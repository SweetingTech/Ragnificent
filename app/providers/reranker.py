"""
Reranker provider interface and implementations.
"""
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from ..utils.logging import setup_logging

logger = setup_logging()

class RerankProvider(ABC):
    """Base interface for reranking models."""

    @abstractmethod
    def rerank(self, query: str, documents: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Rerank a list of documents for a given query.

        Args:
            query: The search query
            documents: List of document dictionaries (from Qdrant search)
            top_n: Number of documents to return after reranking

        Returns:
            Reranked list of documents
        """
        pass

class OllamaRerankProvider(RerankProvider):
    """
    Reranker using Ollama (if a reranking model is available via Ollama chat/embedding endpoints,
    though typically rerankers like Cohere are used via API or local sentence-transformers).
    For Ollama, one might use a prompt-based approach or a specific reranking model if loaded.
    Here we provide a stub for a generic API or prompt-based reranking.
    """
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url
        self.model = model
        from ollama import Client
        self._client = Client(host=base_url)

    def rerank(self, query: str, documents: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Placeholder for a prompt-based reranking using an LLM.
        This is typically slow and true rerankers (like Cohere or BGE-Reranker) are preferred.
        """
        logger.warning("OllamaRerankProvider is a stub using prompt-based LLM ranking. It is slow.")
        # Very naive pass-through for now, as real local reranking is better done with sentence-transformers.
        return documents[:top_n]


def get_rerank_provider(name: str, **kwargs) -> Optional[RerankProvider]:
    """Factory for rerank providers."""
    if name == "ollama":
        return OllamaRerankProvider(**kwargs)
    return None
