from abc import ABC, abstractmethod
from typing import List

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        pass

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Generates text based on prompt."""
        pass
