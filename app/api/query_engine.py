"""
Query engine for RAG-based search and answer generation.
Handles vector search, context assembly, and LLM answer generation.
"""
from typing import Dict, Optional, Any
from pathlib import Path
import yaml
import time

from ..vector.qdrant_client import VectorService
from ..providers.base import EmbeddingProvider, LLMProvider
from ..providers.factory import get_llm_provider
from ..services.corpus_service import validate_corpus_id, CorpusValidationError
from ..utils.logging import setup_logging
from ..config.loader import load_config
from ..config.schema import GlobalConfig

logger = setup_logging()

# Default base URL for LLM providers (loaded from config when possible)
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class QueryEngine:
    """
    Engine for processing RAG queries.

    Handles:
    - Query embedding and vector search
    - Context formatting from search results
    - LLM resolution (corpus-specific or default)
    - Answer generation
    """

    def __init__(
        self,
        vector_service: VectorService,
        embedder: EmbeddingProvider,
        default_llm: Optional[LLMProvider] = None,
        default_base_url: Optional[str] = None,
        config: Optional[GlobalConfig] = None
    ):
        """
        Initialize the query engine.

        Args:
            vector_service: Service for vector database operations
            embedder: Provider for generating query embeddings
            default_llm: Default LLM provider for answer generation
            default_base_url: Default base URL for LLM providers
            config: Optional pre-loaded configuration (avoids re-loading)
        """
        self.vector_service = vector_service
        self.embedder = embedder
        self.default_llm = default_llm
        self.config = config

        # Cache config if not provided
        if self.config is None:
            try:
                self.config = load_config()
            except Exception:
                self.config = None

        # Resolve base_url from config or fallback
        if self.config and hasattr(self.config.models, 'embeddings'):
            self.base_url = self.config.models.embeddings.base_url
        else:
            self.base_url = default_base_url or DEFAULT_OLLAMA_URL

    def _get_corpus_config_path(self, corpus_id: str) -> Optional[Path]:
        """
        Get the path to corpus config file.

        Args:
            corpus_id: Corpus identifier

        Returns:
            Path to corpus.yaml or None if not found
        """
        try:
            validate_corpus_id(corpus_id)

            # Use cached config if available
            if self.config and hasattr(self.config, 'library_root'):
                base_path = Path(self.config.library_root) / "corpora" / corpus_id
            else:
                base_path = Path("rag_library/corpora") / corpus_id

            config_path = base_path / "corpus.yaml"
            if config_path.exists():
                return config_path
        except CorpusValidationError as e:
            logger.warning(f"Invalid corpus_id '{corpus_id}': {e}")
        return None

    def _resolve_llm(self, corpus_id: str) -> Optional[LLMProvider]:
        """
        Resolve the LLM provider for a corpus.

        First checks corpus-specific configuration, then falls back to default.

        Args:
            corpus_id: Corpus identifier

        Returns:
            LLM provider instance or None
        """
        config_path = self._get_corpus_config_path(corpus_id)
        if config_path:
            try:
                with open(config_path) as f:
                    meta = yaml.safe_load(f)

                answer_config = meta.get("models", {}).get("answer")
                if answer_config:
                    provider = answer_config.get("provider", "ollama")
                    model = answer_config.get("model", "llama3")
                    base_url = answer_config.get("base_url", self.base_url)
                    return get_llm_provider(provider, base_url=base_url, model=model)
            except Exception as e:
                logger.warning(f"Failed to load corpus LLM config for {corpus_id}: {e}")

        return self.default_llm

    def query(
        self,
        query_text: str,
        corpus_id: Optional[str] = None,
        top_k: int = 5,
        llm_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute a RAG query.

        Args:
            query_text: The user's query
            corpus_id: Optional corpus to search
            top_k: Maximum number of results to retrieve
            llm_model: Optional LLM model override

        Returns:
            Dictionary with query, hits, answer, and timing information
        """
        start_time = time.time()

        # Validate corpus_id if provided
        if corpus_id:
            try:
                validate_corpus_id(corpus_id)
            except CorpusValidationError as e:
                logger.warning(f"Invalid corpus_id: {e}")
                return {
                    "query": query_text,
                    "hits": [],
                    "answer": f"Invalid corpus ID: {e}",
                    "time": time.time() - start_time
                }

        # 1. Embed & Search (only if corpus_id provided)
        hits = []
        if corpus_id:
            try:
                query_vector = self.embedder.embed([query_text])[0]
                hits = self.vector_service.search(corpus_id, query_vector, limit=top_k)
            except Exception as e:
                logger.error(f"Search failed: {e}")

        # 2. Format hits and build context
        formatted_hits = []
        context_parts = []
        for hit in hits:
            formatted_hits.append({
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload
            })

            meta = hit.payload
            file_name = meta.get('file_name', 'unknown')
            page = meta.get('page', meta.get('chunk_index', '?'))
            source = f"File: {file_name} (Section {page})"
            text = meta.get('text', '')
            context_parts.append(f"[{source}]:\n{text}")

        # 3. Resolve LLM provider
        llm = None
        if llm_model:
            # Ad-hoc model override
            try:
                llm = get_llm_provider("ollama", base_url=self.base_url, model=llm_model)
            except Exception as e:
                logger.warning(f"Failed to create LLM with model {llm_model}: {e}")
                llm = self.default_llm
        elif corpus_id:
            # Use corpus-specific config
            llm = self._resolve_llm(corpus_id)
        else:
            # Use default
            llm = self.default_llm

        # 4. Generate answer
        answer = None
        if llm:
            if corpus_id and formatted_hits:
                # RAG mode - answer based on context
                system_prompt = (
                    "You are an intelligent librarian assistant. "
                    "Answer the user question based ONLY on the provided context excerpts. "
                    "If the answer is not in the context, say you don't know. "
                    "Cite sources when possible."
                )
                context_str = "\n\n".join(context_parts)
                user_prompt = f"Context:\n{context_str}\n\nQuestion: {query_text}\n\nAnswer:"
            else:
                # Chat mode - general conversation
                system_prompt = "You are a helpful AI assistant."
                user_prompt = query_text

            try:
                answer = llm.generate(user_prompt, system_prompt=system_prompt)
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                answer = f"Error generating answer: {e}"
        else:
            if not corpus_id and not llm_model:
                answer = "No LLM selected. Please select a corpus or model."

        return {
            "query": query_text,
            "hits": formatted_hits,
            "answer": answer,
            "time": time.time() - start_time
        }
