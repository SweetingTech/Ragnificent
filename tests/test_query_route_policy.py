from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import query


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
