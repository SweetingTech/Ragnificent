"""
Thread-safe SQLite database connection manager.
Uses thread-local storage to ensure each thread has its own connection.
"""
import sqlite3
import os
import threading
from typing import Generator
from contextlib import contextmanager
from ..utils.logging import setup_logging

logger = setup_logging()


class Database:
    """
    Thread-safe SQLite database manager using thread-local connections.

    Each thread gets its own connection to avoid SQLite threading issues.
    Connections are created lazily and stored in thread-local storage.
    """

    def __init__(self, db_path: str):
        """
        Initialize the database manager.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure_directory(self) -> None:
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def _get_thread_connection(self) -> sqlite3.Connection:
        """
        Get or create a connection for the current thread.

        Returns:
            SQLite connection for this thread
        """
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._ensure_directory()
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent read performance
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.connection = conn
            logger.debug(f"Created new database connection for thread {threading.current_thread().name}")
        return self._local.connection

    def get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection for the current thread.

        Returns:
            SQLite connection for this thread
        """
        return self._get_thread_connection()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database transactions.

        Automatically commits on success or rolls back on exception.

        Yields:
            SQLite connection within a transaction

        Example:
            with db.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO ...")
        """
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Context manager for database cursor operations.

        Automatically commits on success or rolls back on exception.

        Yields:
            SQLite cursor within a transaction
        """
        with self.transaction() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def init_db(self, schema_path: str) -> None:
        """
        Initialize the database schema.

        Args:
            schema_path: Path to the SQL schema file
        """
        with self._lock:
            if self._initialized:
                logger.debug("Database already initialized")
                return

            with self.transaction() as conn:
                with open(schema_path, 'r') as f:
                    schema = f.read()
                conn.executescript(schema)

            self._initialized = True
            logger.info(f"Database initialized at {self.db_path}")

    def close(self) -> None:
        """Close the connection for the current thread."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
            logger.debug(f"Closed database connection for thread {threading.current_thread().name}")

    def close_all(self) -> None:
        """
        Close all thread-local connections.

        Note: This only closes the connection for the calling thread.
        Each thread should call close() when done.
        """
        self.close()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        Execute a query and return the cursor.

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            Cursor with query results
        """
        conn = self.get_connection()
        return conn.execute(query, params)

    def execute_commit(self, query: str, params: tuple = ()) -> None:
        """
        Execute a query and commit immediately.

        Args:
            query: SQL query to execute
            params: Query parameters
        """
        with self.transaction() as conn:
            conn.execute(query, params)
