from pathlib import Path

import pytest
import yaml

from app.api.query_engine import QueryEngine
from app.config.schema import AnswerModelConfig, GlobalConfig
from app.policy import PolicyViolation
from app.services.corpus_service import CorpusService, CorpusValidationError


class _VectorService:
    def search(self, corpus_id, vector, limit=5):
        return []


class _Embedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3]]


def _config(tmp_path: Path) -> GlobalConfig:
    library_root = tmp_path / "library"
    (library_root / "corpora" / "private").mkdir(parents=True)
    return GlobalConfig(
        library_root=str(library_root),
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
            "embeddings": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "nomic-embed-text"},
            "answer": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "llama3"},
        },
        vector_db={"backend": "qdrant", "url": "http://localhost:6333", "collection_prefix": "test"},
        state_db={"path": str(tmp_path / "state" / "ingest.sqlite")},
    )


def test_local_only_corpus_creation_rejects_cloud_embedding_or_answer_routes(tmp_path):
    service = CorpusService(str(tmp_path / "library"))

    with pytest.raises(CorpusValidationError, match="forbids cloud answer provider"):
        service.create_corpus(
            corpus_id="private-answer",
            description="private",
            source_path=str(tmp_path),
            llm_provider="openai",
            embedding_provider="ollama",
            embedding_model="nomic-embed-text",
            privacy="local_only",
        )

    with pytest.raises(CorpusValidationError, match="forbids cloud embedding provider"):
        service.create_corpus(
            corpus_id="private-embedding",
            description="private",
            source_path=str(tmp_path),
            llm_provider="ollama",
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            privacy="local_only",
        )


def test_query_engine_rejects_cloud_answer_route_for_legacy_local_only_corpus(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.models.answer = AnswerModelConfig(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-5.4",
    )
    corpus_config_path = Path(config.library_root) / "corpora" / "private" / "corpus.yaml"
    corpus_config_path.write_text(
        yaml.safe_dump(
            {
                "corpus_id": "private",
                "privacy": "local_only",
                "models": {
                    "embeddings": {"provider": "ollama", "model": "nomic-embed-text"},
                    "answer": {"provider": "openai", "model": "gpt-5.4"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.api.query_engine.get_llm_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cloud answer provider must not be created")),
    )
    engine = QueryEngine(
        vector_service=_VectorService(),
        embedder=_Embedder(),
        default_llm=None,
        config=config,
    )

    result = engine.query("private evidence", corpus_id="private")
    assert result["hits"] == []
    assert "local_only corpus policy forbids cloud answer provider" in result["answer"]

    with pytest.raises(PolicyViolation, match="forbids cloud answer provider"):
        engine._resolve_llm("private")
