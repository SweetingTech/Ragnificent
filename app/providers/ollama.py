"""
Ollama provider implementations for embeddings and LLM.
Uses the Ollama Python client with explicit host configuration (no global env vars).
"""
from typing import List, Optional
from ollama import Client
from .base import EmbeddingProvider, LLMProvider
from ..utils.logging import setup_logging

logger = setup_logging()


class OllamaProvider(EmbeddingProvider):
    """Embedding provider using Ollama's embedding models."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        """
        Initialize the Ollama embedding provider.

        Args:
            base_url: URL of the Ollama server
            model: Name of the embedding model to use
        """
        self.base_url = base_url
        self.model = model
        # Use explicit Client instead of global env var
        self._client = Client(host=base_url)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (list of floats)
        """
        results = []
        for text in texts:
            # Clean newlines to avoid issues with some models
            clean_text = text.replace("\n", " ")
            try:
                resp = self._client.embeddings(model=self.model, prompt=clean_text)
                results.append(resp['embedding'])
            except Exception as e:
                logger.error(f"Embedding failed for text chunk: {e}")
                raise
        return results


class OllamaLLM(LLMProvider):
    """LLM provider using Ollama's chat models."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        """
        Initialize the Ollama LLM provider.

        Args:
            base_url: URL of the Ollama server
            model: Name of the LLM model to use
        """
        self.base_url = base_url
        self.model = model
        # Use explicit Client instead of global env var
        self._client = Client(host=base_url)

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generate a response using the LLM.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt for context

        Returns:
            Generated text response
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        try:
            response = self._client.chat(model=self.model, messages=messages)
            return response['message']['content']
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            raise

    @staticmethod
    def list_models(base_url: str = "http://localhost:11434") -> List[str]:
        """
        List available models from the Ollama server.

        Args:
            base_url: URL of the Ollama server

        Returns:
            List of model names available on the server
        """
        try:
            # Create a temporary client for listing models
            client = Client(host=base_url)
            models_info = client.list()
            # ollama.list() returns dict with 'models' key which is a list of dicts
            return [m['name'] for m in models_info.get('models', [])]
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []
