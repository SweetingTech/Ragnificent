from pydantic import BaseModel, Field
from typing import Optional, Dict

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

class ModelsConfig(BaseModel):
    embeddings: EmbeddingsConfig

class VectorDbConfig(BaseModel):
    backend: str
    url: str
    collection_prefix: str

class GlobalConfig(BaseModel):
    library_root: str
    ingest: IngestConfig
    extraction: ExtractionConfig
    ocr: OcrConfig
    models: ModelsConfig
    vector_db: VectorDbConfig
