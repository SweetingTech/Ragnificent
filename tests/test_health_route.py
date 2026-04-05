from fastapi.testclient import TestClient

from app.api.server import create_app


def test_health_reports_hosted_embedding_provider_without_ollama_probe(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.ingest.get_config",
        lambda: type(
            "Cfg",
            (),
            {
                "vector_db": type("VectorDb", (), {"url": "http://localhost:6333"})(),
                "models": type(
                    "Models",
                    (),
                    {
                        "embeddings": type(
                            "Embeddings",
                            (),
                            {
                                "provider": "openrouter",
                                "base_url": "https://openrouter.ai/api/v1",
                            },
                        )(),
                        "answer": type(
                            "Answer",
                            (),
                            {
                                "provider": "openai",
                                "base_url": "https://api.openai.com/v1",
                            },
                        )(),
                    },
                )(),
            },
        )(),
    )
    monkeypatch.setattr(
        "app.api.routes.health._probe_qdrant",
        lambda url: {"status": "ok", "url": url},
    )
    monkeypatch.setattr(
        "app.api.routes.health._probe_openai_compatible",
        lambda provider, base_url: {
            "status": "ok",
            "provider": provider,
            "url": base_url,
        },
    )
    monkeypatch.setattr(
        "app.api.routes.health._probe_anthropic",
        lambda base_url: {"status": "ok", "provider": "anthropic", "url": base_url},
    )

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["dependencies"]["embeddings"]["provider"] == "openrouter"
    assert body["dependencies"]["embeddings"]["url"] == "https://openrouter.ai/api/v1"
    assert body["dependencies"]["answer"]["provider"] == "openai"
