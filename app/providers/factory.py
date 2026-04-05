"""
Provider factory for creating embedding and LLM provider instances.
Supports: ollama, openai, anthropic, openrouter
"""
from typing import Optional
from .base import EmbeddingProvider, LLMProvider
from .ollama import OllamaProvider, OllamaLLM
from .openai_provider import OpenAIEmbeddingProvider, OpenAILLM, OPENAI_BASE_URL, OPENROUTER_BASE_URL
from .anthropic_provider import AnthropicLLM, ANTHROPIC_BASE_URL

SUPPORTED_EMBEDDING_PROVIDERS = ["ollama", "openai", "openrouter"]
SUPPORTED_LLM_PROVIDERS = ["ollama", "openai", "anthropic", "openrouter"]

# Default base URLs per provider
_PROVIDER_DEFAULTS = {
    "ollama":      "http://localhost:11434",
    "openai":      OPENAI_BASE_URL,
    "openrouter":  OPENROUTER_BASE_URL,
    "anthropic":   ANTHROPIC_BASE_URL,
}


def _resolve_url(provider: str, base_url: Optional[str]) -> str:
    """Return base_url if set, otherwise use the provider's default."""
    if base_url:
        return base_url
    return _PROVIDER_DEFAULTS.get(provider, "")


def get_embedding_provider(
    name: str,
    base_url: Optional[str] = None,
    model: str = "nomic-embed-text",
    api_key: Optional[str] = None,
) -> EmbeddingProvider:
    """
    Create an embedding provider instance.

    Args:
        name:     Provider name — ollama | openai
        model:    Embedding model name
        base_url: API base URL (uses provider default if omitted)
        api_key:  API key (falls back to env vars if omitted)
    """
    url = _resolve_url(name, base_url)

    if name == "ollama":
        return OllamaProvider(base_url=url, model=model)

    if name == "openai":
        return OpenAIEmbeddingProvider(
            model=model, api_key=api_key, base_url=url, provider_hint="openai"
        )

    if name == "openrouter":
        return OpenAIEmbeddingProvider(
            model=model, api_key=api_key, base_url=url, provider_hint="openrouter"
        )

    raise ValueError(
        f"Unknown embedding provider: '{name}'. "
        f"Supported: {SUPPORTED_EMBEDDING_PROVIDERS}"
    )


def get_llm_provider(
    name: str,
    base_url: Optional[str] = None,
    model: str = "llama3",
    api_key: Optional[str] = None,
) -> LLMProvider:
    """
    Create an LLM provider instance.

    Args:
        name:     Provider name — ollama | openai | anthropic | openrouter
        model:    Model name
        base_url: API base URL (uses provider default if omitted)
        api_key:  API key (falls back to env vars if omitted)
    """
    url = _resolve_url(name, base_url)

    if name == "ollama":
        return OllamaLLM(base_url=url, model=model)

    if name == "openai":
        return OpenAILLM(model=model, api_key=api_key, base_url=url, provider_hint="openai")

    if name == "openrouter":
        return OpenAILLM(model=model, api_key=api_key, base_url=url, provider_hint="openrouter")

    if name == "anthropic":
        return AnthropicLLM(model=model, api_key=api_key, base_url=url)

    raise ValueError(
        f"Unknown LLM provider: '{name}'. "
        f"Supported: {SUPPORTED_LLM_PROVIDERS}"
    )


def list_supported_providers() -> dict:
    return {
        "embedding": SUPPORTED_EMBEDDING_PROVIDERS,
        "llm": SUPPORTED_LLM_PROVIDERS,
    }
