"""
Statistics service for retrieving ingestion metrics.
"""
import sqlite3
import os
from threading import Lock
from typing import Dict

from ..utils.logging import setup_logging

logger = setup_logging()


class StatsService:
    """Service for retrieving file processing statistics."""

    def __init__(self, db_path: str):
        """
        Initialize the stats service.

        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = db_path
        self._lock = Lock()

    def get_stats(self) -> Dict[str, int]:
        """
        Get file processing statistics.

        Returns:
            Dictionary with total, success, and failed counts
        """
        if not os.path.exists(self.db_path):
            logger.debug(f"Database not found at {self.db_path}, returning empty stats")
            return {"total": 0, "success": 0, "failed": 0}

        try:
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                    cursor = conn.cursor()

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
        except sqlite3.Error as e:
            logger.error(f"Database error while fetching stats: {e}")
            return {"total": 0, "success": 0, "failed": 0}
        except Exception as e:
            logger.error(f"Unexpected error while fetching stats: {e}")
            return {"total": 0, "success": 0, "failed": 0}

    def get_corpus_stats(self, corpus_id: str) -> Dict[str, int]:
        """
        Get statistics for a specific corpus.

        Args:
            corpus_id: The corpus identifier

        Returns:
            Dictionary with total, success, and failed counts for the corpus
        """
        if not os.path.exists(self.db_path):
            return {"total": 0, "success": 0, "failed": 0}

        try:
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                    cursor = conn.cursor()

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
