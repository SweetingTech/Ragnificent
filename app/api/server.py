from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from fastapi.staticfiles import StaticFiles
from .routes import health, query, ingest, corpora
from ..gui import routes as gui_routes
from ..utils.logging import setup_logging

logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Auto-initialize the state database on startup (idempotent)."""
    try:
        from ..config.loader import load_config
        from ..state.db import Database
        config = load_config()
        db_path = config.get_state_db_path()
        db = Database(db_path)
        schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state", "schema.sql")
        try:
            db.init_db(schema_path)
            logger.info("State database ready.")
        finally:
            db.close()
    except Exception:
        logger.exception("Could not auto-initialize state database")
    yield


def create_app():
    app = FastAPI(title="Ragnificent", version="0.1.0", lifespan=lifespan)

    # CORS — allow all origins on the local network
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount Static
    static_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gui", "static")
    app.mount("/static", StaticFiles(directory=static_path), name="static")

    app.include_router(health.router)
    app.include_router(query.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(corpora.router, prefix="/api")
    app.include_router(gui_routes.router)

    @app.get("/")
    def root():
        # Redirect to dashboard for better UX
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/gui/dashboard")
    
    return app

app = create_app()
