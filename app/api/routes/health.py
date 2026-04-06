"""
Health check / heartbeat endpoint.

Returns overall service health plus per-dependency status for Qdrant and the
currently configured model providers.

HTTP status codes:
  200  all configured dependencies reachable
  503  one or more configured dependencies unreachable (service degraded)
"""
import datetime
import os
import time

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])

# Captured once at import time so uptime survives hot-reloads
_SERVICE_START = time.time()

_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "anthropic": "https://api.anthropic.com/v1",
}
_ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _probe_qdrant(url: str) -> dict:
    try:
        from qdrant_client import QdrantClient

        QdrantClient(url=url, timeout=3).get_collections()
        return {"status": "ok", "url": url}
    except Exception as exc:
        return {"status": "error", "url": url, "detail": str(exc)}


def _probe_ollama(base_url: str) -> dict:
    try:
        from ollama import Client

        Client(host=base_url).list()
        return {"status": "ok", "url": base_url}
    except Exception as exc:
        return {"status": "error", "url": base_url, "detail": str(exc)}


def _probe_openai_compatible(provider: str, base_url: str) -> dict:
    api_key = os.getenv(_ENV_KEY_MAP[provider], "")
    if not api_key:
        return {
            "status": "error",
            "provider": provider,
            "url": base_url,
            "detail": f"Missing {_ENV_KEY_MAP[provider]}",
        }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
        return {"status": "ok", "provider": provider, "url": base_url}
    except Exception as exc:
        return {"status": "error", "provider": provider, "url": base_url, "detail": str(exc)}


def _probe_anthropic(base_url: str) -> dict:
    api_key = os.getenv(_ENV_KEY_MAP["anthropic"], "")
    if not api_key:
        return {
            "status": "error",
            "provider": "anthropic",
            "url": base_url,
            "detail": "Missing ANTHROPIC_API_KEY",
        }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{base_url.rstrip('/')}/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            resp.raise_for_status()
        return {"status": "ok", "provider": "anthropic", "url": base_url}
    except Exception as exc:
        return {"status": "error", "provider": "anthropic", "url": base_url, "detail": str(exc)}


def _probe_provider(provider: str, base_url: str) -> dict:
    normalized_url = (base_url or _DEFAULT_BASE_URLS.get(provider, "")).rstrip("/")

    if provider == "ollama":
        return {"provider": provider, **_probe_ollama(normalized_url)}
    if provider in {"openai", "openrouter"}:
        return _probe_openai_compatible(provider, normalized_url)
    if provider == "anthropic":
        return _probe_anthropic(normalized_url)

    return {
        "status": "error",
        "provider": provider,
        "url": normalized_url,
        "detail": f"Unknown provider '{provider}'",
    }


@router.get("/health")
def health_check():
    """
    Heartbeat endpoint.

    Probes each configured downstream dependency and returns a unified health
    object. Callers should poll this endpoint to determine whether
    RAGnificent is up and its configured services are reachable before sending
    queries.
    """
    try:
        from ..routes.ingest import get_config

        cfg = get_config()
        qdrant_url = cfg.vector_db.url
        embedding_provider = cfg.models.embeddings.provider
        embedding_url = cfg.models.embeddings.base_url or _DEFAULT_BASE_URLS.get(
            embedding_provider, ""
        )

        answer_cfg = cfg.models.answer
        answer_provider = answer_cfg.provider if answer_cfg else None
        answer_url = (
            answer_cfg.base_url or _DEFAULT_BASE_URLS.get(answer_provider, "")
            if answer_cfg
            else None
        )
    except Exception:
        qdrant_url = "http://localhost:6333"
        embedding_provider = "ollama"
        embedding_url = _DEFAULT_BASE_URLS["ollama"]
        answer_provider = None
        answer_url = None

    qdrant = _probe_qdrant(qdrant_url)
    embeddings = _probe_provider(embedding_provider, embedding_url)

    dependencies = {
        "qdrant": qdrant,
        "embeddings": embeddings,
    }

    dependency_statuses = [qdrant["status"], embeddings["status"]]

    if answer_provider:
        answer = _probe_provider(answer_provider, answer_url)
        dependencies["answer"] = answer
        dependency_statuses.append(answer["status"])

    all_ok = all(status == "ok" for status in dependency_statuses)
    overall = "ok" if all_ok else "degraded"

    uptime = int(time.time() - _SERVICE_START)
    started_at = datetime.datetime.utcfromtimestamp(_SERVICE_START).isoformat() + "Z"

    body = {
        "status": overall,
        "service": "ragnificent",
        "uptime_seconds": uptime,
        "started_at": started_at,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "dependencies": dependencies,
    }

    return JSONResponse(content=body, status_code=200 if all_ok else 503)
