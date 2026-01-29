"""
Provider factory for creating embedding and LLM provider instances.
"""
from .base import EmbeddingProvider, LLMProvider
from .ollama import OllamaProvider, OllamaLLM

# Supported providers
SUPPORTED_EMBEDDING_PROVIDERS = ["ollama"]
SUPPORTED_LLM_PROVIDERS = ["ollama"]


def get_embedding_provider(name: str, base_url: str, model: str) -> EmbeddingProvider:
    """
    Create an embedding provider instance.

    Args:
        name: Provider name (e.g., "ollama")
        base_url: Base URL for the provider API
        model: Model name to use

    Returns:
        Configured embedding provider instance

    Raises:
        ValueError: If the provider name is not supported
    """
    if name == "ollama":
        return OllamaProvider(base_url=base_url, model=model)

    raise ValueError(
        f"Unknown embedding provider: '{name}'. "
        f"Supported providers: {SUPPORTED_EMBEDDING_PROVIDERS}"
    )


def get_llm_provider(name: str, base_url: str, model: str) -> LLMProvider:
    """
    Create an LLM provider instance.

    Args:
        name: Provider name (e.g., "ollama")
        base_url: Base URL for the provider API
        model: Model name to use

    Returns:
        Configured LLM provider instance

    Raises:
        ValueError: If the provider name is not supported
    """
    if name == "ollama":
        return OllamaLLM(base_url=base_url, model=model)

    raise ValueError(
        f"Unknown LLM provider: '{name}'. "
        f"Supported providers: {SUPPORTED_LLM_PROVIDERS}"
    )


def list_supported_providers() -> dict:
    """
    List all supported providers.

    Returns:
        Dictionary with 'embedding' and 'llm' keys listing supported providers
    """
    return {
        "embedding": SUPPORTED_EMBEDDING_PROVIDERS,
        "llm": SUPPORTED_LLM_PROVIDERS
    }
