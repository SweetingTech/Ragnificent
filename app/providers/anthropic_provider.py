"""
Anthropic Claude provider for LLM generation.
Anthropic does not offer an embeddings API — use OpenAI or Ollama for embeddings.
"""
import os
import httpx
from typing import Optional
from .base import LLMProvider
from ..utils.logging import setup_logging

logger = setup_logging()

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicLLM(LLMProvider):
    """LLM provider using Anthropic's Messages API."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: Optional[str] = None,
        base_url: str = ANTHROPIC_BASE_URL,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.base_url}/messages", json=payload, headers=headers
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
        except Exception as e:
            logger.error(f"Anthropic LLM generation failed ({self.model}): {e}")
            raise
