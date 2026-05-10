import pytest

from app.api.routes.agenda import (
    AgendaEvidenceRequest,
    _corpus_inventory,
    _effective_corpora,
    _query_allowed_corpora,
)


class FakeCorpusService:
    def get_all_corpora(self):
        return [
            {"corpus_id": "safe", "description": "Allowed corpus"},
            {"corpus_id": "restricted", "description": "Restricted corpus"},
        ]


class FakeVectorService:
    def get_count(self, corpus_id):
        if corpus_id == "restricted":
            raise RuntimeError("password=secret host=internal")
        return 3


class FakeEngine:
    def __init__(self):
        self.queries = []

    def query(self, query, corpus_id=None, top_k=5, llm_model=None):
        self.queries.append((query, corpus_id, top_k, llm_model))
        return {
            "query": query,
            "hits": [
                {
                    "id": f"{corpus_id}-hit",
                    "score": 0.9 if corpus_id == "safe" else 0.1,
                    "payload": {
                        "corpus_id": corpus_id,
                        "file_name": f"{corpus_id}.md",
                        "text": f"{corpus_id} text",
                    },
                }
            ],
            "answer": f"{corpus_id} answer",
            "time": 0.01,
        }


def test_specific_corpus_intersects_with_caller_allowlist():
    corpora = [
        {"corpus_id": "safe"},
        {"corpus_id": "restricted"},
    ]
    request = AgendaEvidenceRequest(
        corpus_id="restricted",
        allowed_corpora=["safe"],
        denied_corpora=[],
    )

    policy = _effective_corpora(corpora, request)

    assert policy["effective"] == []
    assert policy["queryAllowed"] is False


@pytest.mark.asyncio
async def test_all_corpus_query_uses_only_effective_corpora():
    engine = FakeEngine()

    result = await _query_allowed_corpora(engine, "find policy", ["safe"], 5)

    assert engine.queries == [("find policy", "safe", 5, None)]
    assert [hit["payload"]["corpus_id"] for hit in result["hits"]] == ["safe"]


def test_corpus_inventory_sanitizes_vector_count_errors():
    corpora = _corpus_inventory(FakeCorpusService(), FakeVectorService())
    restricted = next(corpus for corpus in corpora if corpus["corpus_id"] == "restricted")

    assert restricted["vector_count"] == 0
    assert restricted["vector_error"] == "vector_count_unavailable"
    assert "secret" not in str(restricted)
