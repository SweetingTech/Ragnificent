from ..config.schema import GlobalConfig
from ..state.db import Database
from ..vector.qdrant_client import VectorService
from ..utils.logging import setup_logging
from typing import Optional

logger = setup_logging()

class IngestionPipeline:
    def __init__(self, config: GlobalConfig, db: Database, vector_service: VectorService):
        self.config = config
        self.db = db
        self.vector_service = vector_service

    def run_once(self, corpus_id: Optional[str] = None):
        logger.info(f"Starting ingestion run (corpus={corpus_id or 'all'})...")
        # Logic:
        # 1. Scan folders
        # 2. Hash files
        # 3. Check DB for change
        # 4. Extract -> Chunk -> Embed -> Upsert
        # 5. Update DB
        logger.info("Ingestion run complete (stub).")
