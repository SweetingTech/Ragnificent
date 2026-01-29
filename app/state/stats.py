import sqlite3
import os
from threading import Lock
from typing import Optional, Dict

class StatsService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = Lock()

    def get_stats(self) -> Dict[str, int]:
        if not os.path.exists(self.db_path):
            return {"total": 0, "success": 0, "failed": 0}

        try:
            with sqlite3.connect(self.db_path) as conn:
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
        except Exception:
            return {"total": 0, "success": 0, "failed": 0}
