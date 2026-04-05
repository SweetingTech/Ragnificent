"""
GUI routes for the web interface.
"""
import json
import shutil
import yaml
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Any, Optional
from functools import lru_cache
from pathlib import Path

from ..config.loader import load_config
from ..config.schema import GlobalConfig
from ..config.models_catalog import load_models_catalog
from ..config.embedding_presets import load_embedding_presets
from ..state.db import Database
from ..state.stats import StatsService
from ..vector.qdrant_client import VectorService
from ..services.corpus_service import (
    CorpusService,
    validate_corpus_id,
    CorpusValidationError
)
from ..utils.logging import setup_logging

logger = setup_logging()


def _toast(message: str, type: str = "info") -> dict:
    """Build X-Toast header value."""
    return {"X-Toast": json.dumps({"message": message, "type": type})}


templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(prefix="/gui", tags=["gui"])

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
PROVIDER_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# ---------------------------------------------------------------------------
# Cached singletons — created once per process, reused across requests.
# This is the main performance fix: QdrantClient and CorpusService are
# expensive to spin up fresh on every page load.
# ---------------------------------------------------------------------------

@lru_cache()
def get_config() -> GlobalConfig:
    return load_config()


@lru_cache()
def get_vector_service() -> VectorService:
    config = get_config()
    return VectorService(config.vector_db.url, config.vector_db.collection_prefix)


@lru_cache(maxsize=1)
def get_models_catalog() -> dict:
    return load_models_catalog()


@lru_cache(maxsize=1)
def get_embedding_presets() -> dict:
    return load_embedding_presets()


@lru_cache()
def get_corpus_service() -> CorpusService:
    config = get_config()
    return CorpusService(config.library_root)


def get_database() -> Database:
    config = get_config()
    return Database(config.get_state_db_path())


def get_stats_service() -> StatsService:
    return StatsService(get_database())


def get_corpora_with_vectors(
    corpus_service: CorpusService,
    vector_service: VectorService,
) -> List[Dict[str, Any]]:
    corpora = corpus_service.get_all_corpora()
    result = []
    for c in corpora:
        config = c.get("config", {})
        embedding_config = config.get("models", {}).get("embeddings", {})
        chunk_config = config.get("chunking", {}).get("default", {})
        result.append({
            "corpus_id": c["corpus_id"],
            "description": c.get("description", ""),
            "source_path": c.get("source_path") or "",
            "inbox_path": c.get("inbox_path", ""),
            "vector_count": vector_service.get_count(c["corpus_id"]),
            "embedding_provider": embedding_config.get("provider"),
            "embedding_model": embedding_config.get("model"),
            "chunk_strategy": chunk_config.get("strategy"),
        })
    return result


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    config = get_config()
    stats = get_stats_service().get_stats()
    corpora = get_corpora_with_vectors(get_corpus_service(), get_vector_service())
    total_vectors = sum(c.get("vector_count", 0) for c in corpora)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "total_files": stats["total"],
        "success_count": stats["success"],
        "failed_count": stats["failed"],
        "total_vectors": total_vectors,
        "vector_backend": config.vector_db.backend,
        "corpora": corpora,
    })


@router.get("/corpora", response_class=HTMLResponse)
async def corpora_list(request: Request):
    return templates.TemplateResponse("corpora.html", {
        "request": request,
        "active_page": "corpora",
        "corpora": get_corpora_with_vectors(get_corpus_service(), get_vector_service()),
    })


@router.get("/search", response_class=HTMLResponse)
async def search_ui(request: Request):
    config = get_config()
    corpus_service = get_corpus_service()
    corpora = corpus_service.get_all_corpora()

    # Default model name from config (no blocking network call)
    default_model = "llama3"
    if config.models.answer:
        default_model = config.models.answer.model
    elif config.models.embeddings.provider == "ollama":
        default_model = "llama3"

    return templates.TemplateResponse("search.html", {
        "request": request,
        "active_page": "search",
        "corpora": corpora,
        "default_model": default_model,
    })


@router.get("/corpora/new", response_class=HTMLResponse)
async def new_corpus_ui(request: Request):
    config = get_config()
    return templates.TemplateResponse(
        "create_corpus.html",
        {
            "request": request,
            "active_page": "corpora",
            "models_catalog": get_models_catalog(),
            "embedding_presets": get_embedding_presets(),
            "default_answer_provider": config.models.answer.provider if config.models.answer else "ollama",
            "default_answer_model": config.models.answer.model if config.models.answer else "llama3",
            "default_answer_base_url": config.models.answer.base_url if config.models.answer else "",
        }
    )


