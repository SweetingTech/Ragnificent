"""
Health check / heartbeat endpoint.

Returns overall service health plus per-dependency status for Qdrant and
Ollama so any external consumer can tell at a glance whether RAGnificent is
ready to handle requests.

HTTP status codes:
  200  all dependencies reachable
  503  one or more dependencies unreachable (service degraded)
"""
import time
import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])

# Captured once at import time so uptime survives hot-reloads
_SERVICE_START = time.time()


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


@router.get("/health")
def health_check():
    """
    Heartbeat endpoint.

    Probes each downstream dependency and returns a unified health object.
    Callers should poll this endpoint to determine whether RAGnificent is up
    and all its dependencies are reachable before sending queries.
    """
    # Try to pull URLs from config; fall back to defaults if config is broken
    try:
        from ..routes.ingest import get_config
        cfg = get_config()
        qdrant_url = cfg.vector_db.url
        ollama_url = cfg.models.embeddings.base_url
    except Exception:
        qdrant_url = "http://localhost:6333"
        ollama_url = "http://localhost:11434"

    qdrant = _probe_qdrant(qdrant_url)
    ollama = _probe_ollama(ollama_url)

    all_ok = qdrant["status"] == "ok" and ollama["status"] == "ok"
    overall = "ok" if all_ok else "degraded"

    uptime = int(time.time() - _SERVICE_START)
    started_at = datetime.datetime.utcfromtimestamp(_SERVICE_START).isoformat() + "Z"

    body = {
        "status": overall,
        "service": "ragnificent",
        "uptime_seconds": uptime,
        "started_at": started_at,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "dependencies": {
            "qdrant": qdrant,
            "ollama": ollama,
        },
    }

    return JSONResponse(content=body, status_code=200 if all_ok else 503)
