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

    def run_once(
        self,
        corpus_id=None,
        source_path=None,
        retry_failed_only=False,
        progress_callback=None,
    ):
        raise self.error


class SuccessfulPipeline:
    def __init__(self):
        self.config = SimpleNamespace(vector_db=SimpleNamespace(url="http://localhost:6333"))
        self.calls = []

    def run_once(
        self,
        corpus_id=None,
        source_path=None,
        retry_failed_only=False,
        progress_callback=None,
    ):
        self.calls.append(
            {
                "corpus_id": corpus_id,
                "source_path": source_path,
                "retry_failed_only": retry_failed_only,
            }
        )
        if progress_callback:
            progress_callback({
                "status": "running",
                "total_files": 5,
                "files_completed": 3,
                "files_processed": 2,
                "files_skipped": 1,
                "files_failed": 0,
                "percent_complete": 60.0,
                "current_corpus": corpus_id,
                "current_file": "demo.epub",
                "message": "Completed 3 of 5",
            })
        return {
            "corpora_processed": 1,
            "total_files": 5,
            "files_completed": 5,
            "files_processed": 4,
            "files_skipped": 1,
            "files_failed": 0,
        }


def raise_error(error: Exception):
    raise error


def make_config(tmp_path) -> GlobalConfig:
    library_root = tmp_path / "library"
    library_root.mkdir()

    return GlobalConfig(
        library_root=str(library_root),
        ingest={
            "lock_file": str(tmp_path / "ingest.lock"),
            "ocr_trigger": {"min_text_chars": 10},
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
        lambda self: raise_error(
            ResponseHandlingException(httpx.ConnectError("connection refused"))
        ),
    )

    with caplog.at_level("WARNING"):
        with TestClient(create_app()) as client:
            response = client.get("/health")

    assert response.status_code == 503
    assert "Cannot reach Qdrant at http://localhost:6333. Is it running?" in caplog.text


def test_ingest_status_reports_last_job_summary():
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    pipeline = SuccessfulPipeline()
    app.dependency_overrides[ingest.get_pipeline] = lambda: pipeline

    with TestClient(app) as client:
        response = client.post("/api/ingest/run?corpus_id=my_docs")
        assert response.status_code == 200

        status = client.get("/api/ingest/status")

    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "success"
    assert body["summary"]["total_files"] == 5
    assert body["summary"]["files_processed"] == 4
    assert body["percent_complete"] == 100.0


def test_retry_failed_mode_is_forwarded_to_pipeline():
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    pipeline = SuccessfulPipeline()
    app.dependency_overrides[ingest.get_pipeline] = lambda: pipeline

    with TestClient(app) as client:
        response = client.post("/api/ingest/run?corpus_id=my_docs&retry_failed_only=true")

    assert response.status_code == 200
    assert pipeline.calls == [
        {
            "corpus_id": "my_docs",
            "source_path": None,
            "retry_failed_only": True,
        }
    ]
