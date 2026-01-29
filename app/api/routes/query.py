"""
Query API routes for search and RAG functionality.
"""
import asyncio
from fastapi import APIRouter, Form, Request, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from functools import lru_cache
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ...config.loader import load_config
from ...config.schema import GlobalConfig
from ...vector.qdrant_client import VectorService
from ...providers.factory import get_embedding_provider, get_llm_provider
from ...providers.base import EmbeddingProvider, LLMProvider
from ..query_engine import QueryEngine
from ...utils.logging import setup_logging

logger = setup_logging()

router = APIRouter()

# Templates for HTMX fragments
templates_dir = Path(__file__).parent.parent.parent / "gui" / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


class QueryRequest(BaseModel):
    """Request model for query API."""
    query: str
    corpus_id: Optional[str] = None
    top_k: int = 5
    llm_model: Optional[str] = None


class QueryResponse(BaseModel):
    """Response model for query API."""
    query: str
    answer: Optional[str] = None
    hits: List[Dict[str, Any]]
    time: Optional[float] = None


@lru_cache()
def get_config() -> GlobalConfig:
    """Get cached configuration."""
    return load_config()


def get_vector_service() -> VectorService:
    """Get vector service instance."""
    config = get_config()
    return VectorService(config.vector_db.url, config.vector_db.collection_prefix)


def get_embedder() -> EmbeddingProvider:
    """Get embedding provider instance."""
    config = get_config()
    return get_embedding_provider(
        config.models.embeddings.provider,
        config.models.embeddings.base_url,
        config.models.embeddings.model
    )


def get_default_llm() -> Optional[LLMProvider]:
    """Get default LLM provider instance."""
    config = get_config()
    try:
        # Use answer model config if available, otherwise fall back to defaults
        if config.models.answer:
            return get_llm_provider(
                config.models.answer.provider,
                config.models.answer.base_url,
                config.models.answer.model
            )
        else:
            # Fall back to using embedding provider's base_url with default model
            return get_llm_provider(
                "ollama",
                config.models.embeddings.base_url,
                "llama3"
            )
    except Exception as e:
        logger.warning(f"Failed to initialize default LLM: {e}")
        return None


def get_query_engine() -> QueryEngine:
    """Get query engine instance."""
    return QueryEngine(
        vector_service=get_vector_service(),
        embedder=get_embedder(),
        default_llm=get_default_llm()
    )


@router.post("/query", response_model=QueryResponse)
async def query_api(
    request: QueryRequest,
    engine: QueryEngine = Depends(get_query_engine)
):
    """
    Execute a RAG query.

    Args:
        request: Query request with query text, optional corpus_id, and top_k

    Returns:
        Query response with answer and source hits
    """
    # Run the potentially blocking query in a thread pool
    result = await asyncio.to_thread(
        engine.query,
        request.query,
        request.corpus_id,
        request.top_k,
        request.llm_model
    )

    # Use the actual answer from the engine (LLM-generated)
    answer = result.get('answer')
    if answer is None and result['hits']:
        answer = f"Found {len(result['hits'])} relevant matches."
    elif answer is None:
        answer = "No relevant knowledge found (or no corpus selected)."

    return QueryResponse(
        query=request.query,
        answer=answer,
        hits=result['hits'],
        time=result.get('time')
    )


@router.post("/query/ui")
async def query_ui(
    request: Request,
    query: str = Form(...),
    corpus_id: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None),
    engine: QueryEngine = Depends(get_query_engine)
):
    """
    Execute a query and return HTML response for HTMX.

    Args:
        request: FastAPI request object
        query: Search query text
        corpus_id: Optional corpus to search
        llm_model: Optional LLM model override

    Returns:
        HTML template response with search results
    """
    # Run the potentially blocking query in a thread pool
    result = await asyncio.to_thread(
        engine.query,
        query,
        corpus_id,
        5,  # default top_k
        llm_model
    )

    hits = result['hits']
    answer = result.get('answer')

    # Build response context
    context = {
        "request": request,
        "query": query,
        "corpus_id": corpus_id,
        "answer": answer,
        "hits": hits,
        "time": result.get('time', 0)
    }

    return templates.TemplateResponse("search_results.html", context)
