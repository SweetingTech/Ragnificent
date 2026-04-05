from app.providers.openai_provider import OpenAIEmbeddingProvider, EMBED_BATCH_SIZE


class DummyResponse:
    def __init__(self, count):
        self._count = count

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": [
                {"index": i, "embedding": [float(i)]}
                for i in range(self._count)
            ]
        }


class DummyClient:
    def __init__(self, recorder):
        self.recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json, headers):
        self.recorder.append({"url": url, "size": len(json["input"])})
        return DummyResponse(len(json["input"]))


def test_embedding_requests_are_batched(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.providers.openai_provider.httpx.Client",
        lambda timeout: DummyClient(calls),
    )

    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="test-key",
        base_url="https://api.openai.com/v1",
    )
    texts = [f"chunk {i}" for i in range(EMBED_BATCH_SIZE + 5)]

    embeddings = provider.embed(texts)

    assert len(embeddings) == len(texts)
    assert calls == [
        {"url": "https://api.openai.com/v1/embeddings", "size": EMBED_BATCH_SIZE},
        {"url": "https://api.openai.com/v1/embeddings", "size": 5},
    ]
