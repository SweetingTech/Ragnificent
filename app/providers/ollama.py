import ollama
from typing import List
from .base import EmbeddingProvider
import os

class OllamaProvider(EmbeddingProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        self.base_url = base_url
        self.model = model
        # The official python client uses OLLAMA_HOST env var automatically or we can pass client.
        # But for now, let's assume it reads env or we just set it.
        if base_url:
            os.environ["OLLAMA_HOST"] = base_url
            
    def embed(self, texts: List[str]) -> List[List[float]]:
        # Ollama batch embed ? currently ollama-python .embeddings() is one by one or maybe batch?
        # The new /api/embed (if available) supports batch.
        # But 'embeddings' call is usually single.
        # We'll iterate for safety or check library capabilities.
        results = []
        for text in texts:
            # We assume ollama.embeddings returns {'embedding': [...]}
            # clean newlines to avoid issues
            clean_text = text.replace("\n", " ")
            resp = ollama.embeddings(model=self.model, prompt=clean_text)
            results.append(resp['embedding'])
        return results