@router.post("/corpora/create")
async def create_corpus(
    request: Request,
    corpus_id: str = Form(...),
    description: str = Form(...),
    source_path: str = Form(...),
    embedding_preset: str = Form("epub_general"),
    embed_provider: str = Form("openrouter"),
    embed_model: str = Form(...),
    embed_base_url: str = Form(""),
    chunk_strategy: str = Form("heading_then_paragraph"),
    chunk_max_tokens: int = Form(700),
    chunk_overlap_tokens: int = Form(120),
    llm_provider: str = Form("ollama"),
    llm_model: str = Form("llama3"),
    llm_base_url: str = Form(""),
):
    corpus_service = get_corpus_service()

    try:
        validate_corpus_id(corpus_id)
    except CorpusValidationError as e:
        return HTMLResponse(f"Invalid corpus ID: {e}", status_code=400)

    if not source_path or not source_path.strip():
        return HTMLResponse("Source path is required", status_code=400)

    if corpus_service.corpus_exists(corpus_id):
        return HTMLResponse(f"Corpus '{corpus_id}' already exists", status_code=400)

    try:
        corpus_service.create_corpus(
            corpus_id=corpus_id,
            description=description,
            source_path=source_path.strip(),
            llm_model=llm_model,
            llm_provider=llm_provider,
            llm_base_url=(
                llm_base_url.strip()
                or PROVIDER_DEFAULT_BASE_URLS.get(llm_provider.strip(), "")
            ),
            embedding_provider=embed_provider.strip(),
            embedding_model=embed_model.strip(),
            embedding_base_url=(
                embed_base_url.strip()
                or PROVIDER_DEFAULT_BASE_URLS.get(embed_provider.strip(), "")
            ),
            embedding_preset=embedding_preset.strip(),
            chunk_strategy=chunk_strategy.strip(),
            chunk_max_tokens=chunk_max_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
        )
        logger.info(f"Created corpus: {corpus_id}")
        return RedirectResponse(url="/gui/dashboard", status_code=303)
    except Exception as e:
        logger.error(f"Failed to create corpus {corpus_id}: {e}")
        return HTMLResponse(f"Failed to create corpus: {e}", status_code=500)


@router.get("/corpora/{corpus_id}", response_class=HTMLResponse)
async def manage_corpus(request: Request, corpus_id: str):
    corpus_service = get_corpus_service()
    vector_service = get_vector_service()
    db = get_database()

    try:
        validate_corpus_id(corpus_id)
    except CorpusValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    metadata = corpus_service.get_corpus_metadata(corpus_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Corpus not found")

    v_count = vector_service.get_count(corpus_id)
    config = metadata.get("config", {})
    embedding_config = config.get("models", {}).get("embeddings", {})
    chunk_config = config.get("chunking", {}).get("default", {})
    answer_config = config.get("models", {}).get("answer", {})
    embedding_inherited = not bool(embedding_config)
    chunking_inherited = not bool(chunk_config)
    answer_inherited = not bool(answer_config)
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS count FROM files WHERE corpus_id = ? AND status = 'FAILED'",
            (corpus_id,),
        )
        failed_row = cursor.fetchone()
    corpus_data = {
        "corpus_id": metadata["corpus_id"],
        "description": metadata.get("description", ""),
        "source_path": metadata.get("source_path") or metadata.get("inbox_path", ""),
        "inbox_path": metadata.get("inbox_path", ""),
        "model": config.get("models", {}).get("answer", {}).get("model", "Default"),
        "provider": config.get("models", {}).get("answer", {}).get("provider", "ollama"),
        "answer_inherited": answer_inherited,
        "embedding_preset": (
            config.get("embedding_preset")
            or ("Inherited from current defaults" if embedding_inherited else "Custom (saved on corpus)")
        ),
        "embedding_model": embedding_config.get("model", get_config().models.embeddings.model),
        "embedding_provider": embedding_config.get("provider", get_config().models.embeddings.provider),
        "embedding_inherited": embedding_inherited,
        "chunk_strategy": chunk_config.get("strategy", "pdf_sections"),
        "chunk_max_tokens": chunk_config.get("max_tokens", 700),
        "chunk_overlap_tokens": chunk_config.get("overlap_tokens", 80),
        "chunking_inherited": chunking_inherited,
        "failed_files": failed_row["count"] if failed_row else 0,
    }

    return templates.TemplateResponse("manage_corpus.html", {
        "request": request,
        "active_page": "corpora",
        "corpus": corpus_data,
        "vector_count": v_count,
    })


