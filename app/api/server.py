from fastapi import FastAPI
from .routes import health
from ..config.loader import load_config
import os

def create_app():
    # Load config on startup
    # config = load_config() # can be injected or loaded here
    
    app = FastAPI(title="RAG Librarian", version="0.1.0")
    
    app.include_router(health.router)
    
    return app

app = create_app()
