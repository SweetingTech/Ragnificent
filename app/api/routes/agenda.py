from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from ...services.corpus_service import CorpusService
from ...vector.qdrant_client import VectorService
from .corpora import get_corpus_service, get_vector_service

router = APIRouter(prefix="/agenda", tags=["agenda"])


@router.get("/evidence")
async def agenda_evidence(
    corpus_service: CorpusService = Depends(get_corpus_service),
    vector_service: VectorService = Depends(get_vector_service),
) -> Dict[str, Any]:
    """Return read-only corpus evidence for Trombone agenda refreshes."""

    corpora: List[Dict[str, Any]] = []
    for meta in corpus_service.get_all_corpora():
        corpus_id = meta.get("corpus_id")
        if not corpus_id:
            continue
        try:
            vector_count = vector_service.get_count(corpus_id)
        except Exception as exc:  # noqa: BLE001
            vector_count = 0
            meta = {**meta, "vector_error": str(exc)}
        corpora.append(
            {
                "corpus_id": corpus_id,
                "description": meta.get("description", ""),
                "vector_count": vector_count,
                "query_endpoint": "/api/query",
                "readOnly": True,
            }
        )
    return {
        "source": "ragnificent",
        "readOnly": True,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "corpora": corpora,
        "agendaEvidenceKinds": ["corpora", "vector_counts", "allowed_query_targets"],
    }
