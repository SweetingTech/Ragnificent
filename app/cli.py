"""
Command-line interface for the RAG Librarian service.
Provides commands for serving, database initialization, and ingestion.
"""
import argparse
import os
from .config.loader import load_config
from .state.db import Database
from .utils.logging import setup_logging

logger = setup_logging()

# Constants
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8008


def cmd_serve(args):
    """Start the API server."""
    import uvicorn

    logger.info(f"Starting API server on {DEFAULT_HOST}:{DEFAULT_PORT}...")
    uvicorn.run(
        "app.api.server:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        reload=True
    )


def cmd_init_db(args):
    """Initialize the state database."""
    config = load_config(args.config)

    # Use the config method to get state db path (handles env var and fallback)
    db_path = config.get_state_db_path()

    logger.info(f"Initializing database at {db_path}...")
    db = Database(db_path)
    schema_path = os.path.join(os.path.dirname(__file__), "state", "schema.sql")
    db.init_db(schema_path)
    logger.info("Database initialization complete.")


def cmd_ingest(args):
    """Run document ingestion."""
    from .config.loader import load_config
    from .state.db import Database
    from .vector.qdrant_client import VectorService
    from .ingest.pipeline import IngestionPipeline

    config = load_config(args.config)
    db_path = config.get_state_db_path()

    db = Database(db_path)
    vector_service = VectorService(config.vector_db.url, config.vector_db.collection_prefix)
    pipeline = IngestionPipeline(config, db, vector_service)

    corpus_id = getattr(args, 'corpus', None)
    logger.info(f"Running ingestion for corpus: {corpus_id or 'all'}")

    try:
        pipeline.run_once(corpus_id)
        logger.info("Ingestion completed successfully.")
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise
    finally:
        db.close()


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="RAG Librarian CLI - Document ingestion and retrieval service"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)"
    )

    subparsers = parser.add_subparsers(dest="command")

    # Serve command
    subparsers.add_parser("serve", help="Start the API server")

    # Init-db command
    subparsers.add_parser("init-db", help="Initialize the state database")

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Run document ingestion")
    ingest_parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (default behavior)"
    )
    ingest_parser.add_argument(
        "--corpus",
        type=str,
        default=None,
        help="Specific corpus ID to ingest (default: all)"
    )

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
