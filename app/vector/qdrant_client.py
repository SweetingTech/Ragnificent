"""
Qdrant vector database service for storing and searching document embeddings.
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse
from typing import List, Dict, Optional
from ..utils.logging import setup_logging

logger = setup_logging()

# Constants
DEFAULT_VECTOR_SIZE = 768


class VectorService:
    """Service for managing vector storage in Qdrant."""

    def __init__(self, url: str, collection_prefix: str):
        """
        Initialize the vector service.

        Args:
            url: URL of the Qdrant server
            collection_prefix: Prefix for collection names
        """
        self.client = QdrantClient(url=url)
        self.prefix = collection_prefix
        self._collection_cache: Dict[str, bool] = {}

    def _get_collection_name(self, corpus_id: str) -> str:
        """
        Get the full collection name for a corpus.

        Args:
            corpus_id: The corpus identifier

        Returns:
            Full collection name with prefix
        """
        return f"{self.prefix}_{corpus_id}"

    def collection_exists(self, corpus_id: str) -> bool:
        """
        Check if a collection exists for the given corpus.

        Uses direct lookup instead of listing all collections for O(1) performance.

        Args:
            corpus_id: The corpus identifier

        Returns:
            True if the collection exists
        """
        collection_name = self._get_collection_name(corpus_id)

        # Check cache first
        if collection_name in self._collection_cache:
            return self._collection_cache[collection_name]

        try:
            # Use direct lookup instead of listing all collections (O(1) vs O(n))
            self.client.get_collection(collection_name=collection_name)
            exists = True
        except UnexpectedResponse as e:
            # Treat 404/not-found as "collection does not exist"
            if hasattr(e, 'status_code') and e.status_code == 404:
                exists = False
            else:
                logger.error(f"Failed to check collection existence for {collection_name}: {e}")
                return False
        except Exception as e:
            logger.error(f"Failed to check collection existence for {collection_name}: {e}")
            return False

        self._collection_cache[collection_name] = exists
        return exists

    def ensure_collection(self, corpus_id: str, vector_size: int = DEFAULT_VECTOR_SIZE) -> None:
        """
        Ensure a collection exists, creating it if necessary.

        Args:
            corpus_id: The corpus identifier
            vector_size: Dimension of the vectors to store
        """
        collection_name = self._get_collection_name(corpus_id)

        if self.collection_exists(corpus_id):
            logger.debug(f"Collection {collection_name} already exists")
            return

        try:
            logger.info(f"Creating collection {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE
                )
            )
            # Update cache
            self._collection_cache[collection_name] = True
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
            raise

    def upsert_chunks(self, corpus_id: str, chunks: List[Dict]) -> None:
        """
        Upsert document chunks to the vector database.

        Args:
            corpus_id: The corpus identifier
            chunks: List of chunk dictionaries with 'id', 'vector', 'payload' keys
        """
        if not chunks:
            logger.warning(f"No chunks to upsert for corpus {corpus_id}")
            return

        collection_name = self._get_collection_name(corpus_id)

        # Ensure collection exists before upserting
        self.ensure_collection(corpus_id)

        points = [
            models.PointStruct(
                id=c['id'],
                vector=c['vector'],
                payload=c['payload']
            ) for c in chunks
        ]

        try:
            self.client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.info(f"Upserted {len(points)} chunks to {collection_name}")
        except Exception as e:
            logger.error(f"Failed to upsert chunks to {collection_name}: {e}")
            raise

    def delete_by_file_hash(self, corpus_id: str, file_hash: str) -> None:
        """
        Delete all chunks associated with a file hash.

        Args:
            corpus_id: The corpus identifier
            file_hash: Hash of the file whose chunks should be deleted
        """
        collection_name = self._get_collection_name(corpus_id)

        if not self.collection_exists(corpus_id):
            logger.warning(f"Collection {collection_name} does not exist, nothing to delete")
            return

        try:
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
        except Exception as e:
            logger.error(f"Failed to delete chunks for {file_hash} in {collection_name}: {e}")
            raise

    def search(self, corpus_id: str, vector: List[float], limit: int = 5) -> List:
        """
        Search for similar vectors in the collection.

        Args:
            corpus_id: The corpus identifier
            vector: Query vector
            limit: Maximum number of results to return

        Returns:
            List of search results (empty if collection doesn't exist)
        """
        collection_name = self._get_collection_name(corpus_id)

        # Check if collection exists before searching
        if not self.collection_exists(corpus_id):
            logger.warning(f"Collection {collection_name} does not exist, returning empty results")
            return []

        try:
            return self.client.search(
                collection_name=collection_name,
                query_vector=vector,
                limit=limit
            )
        except UnexpectedResponse as e:
            logger.error(f"Qdrant search failed for {collection_name}: {e}")
            return []
        except Exception as e:
            logger.error(f"Search failed for {collection_name}: {e}")
            return []

    def get_count(self, corpus_id: str) -> int:
        """
        Get the number of vectors in a collection.

        Args:
            corpus_id: The corpus identifier

        Returns:
            Number of vectors, or 0 if collection doesn't exist
        """
        collection_name = self._get_collection_name(corpus_id)

        if not self.collection_exists(corpus_id):
            return 0

        try:
            info = self.client.get_collection(collection_name)
            return info.points_count
        except Exception as e:
            logger.warning(f"Failed to get count for {collection_name}: {e}")
            return 0

    def invalidate_cache(self, corpus_id: Optional[str] = None) -> None:
        """
        Invalidate the collection cache.

        Args:
            corpus_id: If provided, only invalidate cache for this corpus.
                      If None, invalidate entire cache.
        """
        if corpus_id:
            collection_name = self._get_collection_name(corpus_id)
            self._collection_cache.pop(collection_name, None)
        else:
            self._collection_cache.clear()
