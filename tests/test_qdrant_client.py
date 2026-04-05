from types import SimpleNamespace

from app.vector.qdrant_client import VectorService


class QueryPointsOnlyClient:
    def __init__(self):
        self.calls = []

    def get_collection(self, collection_name):
        return object()

    def query_points(self, collection_name, query, limit):
        self.calls.append(
            {
                "collection_name": collection_name,
                "query": query,
                "limit": limit,
            }
        )
        return SimpleNamespace(points=["hit-1", "hit-2"])


def test_search_uses_query_points_when_search_api_is_unavailable():
    service = VectorService("http://localhost:6333", "instance01")
    service.client = QueryPointsOnlyClient()

    hits = service.search("smut", [0.1, 0.2, 0.3], limit=2)

    assert hits == ["hit-1", "hit-2"]
    assert service.client.calls == [
        {
            "collection_name": "instance01_smut",
            "query": [0.1, 0.2, 0.3],
            "limit": 2,
        }
    ]
