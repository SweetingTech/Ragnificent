"""
OpenAI-compatible provider for embeddings and LLM.
Works with OpenAI, OpenRouter, and any other OpenAI-compatible endpoint.
"""
import os
import time
import httpx
from typing import List, Optional
from .base import EmbeddingProvider, LLMProvider
from ..utils.logging import setup_logging

logger = setup_logging()

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EMBED_BATCH_SIZE = 16
EMBED_TIMEOUT_SECONDS = 120.0
EMBED_MAX_RETRIES = 3

_ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _resolve_key(api_key: Optional[str], provider_hint: str = "openai") -> str:
    if api_key:
        return api_key
    env_var = _ENV_KEY_MAP.get(provider_hint, "OPENAI_API_KEY")
    return os.getenv(env_var, "")


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using OpenAI's embeddings API (or any compatible endpoint)."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        base_url: str = OPENAI_BASE_URL,
        provider_hint: str = "openai",
    ):
        self.model = model
        self.api_key = _resolve_key(api_key, provider_hint)
        self.base_url = base_url.rstrip("/")

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.base_url}/embeddings"
        all_embeddings: List[List[float]] = []

        try:
            with httpx.Client(timeout=EMBED_TIMEOUT_SECONDS) as client:
                for start in range(0, len(texts), EMBED_BATCH_SIZE):
                    batch = texts[start:start + EMBED_BATCH_SIZE]
                    payload = {"model": self.model, "input": batch}
                    last_error = None

                    for attempt in range(1, EMBED_MAX_RETRIES + 1):
                        try:
                            resp = client.post(endpoint, json=payload, headers=headers)
                            resp.raise_for_status()
                            data = resp.json()
                            ordered = sorted(data["data"], key=lambda x: x["index"])
                            all_embeddings.extend(e["embedding"] for e in ordered)
                            last_error = None
                            break
                        except Exception as exc:
                            last_error = exc
                            if attempt >= EMBED_MAX_RETRIES:
                                raise
                            logger.warning(
                                f"Embedding batch retry {attempt}/{EMBED_MAX_RETRIES - 1} for "
                                f"{self.model} after {len(all_embeddings)} / {len(texts)} chunks: {exc}"
                            )
                            time.sleep(min(2 * attempt, 6))

                    if last_error is not None:
                        raise last_error
            return all_embeddings
        except Exception as e:
            logger.error(
                f"OpenAI embedding failed ({self.model}) after {len(all_embeddings)} / {len(texts)} chunks: {e}"
            )
            raise


class OpenAILLM(LLMProvider):
    """LLM provider using OpenAI chat completions API (or any compatible endpoint)."""

    def __init__(
        self,
        model: str = "gpt-5.4-mini",
        api_key: Optional[str] = None,
        base_url: str = OPENAI_BASE_URL,
        provider_hint: str = "openai",
    ):
        self.model = model
        self.api_key = _resolve_key(api_key, provider_hint)
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "messages": messages}

        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI LLM generation failed ({self.model}): {e}")
            raise
