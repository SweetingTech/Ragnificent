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


class OcrConfig(BaseModel):
    backend: str
    ocrmypdf: OcrMypdfConfig


class EmbeddingsConfig(BaseModel):
    provider: str
    base_url: str
    model: str


class AnswerModelConfig(BaseModel):
    """Configuration for the default answer/LLM model."""
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "llama3"


class ModelsConfig(BaseModel):
    embeddings: EmbeddingsConfig
    answer: Optional[AnswerModelConfig] = None


class VectorDbConfig(BaseModel):
    backend: str
    url: str
    collection_prefix: str


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
        # Priority: env var > config > derived from library_root
        if os.getenv("STATE_DB_PATH"):
            return os.getenv("STATE_DB_PATH")
        if self.state_db and self.state_db.path:
            return self.state_db.path
        # Fallback: derive from library_root
        return str(Path(self.library_root) / "state" / "ingest.sqlite")

    def get_corpora_path(self) -> str:
        """Get the path to the corpora directory."""
        return str(Path(self.library_root) / "corpora")
