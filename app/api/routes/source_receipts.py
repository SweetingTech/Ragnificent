"""Authenticated source receipt and exact-file ingestion routes.

This is the only supported machine-to-machine intake boundary for new
Voltron/Agent Harness sources.  Legacy corpus creation and source-path
overrides remain available only during the documented migration window.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ...config.schema import GlobalConfig
from ...ingest.pipeline import IngestionPipeline
from ...security import require_source_receipt_token
from ...services.source_receipt_service import (
    SourceReceiptError,
    SourceReceiptNotFound,
    SourceReceiptService,
)
from ...state.db import Database
from .ingest import get_config, get_database, get_pipeline


router = APIRouter(
    prefix="/source-receipts",
    tags=["source-receipts"],
    dependencies=[Depends(require_source_receipt_token)],
)

_SIMPLE_ID = r"^[a-zA-Z0-9_-]{1,64}$"
_HASH = r"^[a-fA-F0-9]{64}$"
_REPOSITORY_SEGMENT = r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}"
_REPOSITORY_ID = rf"^{_REPOSITORY_SEGMENT}(?:/{_REPOSITORY_SEGMENT})?$"
_GIT_COMMIT = r"^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$"


class SourceLocatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_id: Annotated[str, Field(pattern=_SIMPLE_ID)]
    relative_path: Annotated[str, Field(min_length=1, max_length=512)]


class DocumentationProvenanceRequest(BaseModel):
    """Canonical repository identity for the documentation receipt lane.

    The snapshot root/path remains server-side.  These fields are safe to
    return through query citations so agents can find the source README/docs
    file and the exact Git revision that was indexed.
    """

    model_config = ConfigDict(extra="forbid")
    repository: Annotated[str, Field(pattern=_REPOSITORY_ID)]
    path: Annotated[str, Field(min_length=1, max_length=512)]
    git_commit: Annotated[str, Field(pattern=_GIT_COMMIT)]


class DocumentationProvenanceResponse(DocumentationProvenanceRequest):
    """Stored citation provenance with the receipt-verified content hash."""

    content_sha256: Annotated[str, Field(pattern=_HASH)]


class SourceReceiptCreateRequest(BaseModel):
    # ``wiki_publication`` is intentionally absent and unknown fields are
    # rejected: publication authority is computed from trusted corpus config.
    model_config = ConfigDict(extra="forbid")
    workspace_id: Annotated[str, Field(pattern=_SIMPLE_ID)]
    corpus_id: Annotated[str, Field(pattern=_SIMPLE_ID)]
    source_kind: Annotated[str, Field(pattern=_SIMPLE_ID)]
    source_system: Annotated[str, Field(pattern=_SIMPLE_ID)]
    source_record_id: Optional[Annotated[str, Field(max_length=160)]] = None
    source_locator: SourceLocatorRequest
    content_sha256: Annotated[str, Field(pattern=_HASH)]
    title: Optional[Annotated[str, Field(max_length=240)]] = None
    documentation_provenance: Optional[DocumentationProvenanceRequest] = None
    privacy: Literal["internal", "restricted", "local_only"] = "internal"
    correlation_id: Optional[Annotated[str, Field(max_length=160)]] = None
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]


class SourceReceiptResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    receipt_id: str
    canonical_locator: str
    workspace_id: str
    corpus_id: str
    source_kind: str
    source_system: str
    source_record_id: Optional[str] = None
    source_locator: SourceLocatorRequest
    content_sha256: str
    title: Optional[str] = None
    documentation_provenance: Optional[DocumentationProvenanceResponse] = None
    privacy: str
    wiki_publication: Literal["private_wiki_allowed", "local_only"]
    correlation_id: Optional[str] = None
    idempotency_key: str
    status: str
    received_at: Optional[str] = None
    ingested_at: Optional[str] = None
    indexed_file_hash: Optional[str] = None
    ingest_summary: Optional[dict[str, Any]] = None
    model_policy: dict[str, str]


def get_receipt_service(
    config: GlobalConfig = Depends(get_config),
    db: Database = Depends(get_database),
) -> SourceReceiptService:
    return SourceReceiptService(config, db)


def _receipt_error(exc: SourceReceiptError) -> HTTPException:
    if isinstance(exc, SourceReceiptNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("", response_model=SourceReceiptResponse, status_code=status.HTTP_201_CREATED)
def create_source_receipt(
    body: SourceReceiptCreateRequest,
    service: SourceReceiptService = Depends(get_receipt_service),
):
    """Record a hash-verified, root-anchored source before any ingestion work."""
    try:
        record, created = service.create_receipt(body.model_dump())
    except SourceReceiptError as exc:
        raise _receipt_error(exc) from exc
    response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    # FastAPI uses the decorator's default status unless the response object is
    # returned. Keeping idempotent retries visibly successful is useful for a
    # queued Agent Harness publisher and still preserves a stable receipt ID.
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=response_status, content=record)


@router.get("/{receipt_id}", response_model=SourceReceiptResponse)
def get_source_receipt(
    receipt_id: str,
    service: SourceReceiptService = Depends(get_receipt_service),
):
    try:
        return service.get_receipt(receipt_id)
    except SourceReceiptError as exc:
        raise _receipt_error(exc) from exc


@router.post("/{receipt_id}/ingest", response_model=SourceReceiptResponse)
def ingest_source_receipt(
    receipt_id: str,
    service: SourceReceiptService = Depends(get_receipt_service),
    pipeline: IngestionPipeline = Depends(get_pipeline),
):
    """Ingest exactly the hash-verified file named by an accepted receipt."""
    try:
        receipt = service.get_receipt(receipt_id)
        locator = service.resolve_receipt_file(receipt)
    except SourceReceiptError as exc:
        raise _receipt_error(exc) from exc

    try:
        summary = pipeline.ingest_receipted_file(
            corpus_id=receipt["corpus_id"],
            file_path=str(locator.path),
            receipt_id=receipt["receipt_id"],
            canonical_locator=receipt["canonical_locator"],
            expected_hash=receipt["content_sha256"],
            documentation_provenance=receipt.get("documentation_provenance"),
        )
        service.mark_ingested(receipt_id, summary)
        return service.get_receipt(receipt_id)
    except Exception:  # The details may contain filesystem/provider data.
        service.mark_failed(receipt_id, "ingest_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Receipt ingestion failed. Inspect the controlled ingest logs with the correlation ID.",
        )
