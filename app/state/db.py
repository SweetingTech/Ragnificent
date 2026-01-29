import sqlite3
import os
from typing import Optional
from ..utils.logging import setup_logging

logger = setup_logging()

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init_db(self, schema_path: str):
        conn = self.get_connection()
        with open(schema_path, 'r') as f:
            schema = f.read()
        conn.executescript(schema)
        conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
