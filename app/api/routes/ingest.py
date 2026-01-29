"""
Ingestion API routes for triggering document processing.
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from functools import lru_cache

from ...config.loader import load_config
from ...config.schema import GlobalConfig
from ...ingest.pipeline import IngestionPipeline
from ...state.db import Database
from ...vector.qdrant_client import VectorService
from ...services.corpus_service import validate_corpus_id, CorpusValidationError
from ...utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestResponse(BaseModel):
    """Response model for ingestion API."""
    status: str
    message: str
    summary: Optional[Dict[str, Any]] = None


@lru_cache()
def get_config() -> GlobalConfig:
    """Get cached configuration."""
    return load_config()


def get_database() -> Database:
    """Get database instance."""
    config = get_config()
    return Database(config.get_state_db_path())


def get_vector_service() -> VectorService:
    """Get vector service instance."""
    config = get_config()
    return VectorService(config.vector_db.url, config.vector_db.collection_prefix)


def get_pipeline() -> IngestionPipeline:
    """Get ingestion pipeline instance."""
    config = get_config()
    db = get_database()
    vector_service = get_vector_service()
    return IngestionPipeline(config, db, vector_service)


@router.post("/run", response_model=IngestResponse)
async def run_ingest(
    corpus_id: Optional[str] = None,
    pipeline: IngestionPipeline = Depends(get_pipeline)
):
    """
    Trigger document ingestion.

    Args:
        corpus_id: Optional specific corpus to ingest. If not provided, all corpora are processed.

    Returns:
        Ingestion status and summary
    """
    # Validate corpus_id if provided
    if corpus_id:
        try:
            validate_corpus_id(corpus_id)
        except CorpusValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        # Run the blocking ingestion in a thread pool to avoid blocking the event loop
        summary = await asyncio.to_thread(pipeline.run_once, corpus_id)

        return IngestResponse(
            status="success",
            message=f"Ingestion completed for {corpus_id or 'all corpora'}",
            summary=summary
        )
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        return IngestResponse(
            status="error",
            message=str(e),
            summary=None
        )


@router.get("/status")
async def ingest_status():
    """
    Get current ingestion status.

    Returns:
        Current status of the ingestion system
    """
    # Placeholder for future implementation
    return {
        "status": "idle",
        "message": "No active ingestion jobs"
    }
