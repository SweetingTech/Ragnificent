"""
Ingestion API routes for triggering document processing.
"""

import asyncio
import threading
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, Generator
from functools import lru_cache

from ...config.loader import load_config
from ...config.schema import GlobalConfig
from ...ingest.pipeline import IngestionPipeline
from ...state.db import Database
from ...vector.qdrant_client import VectorService, get_connection_error
from ...services.corpus_service import validate_corpus_id, CorpusValidationError
from ...utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/ingest", tags=["ingest"])
_INGEST_STATE_LOCK = threading.Lock()
_INGEST_STATE: Dict[str, Any] = {
    "status": "idle",
    "message": "No active ingestion jobs",
}


class IngestResponse(BaseModel):
    """Response model for ingestion API."""

    status: str
    message: str
    summary: Optional[Dict[str, Any]] = None


def _set_ingest_state(**updates: Any) -> None:
    with _INGEST_STATE_LOCK:
        _INGEST_STATE.update(updates)


def _get_ingest_state() -> Dict[str, Any]:
    with _INGEST_STATE_LOCK:
        return dict(_INGEST_STATE)


@lru_cache()
def get_config() -> GlobalConfig:
    """Get cached configuration."""
    return load_config()


def get_database() -> Generator[Database, None, None]:
    """
    Get database instance with cleanup.

    Yields the database and closes it when done.
    """
    config = get_config()
    db = Database(config.get_state_db_path())
    try:
        yield db
    finally:
        db.close()


def get_vector_service() -> VectorService:
    """Get vector service instance."""
    config = get_config()
    return VectorService(config.vector_db.url, config.vector_db.collection_prefix)


def get_pipeline(db: Database = Depends(get_database)) -> IngestionPipeline:
    """Get ingestion pipeline instance with database dependency."""
    config = get_config()
    vector_service = get_vector_service()
    return IngestionPipeline(config, db, vector_service)


@router.post("/run", response_model=IngestResponse)
async def run_ingest(
    corpus_id: Optional[str] = None,
    source_path: Optional[str] = None,
    retry_failed_only: bool = False,
    pipeline: IngestionPipeline = Depends(get_pipeline)
):
    """
    Trigger document ingestion.

    Args:
        corpus_id: Optional specific corpus to ingest. If not provided, all corpora are processed.
        source_path: Optional path to scan for documents. Can be any absolute or relative
                     path on the server (e.g. D:/Books, /mnt/nas/documents).
                     When provided, corpus_id must also be given so documents are stored
                     in the correct corpus collection.  The corpus must already exist.

    Returns:
        Ingestion status and summary
    """
    if source_path and not corpus_id:
        raise HTTPException(
            status_code=400,
            detail="corpus_id is required when source_path is provided"
        )

    # Validate corpus_id if provided
    if corpus_id:
        try:
            validate_corpus_id(corpus_id)
        except CorpusValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        job_id = str(uuid.uuid4())
        desc = corpus_id or "all corpora"
        if source_path:
            desc = f"{corpus_id} (source: {source_path})"
        if retry_failed_only:
            desc = f"failed files for {desc}"

        _set_ingest_state(
            job_id=job_id,
            status="running",
            message=f"Starting ingestion for {desc}",
            corpus_id=corpus_id,
            source_path=source_path,
            started_at=time.time(),
            current_corpus=corpus_id,
            current_file=None,
            total_files=0,
            files_completed=0,
            files_processed=0,
            files_skipped=0,
            files_failed=0,
            percent_complete=0.0,
            retry_failed_only=retry_failed_only,
            summary=None,
        )

        def progress_callback(update: Dict[str, Any]) -> None:
            _set_ingest_state(job_id=job_id, **update)

        summary = await asyncio.to_thread(
            pipeline.run_once,
            corpus_id,
            source_path,
            retry_failed_only,
            progress_callback,
        )

        _set_ingest_state(
            job_id=job_id,
            status="success",
            message=f"Ingestion completed for {desc}",
            summary=summary,
            current_file=None,
            percent_complete=100.0,
            finished_at=time.time(),
        )

        return IngestResponse(
            status="success",
            message=f"Ingestion completed for {desc}",
            summary=summary
        )
    except Exception as e:
        if get_connection_error(e):
            message = f"Cannot reach Qdrant at {pipeline.config.vector_db.url}. Is it running?"
            logger.warning(f"{message} Original error: {e}")
            _set_ingest_state(
                status="error",
                message=message,
                finished_at=time.time(),
            )
            return JSONResponse(
                status_code=503,
                content=IngestResponse(status="error", message=message).model_dump(
                    exclude_none=True
                ),
            )

        logger.exception(
            f"Ingestion failed unexpectedly for {corpus_id or 'all corpora'}"
        )
        _set_ingest_state(
            status="error",
            message=f"Ingestion failed: {e}",
            finished_at=time.time(),
        )
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@router.get("/status")
async def ingest_status():
    """
    Get current ingestion status.

    Returns:
        Current status of the ingestion system
    """
    return _get_ingest_state()
