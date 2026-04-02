from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from fastapi.staticfiles import StaticFiles
from .routes import health, query, ingest, corpora
from ..gui import routes as gui_routes

def create_app():
    # Load config on startup
    # config = load_config() # can be injected or loaded here

    app = FastAPI(title="Ragnificent", version="0.1.0")

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
