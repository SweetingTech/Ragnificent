import argparse
import sys
import os
from .config.loader import load_config
from .state.db import Database

def cmd_serve(args):
    import uvicorn
    # Loading config to get port/host could be done here if we want to honor config.yaml
    # For now, hardcode defaults or read from args (which we don't have for port/host yet)
    # The .env says API_PORT=8008. 
    # Let's just use the hardcoded 8008 for now as per instructions.
    print("Starting API server on port 8008...")
    uvicorn.run("app.api.server:app", host="0.0.0.0", port=8008, reload=True)

def cmd_init_db(args):
    config = load_config(args.config)
    db_path = os.getenv("STATE_DB_PATH", config.ingest.lock_file.replace(".locks/ingest.lock", "state/ingest.sqlite")) 
    # Fallback logic for db path if not in env, usually it's in config or env.
    # The .env.example says STATE_DB_PATH. config.yaml doesn't explicitly have state db path in global, 
    # but the idea.md implies it's configurable.
    # Let's assume passed via env or default.
    
    if not db_path:
        db_path = "rag_library/state/ingest.sqlite"
        
    print(f"Initializing database at {db_path}...")
    db = Database(db_path)
    schema_path = os.path.join(os.path.dirname(__file__), "state", "schema.sql")
    db.init_db(schema_path)
    print("Done.")

def main():
    parser = argparse.ArgumentParser(description="RAG Librarian CLI")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    
    subparsers = parser.add_subparsers(dest="command")
    
    serve_parser = subparsers.add_parser("serve", help="Start the API server")
    
    init_db_parser = subparsers.add_parser("init-db", help="Initialize the state database")
    
    ingest_parser = subparsers.add_parser("ingest", help="Run ingestion")
    ingest_parser.add_argument("--once", action="store_true", help="Run once and exit")

    args = parser.parse_args()
    
    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "ingest":
        print("Ingestion not implemented yet.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
