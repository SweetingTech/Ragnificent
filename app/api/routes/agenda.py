import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...services.corpus_service import CorpusService
from ...vector.qdrant_client import VectorService
from .corpora import get_corpus_service, get_vector_service
from .query import get_query_engine

router = APIRouter(prefix="/agenda", tags=["agenda"])


class AgendaEvidenceRequest(BaseModel):
    """Read-only agenda evidence request for governed retrieval."""

    query: Optional[str] = None
    corpus_id: Optional[str] = None
    allowed_corpora: List[str] = Field(default_factory=list)
    denied_corpora: List[str] = Field(default_factory=list)
    top_k: int = 6
    include_answer: bool = False


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _excerpt(value: Any, limit: int = 1200) -> str:
    text = str(value or "")
    return text[:limit]


def _corpus_inventory(
    corpus_service: CorpusService,
    vector_service: VectorService,
) -> List[Dict[str, Any]]:
    corpora: List[Dict[str, Any]] = []
    for meta in corpus_service.get_all_corpora():
        corpus_id = meta.get("corpus_id")
        if not corpus_id:
            continue
        try:
            vector_count = vector_service.get_count(corpus_id)
            vector_error = None
        except Exception as exc:  # noqa: BLE001
            vector_count = 0
            vector_error = str(exc)
        entry = {
            "corpus_id": corpus_id,
            "description": meta.get("description", ""),
            "vector_count": vector_count,
            "query_endpoint": "/api/query",
            "agenda_brief_endpoint": "/api/agenda/evidence/brief",
            "readOnly": True,
        }
        if vector_error:
            entry["vector_error"] = vector_error
        corpora.append(entry)
    return corpora


def _effective_corpora(
    corpora: List[Dict[str, Any]],
    request: AgendaEvidenceRequest,
) -> Dict[str, Any]:
    available = {str(item["corpus_id"]) for item in corpora}
    allowed = set(request.allowed_corpora or available)
    denied = set(request.denied_corpora or [])
    if request.corpus_id and request.corpus_id not in {"__all__", "all", "*"}:
        allowed = {request.corpus_id}
    effective = sorted((available & allowed) - denied)
    requested_denied = bool(request.corpus_id and request.corpus_id in denied)
    return {
        "requested": request.corpus_id or "__all__",
        "available": sorted(available),
        "allowed": sorted(allowed & available),
        "denied": sorted(denied),
        "effective": effective,
        "queryAllowed": bool(effective) and not requested_denied,
        "readOnly": True,
        "note": "Agenda retrieval uses allow/deny filters supplied by Trombone and never ingests or mutates corpora.",
    }


def _citation_from_hit(hit: Dict[str, Any], index: int) -> Dict[str, Any]:
    payload = hit.get("payload") if isinstance(hit.get("payload"), dict) else {}
    text = _excerpt(payload.get("text") or hit.get("text") or hit.get("content"))
    corpus_id = str(payload.get("corpus_id") or hit.get("corpusId") or "unknown")
    file_name = str(payload.get("file_name") or payload.get("source") or hit.get("id") or f"hit-{index}")
    page = payload.get("page", payload.get("chunk_index"))
    source_ref = f"{corpus_id}:{file_name}:{page if page is not None else index}"
    return {
        "source_kind": "ragnificent_vector_hit",
        "source_ref": source_ref,
        "corpus_id": corpus_id,
        "file_name": file_name,
        "page": page,
        "score": hit.get("score"),
        "excerpt": text,
        "content_hash": _hash_text(text),
        "payload": {
            "hit_id": hit.get("id"),
            "metadata": {key: value for key, value in payload.items() if key != "text"},
        },
    }


