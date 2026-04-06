from pydantic import BaseModel, Field
from typing import Optional, Dict
from pathlib import Path
import os


class IngestConfig(BaseModel):
    poll_interval_seconds: int = 300
    max_parallel_files: int = 1
    lock_file: str
    ocr_trigger: Dict[str, float]


class ExtractionConfig(BaseModel):
    pdf_backend: str
    normalize: Dict[str, bool]


class OcrMypdfConfig(BaseModel):
    language: str
    deskew: bool
    rotate_pages: bool
    clean: bool
    cache_dir: str


class OcrOllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "hf.co/ggml-org/GLM-OCR-GGUF:Q8_0"
    prompt: str = "Text Recognition:"


class OcrConfig(BaseModel):
    backend: str
    ocrmypdf: OcrMypdfConfig
    ollama: Optional[OcrOllamaConfig] = None


class EmbeddingsConfig(BaseModel):
    provider: str
    base_url: Optional[str] = None  # defaults per provider if omitted
    model: str
    api_key: Optional[str] = None   # prefer env vars; stored here only as override


class AnswerModelConfig(BaseModel):
    """Configuration for the default answer/LLM model."""
    provider: str = "ollama"
    base_url: Optional[str] = None  # defaults per provider if omitted
    model: str = "llama3"
    api_key: Optional[str] = None   # prefer env vars; stored here only as override


class RerankConfig(BaseModel):
    """Configuration for the reranker."""
    enabled: bool = False
    provider: str = "ollama"
    base_url: Optional[str] = None
    model: str = "llama3"


class ModelsConfig(BaseModel):
    embeddings: EmbeddingsConfig
    answer: Optional[AnswerModelConfig] = None
    rerank: Optional[RerankConfig] = None


class VectorDbConfig(BaseModel):
    backend: str
    url: str
    collection_prefix: str
    vector_size: Optional[int] = None
    on_disk: bool = True
    hnsw_on_disk: bool = True


class StateDbConfig(BaseModel):
    """Configuration for the state database."""
    path: str = "rag_library/state/ingest.sqlite"


class GlobalConfig(BaseModel):
    library_root: str
    ingest: IngestConfig
    extraction: ExtractionConfig
    ocr: OcrConfig
    models: ModelsConfig
    vector_db: VectorDbConfig
    state_db: Optional[StateDbConfig] = None

    def get_state_db_path(self) -> str:
        """Get the state database path, with fallback logic."""
        if os.getenv("STATE_DB_PATH"):
            return os.getenv("STATE_DB_PATH")
        if self.state_db and self.state_db.path:
            return self.state_db.path
        return str(Path(self.library_root) / "state" / "ingest.sqlite")

    def get_corpora_path(self) -> str:
        """Get the path to the corpora directory."""
        return str(Path(self.library_root) / "corpora")
