from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path

from app.api.routes import query
from app.api.query_engine import QueryEngine
from app.config.schema import GlobalConfig


class _Engine:
    def __init__(self):
        self.calls = []

    def query(self, query_text, corpus_id=None, top_k=5, llm_model=None):
        self.calls.append((query_text, corpus_id, top_k, llm_model))
        return {"query": query_text, "hits": [], "answer": "ok", "time": 0.01}


def test_http_query_model_override_is_opt_in_but_normal_queries_remain_available(monkeypatch):
    app = FastAPI()
    app.include_router(query.router, prefix="/api")
    engine = _Engine()
    app.dependency_overrides[query.get_query_engine] = lambda: engine
    monkeypatch.delenv("RAGNIFICENT_ALLOWED_QUERY_MODEL_OVERRIDES", raising=False)

    with TestClient(app) as client:
        normal = client.post("/api/query", json={"query": "normal retrieval"})
        blocked = client.post(
            "/api/query",
            json={"query": "override", "llm_model": "unknown-cloud-model"},
        )

    assert normal.status_code == 200
    assert blocked.status_code == 400
    assert engine.calls == [("normal retrieval", None, 5, None)]


class _DocumentationHit:
    id = "documentation-chunk"
    score = 0.93
    payload = {
        "corpus_id": "voltron-repository-docs",
        "file_name": "README.md",
        "chunk_index": 2,
        "text": "Agent Harness owns the Trombone runtime.",
        "source": "ragnificent://source-receipts/receipt-123",
        "source_receipt_id": "receipt-123",
        "source_receipt_locator": "ragnificent://source-receipts/receipt-123",
        "citation_repository": "SweetingTech/Agent_Harness_Template",
        "citation_path": "README.md",
        "citation_git_commit": "b" * 40,
        "citation_content_sha256": "c" * 64,
    }


class _DocumentationVectorService:
    def search(self, corpus_id, vector, limit=5):
        assert corpus_id == "voltron-repository-docs"
        return [_DocumentationHit()]


class _Embedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


def _query_config(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(
        library_root=str(tmp_path / "library"),
        ingest={"lock_file": str(tmp_path / "ingest.lock"), "ocr_trigger": {"min_text_chars": 10}},
        extraction={"pdf_backend": "pymupdf", "normalize": {"whitespace": True}},
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
            "embeddings": {"provider": "ollama", "model": "nomic-embed-text"},
            "answer": {"provider": "ollama", "model": "llama3"},
        },
        vector_db={"backend": "qdrant", "url": "http://localhost:6333", "collection_prefix": "test"},
        state_db={"path": str(tmp_path / "state" / "ingest.sqlite")},
    )


def test_repository_docs_query_returns_pinned_provenance_citations(tmp_path):
    engine = QueryEngine(
        vector_service=_DocumentationVectorService(),
        embedder=_Embedder(),
        default_llm=None,
        config=_query_config(tmp_path),
    )

    result = engine.query("What owns Trombone?", corpus_id="voltron-repository-docs")

    assert result["citations"] == [
        {
            "repository": "SweetingTech/Agent_Harness_Template",
            "path": "README.md",
            "git_commit": "b" * 40,
            "content_sha256": "c" * 64,
            "source_receipt_id": "receipt-123",
            "canonical_locator": "ragnificent://source-receipts/receipt-123",
        }
    ]


def test_query_route_preserves_repository_documentation_citations():
    class CitationEngine:
        def query(self, query_text, corpus_id=None, top_k=5, llm_model=None):
            return {
                "query": query_text,
                "answer": "Grounded answer",
                "hits": [],
                "citations": [{"repository": "SweetingTech/Agent_Harness_Template", "path": "README.md"}],
                "time": 0.01,
            }

    app = FastAPI()
    app.include_router(query.router, prefix="/api")
    app.dependency_overrides[query.get_query_engine] = CitationEngine
    with TestClient(app) as client:
        response = client.post("/api/query", json={"query": "What owns Trombone?"})

    assert response.status_code == 200
    assert response.json()["citations"] == [
        {"repository": "SweetingTech/Agent_Harness_Template", "path": "README.md"}
    ]
