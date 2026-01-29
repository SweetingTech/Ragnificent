from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from pathlib import Path
import os
import yaml

# Adjust path to templates
# We are in app/gui/routes.py, templates are in app/gui/templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(prefix="/gui", tags=["gui"])

def get_corpora():
    # Helper to scan rag_library/corpora
    # This should effectively be in the 'Inventory' service logic, but putting here for v1 speed
    # We should use the config path logic ideally.
    base_path = Path("rag_library/corpora") # TODO: use config.library_root
    corpora = []
    if base_path.exists():
        for d in base_path.iterdir():
            if d.is_dir() and (d / "corpus.yaml").exists():
                # Load metadata
                try:
                    with open(d / "corpus.yaml") as f:
                        meta = yaml.safe_load(f)
                    corpora.append({
                        "corpus_id": meta.get("corpus_id", d.name),
                        "description": meta.get("description", ""),
                        "inbox_path": str((d / "inbox").resolve())
                    })
                except Exception:
                    pass
    return corpora

from app.state.stats import StatsService
from app.config.loader import load_config
from app.vector.qdrant_client import VectorService

# Load globals once (or dependency inject)
config = load_config()
state_db_path = config.ingest.lock_file.replace(".locks/ingest.lock", "state/ingest.sqlite") # Hacky fallback if not in global
if os.getenv("STATE_DB_PATH"):
    state_db_path = os.getenv("STATE_DB_PATH")

stats_service = StatsService(state_db_path)
vector_service = VectorService(config.vector_db.url, config.vector_db.collection_prefix)

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = stats_service.get_stats()
    
    # Get total vectors across all corpora
    corpora = get_corpora()
    total_vectors = 0
    for c in corpora:
        total_vectors += vector_service.get_count(c['corpus_id'])

    context = {
        "request": request,
        "active_page": "dashboard",
        "total_files": stats["total"],
        "success_count": stats["success"],
        "failed_count": stats["failed"],
        "total_vectors": total_vectors,
        "vector_backend": config.vector_db.backend,
        "corpora": corpora
    }
    return templates.TemplateResponse("dashboard.html", context)

@router.get("/corpora", response_class=HTMLResponse)
async def corpora_list(request: Request):
    # Reuse dashboard logic or simpler list
    context = {
        "request": request,
        "active_page": "corpora",
        "corpora": get_corpora()
    }
    return templates.TemplateResponse("corpora.html", context)

from app.providers.ollama import OllamaLLM

@router.get("/search", response_class=HTMLResponse)
async def search_ui(request: Request):
    # Fetch available models on the backend (Ollama)
    # We use the base_url from config
    available_models = OllamaLLM.list_models(base_url=config.models.embeddings.base_url)
    if not available_models:
        available_models = ["llama3", "mistral"] # Fallback if fetch fails
        
    context = {
        "request": request,
        "active_page": "search",
        "corpora": get_corpora(),
        "available_models": available_models
    }
    return templates.TemplateResponse("search.html", context)
@router.get("/corpora/new", response_class=HTMLResponse)
async def new_corpus_ui(request: Request):
    return templates.TemplateResponse("create_corpus.html", {"request": request, "active_page": "corpora"})

@router.post("/corpora/create")
async def create_corpus(
    request: Request,
    corpus_id: str = Form(...),
    description: str = Form(...),
    source_path: str = Form(...),
    llm_model: str = Form("llama3")
):
    # Validate ID
    if not corpus_id.replace("_", "").isalnum():
        return HTMLResponse("Invalid ID", status_code=400)
    
    # Create directory structure
    base_path = Path("rag_library/corpora") / corpus_id
    inbox_path = base_path / "inbox"
    
    # In V2, we might not use internal inbox if we track external path directly.
    # But for consistency, we create the structure.
    os.makedirs(inbox_path, exist_ok=True)
    
    # Create corpus.yaml
    config_content = {
        "corpus_id": corpus_id,
        "description": description,
        "source_path": source_path, # External path to watch
        "retain_on_missing": True,
        "models": {
            "answer": {
                "provider": "ollama",
                "model": llm_model
            }
        },
        "chunking": {
            "default": {
                "strategy": "pdf_sections",
                "max_tokens": 700,
                "overlap_tokens": 80
            }
        }
    }
    
    with open(base_path / "corpus.yaml", "w") as f:
        yaml.dump(config_content, f)
        
    # Spin up vector DB (Create Collection)
    vector_service.ensure_collection(corpus_id)
    
    # Redirect to Dashboard
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/gui/dashboard", status_code=303)

@router.get("/corpora/{corpus_id}", response_class=HTMLResponse)
async def manage_corpus(request: Request, corpus_id: str):
    # Locate corpus
    base_path = Path("rag_library/corpora") / corpus_id
    if not base_path.exists() or not (base_path / "corpus.yaml").exists():
        return HTMLResponse("Corpus not found", status_code=404)
        
    with open(base_path / "corpus.yaml") as f:
        meta = yaml.safe_load(f)
        
    # Get vector count
    v_count = vector_service.get_count(corpus_id)
        
    # Prepare Display Data
    corpus_data = {
        "corpus_id": meta.get("corpus_id"),
        "description": meta.get("description"),
        "source_path": meta.get("source_path") or str((base_path / "inbox").resolve()),
        "model": meta.get("models", {}).get("answer", {}).get("model", "Default")
    }
    
    context = {
        "request": request,
        "active_page": "corpora",
        "corpus": corpus_data,
        "vector_count": v_count
    }
    return templates.TemplateResponse("manage_corpus.html", context)