@router.post("/corpora/{corpus_id}/delete")
async def delete_corpus(request: Request, corpus_id: str):
    """Delete a corpus: Qdrant collection + SQLite records + directory."""
    corpus_service = get_corpus_service()
    vector_service = get_vector_service()
    db = get_database()

    try:
        validate_corpus_id(corpus_id)
    except CorpusValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not corpus_service.corpus_exists(corpus_id):
        raise HTTPException(status_code=404, detail="Corpus not found")

    # Drop Qdrant collection
    vector_service.delete_collection(corpus_id)

    # Clean up SQLite
    try:
        with db.transaction() as conn:
            conn.execute("DELETE FROM chunks WHERE corpus_id = ?", (corpus_id,))
            conn.execute("DELETE FROM files WHERE corpus_id = ?", (corpus_id,))
    except Exception as e:
        logger.warning(f"SQLite cleanup failed for {corpus_id}: {e}")

    # Remove directory
    corpus_path = corpus_service.get_corpus_path(corpus_id)
    try:
        shutil.rmtree(corpus_path)
        logger.info(f"Deleted corpus '{corpus_id}'")
    except Exception as e:
        logger.error(f"Failed to remove corpus directory: {e}")
        return HTMLResponse(f"Partial delete — directory removal failed: {e}", status_code=500)

    return RedirectResponse(url="/gui/corpora", status_code=303,
                            headers=_toast(f"Librarian '{corpus_id}' deleted.", "success"))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def settings_ui(request: Request):
    config = get_config()
    embed = config.models.embeddings
    answer = config.models.answer

    # Check which API keys are present in env
    import os
    env_keys = {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
        "OPENROUTER_API_KEY": bool(os.getenv("OPENROUTER_API_KEY")),
    }

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "embed_provider": embed.provider,
        "embed_base_url": embed.base_url or "",
        "embed_model": embed.model,
        "embed_default_notice": "These defaults apply to connection tests and to new corpora only. Existing corpora keep the embedding model they were ingested with.",
        "answer_provider": answer.provider if answer else "ollama",
        "answer_base_url": (answer.base_url or "") if answer else "",
        "answer_model": answer.model if answer else "llama3",
        "env_keys": env_keys,
        "models_catalog": get_models_catalog(),
    })


@router.post("/settings/save")
async def settings_save(
    request: Request,
    embed_provider: str = Form(...),
    embed_base_url: str = Form(""),
    embed_model: str = Form(...),
    answer_provider: str = Form(...),
    answer_base_url: str = Form(""),
    answer_model: str = Form(...),
):
    """Write model settings back to config.yaml."""
    try:
        with open(CONFIG_PATH, "r") as f:
            raw = yaml.safe_load(f)

        embed_provider = embed_provider.strip()
        answer_provider = answer_provider.strip()
        embed_base_url = (
            embed_base_url.strip()
            if embed_provider == "ollama"
            else PROVIDER_DEFAULT_BASE_URLS.get(embed_provider, "")
        )
        answer_base_url = (
            answer_base_url.strip()
            if answer_provider == "ollama"
            else PROVIDER_DEFAULT_BASE_URLS.get(answer_provider, "")
        )

        raw.setdefault("models", {})
        raw["models"]["embeddings"] = {
            "provider": embed_provider,
            "model": embed_model.strip(),
            "base_url": embed_base_url or PROVIDER_DEFAULT_BASE_URLS["ollama"],
        }

        raw["models"]["answer"] = {
            "provider": answer_provider,
            "model": answer_model.strip(),
            "base_url": answer_base_url or PROVIDER_DEFAULT_BASE_URLS["ollama"],
        }

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)

        # Clear cached config so next request reloads it
        get_config.cache_clear()
        get_vector_service.cache_clear()
        get_corpus_service.cache_clear()

        logger.info("Settings saved; config cache cleared.")
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return HTMLResponse(f"Failed to save settings: {e}", status_code=500)

    return RedirectResponse(url="/gui/settings?saved=1", status_code=303,
                            headers=_toast("Settings saved successfully.", "success"))
