"""
GUI routes for the web interface.
Provides HTML pages for dashboard, search, and corpus management.
"""
from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, List, Dict, Any
from functools import lru_cache
from pathlib import Path
import os

from ..config.loader import load_config
from ..config.schema import GlobalConfig
from ..state.stats import StatsService
from ..vector.qdrant_client import VectorService
from ..providers.ollama import OllamaLLM
from ..services.corpus_service import (
    CorpusService,
    validate_corpus_id,
    CorpusValidationError
)
from ..utils.logging import setup_logging

logger = setup_logging()

# Templates configuration
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(prefix="/gui", tags=["gui"])


# Dependency injection functions
@lru_cache()
def get_config() -> GlobalConfig:
    """Get cached configuration."""
    return load_config()


def get_corpus_service() -> CorpusService:
    """Get corpus service instance."""
    config = get_config()
    return CorpusService(config.library_root)


def get_stats_service() -> StatsService:
    """Get stats service instance."""
    config = get_config()
    return StatsService(config.get_state_db_path())


def get_vector_service() -> VectorService:
    """Get vector service instance."""
    config = get_config()
    return VectorService(config.vector_db.url, config.vector_db.collection_prefix)


def get_corpora_with_vectors(
    corpus_service: CorpusService,
    vector_service: VectorService
) -> List[Dict[str, Any]]:
    """
    Get all corpora with their vector counts.

    Args:
        corpus_service: Corpus service instance
        vector_service: Vector service instance

    Returns:
        List of corpus dictionaries with vector counts
    """
    corpora = corpus_service.get_all_corpora()
    result = []
    for c in corpora:
        corpus_data = {
            "corpus_id": c["corpus_id"],
            "description": c.get("description", ""),
            "inbox_path": c.get("inbox_path", ""),
            "vector_count": vector_service.get_count(c["corpus_id"])
        }
        result.append(corpus_data)
    return result


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    config = get_config()
    corpus_service = get_corpus_service()
    stats_service = get_stats_service()
    vector_service = get_vector_service()

    stats = stats_service.get_stats()
    corpora = get_corpora_with_vectors(corpus_service, vector_service)

    total_vectors = sum(c.get("vector_count", 0) for c in corpora)

    context = {
        "request": request,
        "active_page": "dashboard",
        "total_files": stats["total"],
        "success_count": stats["success"],
        "failed_count": stats["failed"],
        "total_vectors": total_vectors,
        "vector_backend": config.vector_db.backend,
        "corpora": corpora
    }
    return templates.TemplateResponse("dashboard.html", context)


@router.get("/corpora", response_class=HTMLResponse)
async def corpora_list(request: Request):
    """Render the corpora list page."""
    corpus_service = get_corpus_service()
    vector_service = get_vector_service()

    context = {
        "request": request,
        "active_page": "corpora",
        "corpora": get_corpora_with_vectors(corpus_service, vector_service)
    }
    return templates.TemplateResponse("corpora.html", context)


@router.get("/search", response_class=HTMLResponse)
async def search_ui(request: Request):
    """Render the search page."""
    config = get_config()
    corpus_service = get_corpus_service()

    # Fetch available models from Ollama
    available_models = OllamaLLM.list_models(base_url=config.models.embeddings.base_url)
    if not available_models:
        available_models = ["llama3", "mistral"]  # Fallback defaults

    corpora = corpus_service.get_all_corpora()

    context = {
        "request": request,
        "active_page": "search",
        "corpora": corpora,
        "available_models": available_models
    }
    return templates.TemplateResponse("search.html", context)


@router.get("/corpora/new", response_class=HTMLResponse)
async def new_corpus_ui(request: Request):
    """Render the create corpus page."""
    return templates.TemplateResponse(
        "create_corpus.html",
        {"request": request, "active_page": "corpora"}
    )


@router.post("/corpora/create")
async def create_corpus(
    request: Request,
    corpus_id: str = Form(...),
    description: str = Form(...),
    source_path: str = Form(...),
    llm_model: str = Form("llama3")
):
    """
    Create a new corpus.

    Args:
        request: FastAPI request object
        corpus_id: Unique identifier for the corpus
        description: Human-readable description
        source_path: Path to source documents
        llm_model: LLM model to use for this corpus

    Returns:
        Redirect to dashboard on success
    """
    corpus_service = get_corpus_service()
    vector_service = get_vector_service()

    # Validate corpus_id using the service
    try:
        validate_corpus_id(corpus_id)
    except CorpusValidationError as e:
        logger.warning(f"Invalid corpus ID: {corpus_id} - {e}")
        return HTMLResponse(f"Invalid corpus ID: {e}", status_code=400)

    # Validate source_path (basic check - must not be empty)
    if not source_path or not source_path.strip():
        return HTMLResponse("Source path is required", status_code=400)

    # Check if corpus already exists
    if corpus_service.corpus_exists(corpus_id):
        return HTMLResponse(f"Corpus '{corpus_id}' already exists", status_code=400)

    try:
        # Create corpus using the service (handles sanitization)
        corpus_service.create_corpus(
            corpus_id=corpus_id,
            description=description,
            source_path=source_path.strip(),
            llm_model=llm_model
        )

        # Create vector collection
        vector_service.ensure_collection(corpus_id)

        logger.info(f"Created new corpus: {corpus_id}")
        return RedirectResponse(url="/gui/dashboard", status_code=303)

    except Exception as e:
        logger.error(f"Failed to create corpus {corpus_id}: {e}")
        return HTMLResponse(f"Failed to create corpus: {e}", status_code=500)


@router.get("/corpora/{corpus_id}", response_class=HTMLResponse)
async def manage_corpus(request: Request, corpus_id: str):
    """
    Render the corpus management page.

    Args:
        request: FastAPI request object
        corpus_id: ID of the corpus to manage

    Returns:
        HTML page for corpus management
    """
    corpus_service = get_corpus_service()
    vector_service = get_vector_service()

    # Validate corpus_id to prevent path traversal
    try:
        validate_corpus_id(corpus_id)
    except CorpusValidationError as e:
        logger.warning(f"Invalid corpus ID in URL: {corpus_id}")
        raise HTTPException(status_code=400, detail=str(e))

    # Get corpus metadata using the service
    metadata = corpus_service.get_corpus_metadata(corpus_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Corpus not found")

    # Get vector count
    v_count = vector_service.get_count(corpus_id)

    # Prepare display data
    config = metadata.get("config", {})
    corpus_data = {
        "corpus_id": metadata["corpus_id"],
        "description": metadata.get("description", ""),
        "source_path": metadata.get("source_path") or metadata.get("inbox_path", ""),
        "model": config.get("models", {}).get("answer", {}).get("model", "Default")
    }

    context = {
        "request": request,
        "active_page": "corpora",
        "corpus": corpus_data,
        "vector_count": v_count
    }
    return templates.TemplateResponse("manage_corpus.html", context)
