from .base import EmbeddingProvider, LLMProvider
from .ollama import OllamaProvider, OllamaLLM

def get_embedding_provider(name: str, base_url: str, model: str) -> EmbeddingProvider:
    if name == "ollama":
        return OllamaProvider(base_url=base_url, model=model)
    raise ValueError(f"Unknown embedding provider: {name}")

def get_llm_provider(name: str, base_url: str, model: str) -> LLMProvider:
    if name == "ollama":
        return OllamaLLM(base_url=base_url, model=model)
    elif name == "openai":
         # Return OpenAI provider when implemented
         pass
    raise ValueError(f"Unknown LLM provider: {name}")
