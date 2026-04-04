from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qdrant_client.http.exceptions import ResponseHandlingException

from app.api.routes import ingest
from app.api.server import create_app
from app.config.schema import GlobalConfig


class FailingPipeline:
    def __init__(self, error: Exception, url: str = "http://localhost:6333"):
        self.error = error
        self.config = SimpleNamespace(vector_db=SimpleNamespace(url=url))

    def run_once(self, corpus_id=None):
        raise self.error


def make_config(tmp_path) -> GlobalConfig:
    library_root = tmp_path / "library"
    library_root.mkdir()

    return GlobalConfig(
        library_root=str(library_root),
        ingest={
            "lock_file": str(tmp_path / "ingest.lock"),
            "ocr_trigger": {"min_text_chars": 10.0},
        },
        extraction={
            "pdf_backend": "pymupdf",
            "normalize": {"whitespace": True},
        },
        ocr={
            "backend": "tesseract",
            "ocrmypdf": {
                "language": "eng",
                "deskew": True,
                "rotate_pages": True,
                "clean": False,
                "cache_dir": str(tmp_path / "ocr-cache"),
            },
        },
        models={
            "embeddings": {
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model": "nomic-embed-text",
            }
        },
        vector_db={
            "backend": "qdrant",
            "url": "http://localhost:6333",
            "collection_prefix": "rag",
        },
        state_db={"path": str(tmp_path / "state" / "ingest.sqlite")},
    )


def test_run_ingest_returns_503_when_qdrant_is_unreachable():
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[ingest.get_pipeline] = lambda: FailingPipeline(
        ResponseHandlingException(httpx.ConnectError("connection refused"))
    )

    with TestClient(app) as client:
        response = client.post("/api/ingest/run?corpus_id=my_docs")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "Cannot reach Qdrant at http://localhost:6333. Is it running?",
    }


def test_startup_logs_warning_when_qdrant_is_unreachable(tmp_path, monkeypatch, caplog):
    config = make_config(tmp_path)

    monkeypatch.setattr(
        "app.config.loader.load_config", lambda config_path="config.yaml": config
    )
    monkeypatch.setattr(
        "app.vector.qdrant_client.QdrantClient.get_collections",
        lambda self: (_ for _ in ()).throw(
            ResponseHandlingException(httpx.ConnectError("connection refused"))
        ),
    )

    with caplog.at_level("WARNING"):
        with TestClient(create_app()) as client:
            response = client.get("/health")

    assert response.status_code == 200
    assert "Cannot reach Qdrant at http://localhost:6333. Is it running?" in caplog.text
