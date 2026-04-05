from pathlib import Path

import yaml

from app.api.query_engine import QueryEngine
from app.config.schema import GlobalConfig


class DummyVectorService:
    def search(self, corpus_id, vector, limit=5):
        return []


class FailingDefaultEmbedder:
    def embed(self, texts):
        raise AssertionError("default embedder should not be used for corpus-specific embedding config")


class RecordingEmbedder:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [[0.1, 0.2, 0.3]]


def make_config(tmp_path) -> GlobalConfig:
    library_root = tmp_path / "library"
    (library_root / "corpora" / "ebooks").mkdir(parents=True)

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


def test_query_uses_corpus_specific_embedding_provider(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    corpus_config_path = Path(config.library_root) / "corpora" / "ebooks" / "corpus.yaml"
    corpus_config_path.write_text(
        yaml.safe_dump(
            {
                "corpus_id": "ebooks",
                "models": {
                    "embeddings": {
                        "provider": "openai",
                        "model": "text-embedding-3-large",
                        "base_url": "https://api.openai.com/v1",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    recording_embedder = RecordingEmbedder()
    requested = {}

    def fake_get_embedding_provider(name, base_url=None, model="nomic-embed-text", api_key=None):
        requested.update(
            {"name": name, "base_url": base_url, "model": model, "api_key": api_key}
        )
        return recording_embedder

    monkeypatch.setattr("app.api.query_engine.get_embedding_provider", fake_get_embedding_provider)

    engine = QueryEngine(
        vector_service=DummyVectorService(),
        embedder=FailingDefaultEmbedder(),
        default_llm=None,
        config=config,
    )

    result = engine.query("find the citation", corpus_id="ebooks")

    assert requested == {
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "text-embedding-3-large",
        "api_key": None,
    }
    assert recording_embedder.calls == [["find the citation"]]
    assert result["hits"] == []
