"""
OpenAI-compatible provider for embeddings and LLM.
Works with OpenAI, OpenRouter, and any other OpenAI-compatible endpoint.
"""
import os
import httpx
from typing import List, Optional
from .base import EmbeddingProvider, LLMProvider
from ..utils.logging import setup_logging

logger = setup_logging()

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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
        payload = {"model": self.model, "input": texts}

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{self.base_url}/embeddings", json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                ordered = sorted(data["data"], key=lambda x: x["index"])
                return [e["embedding"] for e in ordered]
        except Exception as e:
            logger.error(f"OpenAI embedding failed ({self.model}): {e}")
            raise


class OpenAILLM(LLMProvider):
    """LLM provider using OpenAI chat completions API (or any compatible endpoint)."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
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
