"""
Ingestion API routes for triggering document processing.
"""

import asyncio
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
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


def _build_run_log_writer(config: GlobalConfig, corpus_id: Optional[str], job_id: str):
    log_root = Path(config.library_root) / "logs" / "ingest"
    log_root.mkdir(parents=True, exist_ok=True)
    safe_corpus = corpus_id or "all"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_root / f"{timestamp}_{safe_corpus}_{job_id[:8]}.log"

    def write(message: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    return log_path, write


def _invalidate_vector_cache(pipeline: Any, corpus_id: Optional[str]) -> None:
    vector_service = getattr(pipeline, "vector_service", None)
    if vector_service is None or not hasattr(vector_service, "invalidate_cache"):
        return
    if corpus_id:
        vector_service.invalidate_cache(corpus_id)
    else:
        vector_service.invalidate_cache()


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
        _invalidate_vector_cache(pipeline, corpus_id)

        job_id = str(uuid.uuid4())
        log_path, run_logger = _build_run_log_writer(pipeline.config, corpus_id, job_id)
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
            log_file=str(log_path),
        )
        run_logger(
            f"JOB id={job_id} description={desc} qdrant_url={pipeline.config.vector_db.url}"
        )

        def progress_callback(update: Dict[str, Any]) -> None:
            _set_ingest_state(job_id=job_id, **update)

        summary = await asyncio.to_thread(
            pipeline.run_once,
            corpus_id,
            source_path,
            retry_failed_only,
            progress_callback,
            run_logger,
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
        run_logger(
            "SUMMARY "
            f"total_files={summary.get('total_files', 0)} "
            f"files_processed={summary.get('files_processed', 0)} "
            f"files_skipped={summary.get('files_skipped', 0)} "
            f"files_failed={summary.get('files_failed', 0)}"
        )
        _invalidate_vector_cache(pipeline, corpus_id)

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
            log_path = _INGEST_STATE.get("log_file")
            if log_path:
                with Path(log_path).open("a", encoding="utf-8") as handle:
                    handle.write(f"{datetime.now().isoformat(timespec='seconds')} RUN ERROR reason={message}\n")
            _invalidate_vector_cache(pipeline, corpus_id)
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
        log_path = _INGEST_STATE.get("log_file")
        if log_path:
            with Path(log_path).open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat(timespec='seconds')} RUN ERROR reason={e}\n")
        _invalidate_vector_cache(pipeline, corpus_id)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@router.get("/status")
async def ingest_status():
    """
    Get current ingestion status.

    Returns:
        Current status of the ingestion system
    """
    return JSONResponse(
        content=_get_ingest_state(),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
