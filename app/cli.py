"""
Command-line interface for the RAG Librarian service.
Provides commands for serving, database initialization, and ingestion.
"""
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root before anything else
load_dotenv(Path(__file__).parent.parent / ".env")

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
        reload=True,
        reload_dirs=["app", "."],
        reload_includes=["*.py", "*.html", "*.yaml", "*.css"],
        reload_excludes=["rag_library/*", ".git/*", "*.sqlite", "*.lock", "*.pyc"],
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


def cmd_ingest_file(args):
    """Ingest a specific file directly into a corpus (e.g., from Discord/OpenClaw)."""
    import shutil
    import uuid
    from pathlib import Path
    from .config.loader import load_config
    from .state.db import Database
    from .vector.qdrant_client import VectorService
    from .ingest.pipeline import IngestionPipeline

    config = load_config(args.config)
    db_path = config.get_state_db_path()

    # Verify corpus exists
    from .services.corpus_service import CorpusService
    corpus_service = CorpusService(config.library_root)
    corpus_metadata = corpus_service.get_corpus_metadata(args.corpus)
    if not corpus_metadata:
        logger.error(f"Corpus {args.corpus} not found.")
        return

    # If source_path exists in config, we should drop it there for run_once to find it.
    # Otherwise, fallback to inbox_path
    target_path = Path(corpus_metadata.get("source_path") or corpus_metadata["inbox_path"])
    source_file = Path(args.file)

    if not source_file.exists():
        logger.error(f"Source file {source_file} does not exist.")
        return

    # Create a unique filename in the target to prevent overwriting
    # We prefix with a short uuid to ensure uniqueness while keeping the original extension
    unique_id = str(uuid.uuid4())[:8]
    dest_name = f"{source_file.stem}_{unique_id}{source_file.suffix}"
    dest_file = target_path / dest_name

    logger.info(f"Copying {source_file} to {dest_file}")
    shutil.copy2(source_file, dest_file)

    # Initialize and run pipeline just for this corpus
    db = Database(db_path)
    vector_service = VectorService(config.vector_db.url, config.vector_db.collection_prefix)
    pipeline = IngestionPipeline(config, db, vector_service)

    logger.info(f"Running ingestion for corpus: {args.corpus}")
    try:
        pipeline.run_once(args.corpus)
        logger.info("Single file ingestion completed successfully.")
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

    # Ingest file command
    ingest_file_parser = subparsers.add_parser("ingest-file", help="Ingest a specific file (e.g., from Discord)")
    ingest_file_parser.add_argument(
        "file",
        type=str,
        help="Path to the file to ingest"
    )
    ingest_file_parser.add_argument(
        "--corpus",
        type=str,
        required=True,
        help="Specific corpus ID to ingest into"
    )

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "ingest-file":
        cmd_ingest_file(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