@router.get("/evidence")
async def agenda_evidence(
    corpus_service: CorpusService = Depends(get_corpus_service),
    vector_service: VectorService = Depends(get_vector_service),
) -> Dict[str, Any]:
    """Return read-only corpus inventory for Trombone agenda refreshes."""

    corpora = _corpus_inventory(corpus_service, vector_service)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "system": "RAGnificent",
        "evidenceType": "governed_retrieval",
        "generatedAt": generated_at,
        "readOnly": True,
        "confidence": 0.82,
        "capabilities": ["corpus_inventory", "corpus_search", "citation_return", "policy_filtering"],
        "sources": [
            {
                "kind": "corpus",
                "ref": str(corpus["corpus_id"]),
                "title": str(corpus["corpus_id"]),
                "confidence": 0.75 if corpus.get("vector_count") else 0.35,
            }
            for corpus in corpora
        ],
        "brief": {
            "corpora": corpora,
            "allowedCorpora": [str(corpus["corpus_id"]) for corpus in corpora],
            "deniedCorpora": [],
            "queryTargets": [str(corpus["corpus_id"]) for corpus in corpora if corpus.get("vector_count")],
            "citations": [],
            "retrievalPolicy": {
            "callerSuppliesAllowedCorpora": True,
            "callerSuppliesDeniedCorpora": True,
            "mutationAllowed": False,
            },
        },
        "risks": ["Results depend on corpus freshness."],
        "warnings": [],
        "metadata": {
            "source": "ragnificent",
            "agendaEvidenceKinds": ["corpora", "vector_counts", "governed_retrieval", "citations"],
        },
    }


@router.post("/evidence/brief")
async def agenda_evidence_brief(
    request: AgendaEvidenceRequest,
    corpus_service: CorpusService = Depends(get_corpus_service),
    vector_service: VectorService = Depends(get_vector_service),
) -> Dict[str, Any]:
    """Return a bounded, citation-backed RAGnificent evidence brief."""

    corpora = _corpus_inventory(corpus_service, vector_service)
    policy = _effective_corpora(corpora, request)
    top_k = max(1, min(int(request.top_k or 6), 20))
    citations: List[Dict[str, Any]] = []
    answer: Optional[str] = None
    query_error: Optional[str] = None

    if request.query and policy["queryAllowed"]:
        engine = get_query_engine()
        corpus_id = request.corpus_id
        if not corpus_id or corpus_id in {"__all__", "all", "*"}:
            corpus_id = "__all__"
        elif corpus_id not in policy["effective"]:
            query_error = f"Corpus '{corpus_id}' is not allowed for this agenda evidence request."
        if not query_error:
            result = await asyncio.to_thread(engine.query, request.query, corpus_id, top_k, None)
            hits = result.get("hits") if isinstance(result, dict) else []
            citations = [
                _citation_from_hit(hit, index)
                for index, hit in enumerate(hits if isinstance(hits, list) else [])
                if isinstance(hit, dict)
            ]
            if request.include_answer:
                answer = result.get("answer") if isinstance(result, dict) else None
    elif request.query and not policy["queryAllowed"]:
        query_error = "No allowed RAGnificent corpora were available for this agenda evidence request."

    generated_at = datetime.now(timezone.utc).isoformat()
    warnings = [query_error] if query_error else []
    return {
        "system": "RAGnificent",
        "evidenceType": "governed_retrieval",
        "generatedAt": generated_at,
        "readOnly": True,
        "confidence": 0.86 if citations else 0.55,
        "capabilities": ["corpus_search", "citation_return", "policy_filtering"],
        "sources": [
            {
                "kind": "corpus",
                "ref": str(citation.get("corpus_id") or "unknown"),
                "title": str(citation.get("file_name") or citation.get("source_ref") or "RAGnificent citation"),
                "citationId": str(citation.get("source_ref") or citation.get("payload", {}).get("hit_id") or ""),
                "contentHash": str(citation.get("content_hash") or ""),
                "confidence": float(citation.get("score") or 0.75),
            }
            for citation in citations
        ],
        "brief": {
            "query": request.query,
            "policy": policy,
            "corpora": corpora,
            "answer": answer,
            "allowedCorpora": policy["allowed"],
            "deniedCorpora": policy["denied"],
            "queryTargets": policy["effective"],
            "citations": citations,
        },
        "risks": ["Results depend on corpus freshness."],
        "warnings": warnings,
        "metadata": {
            "source": "ragnificent",
            "agendaEvidenceKinds": ["corpora", "governed_vector_search", "citation_excerpts", "source_confidence"],
        },
    }
