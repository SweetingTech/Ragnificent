"""
Corpora API routes — agent-facing endpoints for discovering and managing RAG databases.

Designed for programmatic access by AI agents and other clients.
"""
from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from functools import lru_cache
import os
import shutil

from ...config.loader import load_config
from ...config.schema import GlobalConfig
from ...services.corpus_service import CorpusService, CorpusValidationError, validate_corpus_id
from ...vector.qdrant_client import VectorService
from ...state.db import Database
from ...utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/corpora", tags=["corpora"])


class CorpusSummary(BaseModel):
    """Summary of a single RAG corpus, suitable for agent discovery.

    Absolute filesystem paths are intentionally omitted to avoid leaking
    local directory structure to unauthenticated callers over the network.
    """
    corpus_id: str
    description: str
    vector_count: int
    query_endpoint: str


class CorpusDetail(CorpusSummary):
    """Full detail for a single corpus, including chunking and model config."""
    config: Dict[str, Any]


class CreateCorpusRequest(BaseModel):
    """Request body for creating a new corpus via the API."""
    corpus_id: str
    description: str
    source_path: str
    llm_model: str = "llama3"
    llm_provider: str = "ollama"
    llm_base_url: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_preset: Optional[str] = None
    chunk_strategy: str = "pdf_sections"
    chunk_max_tokens: int = 700
    chunk_overlap_tokens: int = 80


class CreateCorpusResponse(BaseModel):
    status: str
    corpus_id: str
    message: str
    query_endpoint: str


@lru_cache()
def get_config() -> GlobalConfig:
    return load_config()


def get_corpus_service() -> CorpusService:
    config = get_config()
    return CorpusService(config.library_root)


def get_vector_service() -> VectorService:
    config = get_config()
    return VectorService(config.vector_db.url, config.vector_db.collection_prefix)


def get_database() -> Database:
    config = get_config()
    return Database(config.get_state_db_path())


def _build_summary(corpus_meta: Dict, vector_service: VectorService) -> CorpusSummary:
    corpus_id = corpus_meta["corpus_id"]
    return CorpusSummary(
        corpus_id=corpus_id,
        description=corpus_meta.get("description", ""),
        vector_count=vector_service.get_count(corpus_id),
        query_endpoint="/api/query",
    )


@router.get("", response_model=List[CorpusSummary])
async def list_corpora(
    corpus_service: CorpusService = Depends(get_corpus_service),
    vector_service: VectorService = Depends(get_vector_service),
):
    """
    List all available RAG databases (corpora).

    Returns one entry per corpus with:
    - corpus_id   — pass this as `corpus_id` in POST /api/query
    - description — human-readable label
    - vector_count — how many chunks are indexed (0 = not yet ingested)
    - query_endpoint — the URL to POST queries to
    - source_path — the folder being watched for new documents
    - inbox_path  — the drop folder inside the rag_library

    Agents should call this first to discover which corpus to query.
    """
    all_meta = corpus_service.get_all_corpora()
    return [_build_summary(m, vector_service) for m in all_meta]




