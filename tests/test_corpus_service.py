from pathlib import Path

import yaml

from app.services.corpus_service import CorpusService


def test_create_corpus_persists_embedding_and_chunk_settings(tmp_path):
    service = CorpusService(str(tmp_path / "library"))

    corpus_path = service.create_corpus(
        corpus_id="ebooks",
        description="Books",
        source_path="D:/Books",
        llm_provider="openai",
        llm_model="gpt-5.4-mini",
        embedding_provider="openrouter",
        embedding_model="qwen/qwen3-embedding-8b",
        embedding_base_url="https://openrouter.ai/api/v1",
        embedding_preset="epub_general",
        chunk_strategy="heading_then_paragraph",
        chunk_max_tokens=700,
        chunk_overlap_tokens=120,
    )

    config = yaml.safe_load((corpus_path / "corpus.yaml").read_text(encoding="utf-8"))

    assert config["embedding_preset"] == "epub_general"
    assert config["models"]["embeddings"] == {
        "provider": "openrouter",
        "model": "qwen/qwen3-embedding-8b",
        "base_url": "https://openrouter.ai/api/v1",
    }
    assert config["chunking"]["default"] == {
        "strategy": "heading_then_paragraph",
        "max_tokens": 700,
        "overlap_tokens": 120,
    }
