"""
Statistics service for retrieving ingestion metrics.
Uses the Database class for consistent connection management.
"""
from typing import Dict, Optional

from .db import Database
from ..utils.logging import setup_logging

logger = setup_logging()


class StatsService:
    """Service for retrieving file processing statistics."""

    def __init__(self, db: Database):
        """
        Initialize the stats service.

        Args:
            db: Database instance for connection management
        """
        self.db = db

    def get_stats(self) -> Dict[str, int]:
        """
        Get file processing statistics.

        Returns:
            Dictionary with total, success, and failed counts
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM files")
                total = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM files WHERE status='SUCCESS'")
                success = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM files WHERE status='FAILED'")
                failed = cursor.fetchone()[0]

                return {
                    "total": total,
                    "success": success,
                    "failed": failed
                }
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            return {"total": 0, "success": 0, "failed": 0}

    def get_corpus_stats(self, corpus_id: str) -> Dict[str, int]:
        """
        Get statistics for a specific corpus.

        Args:
            corpus_id: The corpus identifier

        Returns:
            Dictionary with total, success, and failed counts for the corpus
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM files WHERE corpus_id = ?",
                    (corpus_id,)
                )
                total = cursor.fetchone()[0]

                cursor.execute(
                    "SELECT COUNT(*) FROM files WHERE corpus_id = ? AND status='SUCCESS'",
                    (corpus_id,)
                )
                success = cursor.fetchone()[0]

                cursor.execute(
                    "SELECT COUNT(*) FROM files WHERE corpus_id = ? AND status='FAILED'",
                    (corpus_id,)
                )
                failed = cursor.fetchone()[0]

                return {
                    "total": total,
                    "success": success,
                    "failed": failed
                }
        except Exception as e:
            logger.error(f"Error fetching stats for corpus {corpus_id}: {e}")
            return {"total": 0, "success": 0, "failed": 0}
