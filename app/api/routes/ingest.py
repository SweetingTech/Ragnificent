from fastapi import APIRouter
from typing import Optional
import os
import yaml
from pathlib import Path

# Stub imports
from ...config.loader import load_config
from ...ingest.pipeline import IngestionPipeline
from ...state.db import Database
from ...vector.qdrant_client import VectorService

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Dependency Injection (Quick & Dirty for v1)
config = load_config()
state_db_path = os.getenv("STATE_DB_PATH", "rag_library/state/ingest.sqlite")
db = Database(state_db_path)
vector_service = VectorService(config.vector_db.url, config.vector_db.collection_prefix)
pipeline = IngestionPipeline(config, db, vector_service)

@router.post("/run")
async def run_ingest(corpus_id: Optional[str] = None):
    # Run in background ideally, but synchronous for now to see errors
    try:
        pipeline.run_once(corpus_id)
        return {"status": "success", "message": f"Ingestion triggered for {corpus_id or 'all'}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
