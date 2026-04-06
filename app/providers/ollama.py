"""
Ollama provider implementations for embeddings and LLM.
Uses the Ollama Python client with explicit host configuration (no global env vars).
"""
from typing import List, Optional
import re
from ollama import Client
from .base import EmbeddingProvider, LLMProvider
from ..utils.logging import setup_logging

logger = setup_logging()

OLLAMA_EMBED_BATCH_SIZE = 32
_REPEATED_PUNCTUATION_RUN_RE = re.compile(r"([.\-_*=#~•·])\1{5,}\d*")
_LONG_TOKEN_RE = re.compile(r"\S{65,}")


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

    def _normalize_embeddings_response(self, resp) -> List[List[float]]:
        """Handle both current and legacy Ollama client response shapes."""
        if hasattr(resp, "embeddings"):
            return resp.embeddings
        if hasattr(resp, "embedding"):
            return [resp.embedding]
        if isinstance(resp, dict):
            if "embeddings" in resp:
                return resp["embeddings"]
            if "embedding" in resp:
                return [resp["embedding"]]
        raise RuntimeError("Unexpected Ollama embeddings response format.")

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        if hasattr(self._client, "embed"):
            resp = self._client.embed(model=self.model, input=texts)
            return self._normalize_embeddings_response(resp)

        if hasattr(self._client, "embeddings"):
            batched: List[List[float]] = []
            for text in texts:
                resp = self._client.embeddings(model=self.model, prompt=text)
                batched.extend(self._normalize_embeddings_response(resp))
            return batched

        raise RuntimeError("Ollama client does not expose embed or embeddings APIs.")

    def _normalize_long_token(self, token: str) -> str:
        """
        Break up pathological tokens produced by PDF extraction.

        Table-of-contents leaders and other dense punctuation runs can trigger
        Ollama context-length errors even when the overall chunk is small.
        """
        collapsed = _REPEATED_PUNCTUATION_RUN_RE.sub(" ", token).strip()
        if not collapsed:
            return ""

        if len(collapsed) <= 64:
            return collapsed

        # Preserve content while making it tokenizable by splitting long runs.
        return " ".join(
            collapsed[i:i + 48]
            for i in range(0, len(collapsed), 48)
        )

    def _sanitize_text(self, text: str) -> str:
        flattened = text.replace("\n", " ")
        flattened = _REPEATED_PUNCTUATION_RUN_RE.sub(" ", flattened)
        flattened = _LONG_TOKEN_RE.sub(
            lambda match: self._normalize_long_token(match.group(0)),
            flattened,
        )
        return " ".join(flattened.split())

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (list of floats)
        """
        if not texts:
            return []

        clean_texts = [self._sanitize_text(text) for text in texts]

        try:
            return self._embed_batch(clean_texts)
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            if len(clean_texts) == 1:
                raise

        recovered: List[List[float]] = []
        for start in range(0, len(clean_texts), OLLAMA_EMBED_BATCH_SIZE):
            batch = clean_texts[start:start + OLLAMA_EMBED_BATCH_SIZE]
            try:
                recovered.extend(self._embed_batch(batch))
                continue
            except Exception as batch_error:
                logger.warning(
                    "Ollama batch of %s texts failed; falling back to single-item embeds: %s",
                    len(batch),
                    batch_error,
                )

            for text in batch:
                recovered.extend(self.embed([text]))

        return recovered


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