@router.get("/{corpus_id}", response_model=CorpusDetail)
async def get_corpus(
    corpus_id: str,
    corpus_service: CorpusService = Depends(get_corpus_service),
    vector_service: VectorService = Depends(get_vector_service),
):
    """
    Get full detail for a single corpus by ID.

    Returns everything in the corpus summary plus the raw corpus.yaml config,
    which includes chunking strategy, model overrides, etc.
    """
    try:
        validate_corpus_id(corpus_id)
    except CorpusValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    meta = corpus_service.get_corpus_metadata(corpus_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    summary = _build_summary(meta, vector_service)
    return CorpusDetail(**summary.model_dump(), config=meta.get("config", {}))



@router.post("", response_model=CreateCorpusResponse, status_code=201)
async def create_corpus(
    body: CreateCorpusRequest,
    corpus_service: CorpusService = Depends(get_corpus_service),
):
    """
    Create a new RAG corpus (database) via the API.

    `source_path` is the folder on the local filesystem whose documents will
    be ingested into this corpus. The vector database itself will always live
    inside rag_library — only the *source* of documents is external.

    After creating the corpus, trigger ingestion with:
        POST /api/ingest/run?corpus_id=<corpus_id>

    Then query it with:
        POST /api/query  {\"query\": \"...\", \"corpus_id\": \"<corpus_id>\"}
    """
    try:
        validate_corpus_id(body.corpus_id)
    except CorpusValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if corpus_service.corpus_exists(body.corpus_id):
        raise HTTPException(
            status_code=409,
            detail=f"Corpus '{body.corpus_id}' already exists"
        )

    source_path = body.source_path.strip() if body.source_path else ""
    if not source_path:
        raise HTTPException(status_code=400, detail="source_path is required")
    if not os.path.isdir(source_path):
        raise HTTPException(
            status_code=400,
            detail=f"source_path does not exist or is not a directory: {source_path}"
        )

    corpus_path = corpus_service.get_corpus_path(body.corpus_id)
    created_on_disk = False
    try:
        corpus_service.create_corpus(
            corpus_id=body.corpus_id,
            description=body.description,
            source_path=source_path,
            llm_model=body.llm_model,
            llm_provider=body.llm_provider,
            llm_base_url=body.llm_base_url,
            embedding_provider=body.embedding_provider,
            embedding_model=body.embedding_model,
            embedding_base_url=body.embedding_base_url,
            embedding_preset=body.embedding_preset,
            chunk_strategy=body.chunk_strategy,
            chunk_max_tokens=body.chunk_max_tokens,
            chunk_overlap_tokens=body.chunk_overlap_tokens,
        )
        created_on_disk = True
        logger.info(f"API: created corpus {body.corpus_id}")
    except Exception as e:
        logger.exception(f"Failed to create corpus {body.corpus_id}")
        # Roll back the on-disk corpus if vector collection setup failed
        if created_on_disk and corpus_path.exists():
            try:
                shutil.rmtree(corpus_path)
                logger.info(f"Rolled back corpus directory for {body.corpus_id}")
            except Exception:
                logger.exception(f"Rollback failed for {body.corpus_id}")
        raise HTTPException(status_code=500, detail="Failed to create corpus. Check server logs for details.")

    return CreateCorpusResponse(
        status="created",
        corpus_id=body.corpus_id,
        message=(
            f"Corpus '{body.corpus_id}' created. "
            f"Trigger ingestion with POST /api/ingest/run?corpus_id={body.corpus_id}"
        ),
        query_endpoint="/api/query",
    )


@router.delete("/{corpus_id}", status_code=204)
async def delete_corpus(
    corpus_id: str,
    corpus_service: CorpusService = Depends(get_corpus_service),
    vector_service: VectorService = Depends(get_vector_service),
    db: Database = Depends(get_database),
):
    """
    Permanently delete a corpus: removes the Qdrant collection, all SQLite records,
    and the corpus directory on disk. This cannot be undone.
    """
    try:
        validate_corpus_id(corpus_id)
    except CorpusValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not corpus_service.corpus_exists(corpus_id):
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    # 1. Drop Qdrant collection
    vector_service.delete_collection(corpus_id)

    # 2. Delete SQLite records for this corpus
    try:
        with db.transaction() as conn:
            conn.execute("DELETE FROM chunks WHERE corpus_id = ?", (corpus_id,))
            conn.execute("DELETE FROM files WHERE corpus_id = ?", (corpus_id,))
    except Exception as e:
        logger.warning(f"Failed to clean up SQLite records for {corpus_id}: {e}")

    # 3. Remove the corpus directory
    corpus_path = corpus_service.get_corpus_path(corpus_id)
    try:
        shutil.rmtree(corpus_path)
        logger.info(f"Deleted corpus '{corpus_id}'")
    except Exception as e:
        logger.error(f"Failed to remove corpus directory for {corpus_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Corpus data deleted but directory removal failed: {e}")

    return Response(status_code=204)
