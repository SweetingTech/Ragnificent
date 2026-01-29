from fastapi import APIRouter, Header, HTTPException, Form, Request
from pydantic import BaseModel
from typing import List, Optional, Dict
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()

# Need access to templates for HTMX fragments
templates_dir = Path(__file__).parent.parent.parent / "gui" / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

class QueryRequest(BaseModel):
    query: str
    corpus_id: Optional[str] = None
    top_k: int = 5

class QueryResponse(BaseModel):
    query: str
    answer: Optional[str] = None
    hits: List[Dict]

from ...config.loader import load_config
from ...vector.qdrant_client import VectorService
from ...providers.factory import get_embedding_provider, get_llm_provider
from ..query_engine import QueryEngine

# Dependency Setup
config = load_config()
vector_service = VectorService(config.vector_db.url, config.vector_db.collection_prefix)
embedder = get_embedding_provider(config.models.embeddings.provider, config.models.embeddings.base_url, config.models.embeddings.model)

# Try get LLM
try:
    # Use same provider/base_url as embedding for now (Ollama), but model might differ
    # We should add config.models.answer eventually. For now hardcode 'llama3' or reuse logic
    # Assume config has models.llm section or we fallback to defaults
    llm_model = "llama3" # Default
    llm = get_llm_provider("ollama", config.models.embeddings.base_url, llm_model)
except Exception:
    llm = None

engine = QueryEngine(vector_service, embedder, llm)

@router.post("/query", response_model=QueryResponse)
async def query_api(request: QueryRequest):
    # Real Search
    result = engine.query(request.query, request.corpus_id, request.top_k)
    
    # Stub Answer (until LLM 'Answer' provider is added)
    answer = f"Found {len(result['hits'])} vector matches in {result['time']:.2f}s."
    if not result['hits']:
        answer = "No relevant knowledge found (or no corpus selected)."

    return {
        "query": request.query,
        "answer": answer,
        "hits": result['hits']
    }

@router.post("/query/ui")
async def query_ui(request: Request, query: str = Form(...), corpus_id: str = Form(None), llm_model: str = Form(None)):
    # Real Search
    result = engine.query(query, corpus_id=corpus_id, llm_model=llm_model)
    
    hits = result['hits']
    answer_html = f"<p>Parsed {len(hits)} relevant excerpts from <strong>{corpus_id or 'unknown'}</strong>.</p>"
    
    context = {
        "request": request,
        "answer_html": answer_html,
        "hits": hits
    }
    return templates.TemplateResponse("search_results.html", context)
