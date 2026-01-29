from qdrant_client import QdrantClient
from qdrant_client.http import models
from typing import List, Dict, Optional
import os
from ..utils.logging import setup_logging

logger = setup_logging()

class VectorService:
    def __init__(self, url: str, collection_prefix: str):
        self.client = QdrantClient(url=url)
        self.prefix = collection_prefix

    def _get_collection_name(self, corpus_id: str) -> str:
        return f"{self.prefix}_{corpus_id}"

    def ensure_collection(self, corpus_id: str, vector_size: int = 768):
        collection_name = self._get_collection_name(corpus_id)
        collections = self.client.get_collections().collections
        exists = any(c.name == collection_name for c in collections)
        
        if not exists:
            logger.info(f"Creating collection {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
            )

    def upsert_chunks(self, corpus_id: str, chunks: List[Dict]):
        """
        chunks: List of specific structure, expecting dicts with 'id', 'vector', 'payload'
        """
        collection_name = self._get_collection_name(corpus_id)
        points = [
            models.PointStruct(
                id=c['id'], 
                vector=c['vector'], 
                payload=c['payload']
            ) for c in chunks
        ]
        
        self.client.upsert(
            collection_name=collection_name,
            points=points
        )
        logger.info(f"Upserted {len(points)} chunks to {collection_name}")

    def delete_by_file_hash(self, corpus_id: str, file_hash: str):
        collection_name = self._get_collection_name(corpus_id)
        self.client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="file_hash",
                            match=models.MatchValue(value=file_hash)
                        )
                    ]
                )
            )
        )
        logger.info(f"Deleted chunks for file {file_hash} in {collection_name}")

    def get_count(self, corpus_id: str) -> int:
        collection_name = self._get_collection_name(corpus_id)
        try:
            info = self.client.get_collection(collection_name)
            return info.points_count
        except Exception:
            return 0
