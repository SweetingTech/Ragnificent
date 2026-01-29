from typing import List, Dict, Optional
from pathlib import Path
import yaml
import time
from ..vector.qdrant_client import VectorService
from ..providers.base import EmbeddingProvider, LLMProvider
from ..utils.logging import setup_logging
from ..providers.factory import get_llm_provider

logger = setup_logging()

class QueryEngine:
    def __init__(self, vector_service: VectorService, embedder: EmbeddingProvider, default_llm: Optional[LLMProvider] = None):
        self.vector_service = vector_service
        self.embedder = embedder
        self.default_llm = default_llm

    def _resolve_llm(self, corpus_id: str) -> Optional[LLMProvider]:
        """Loads corpus.yaml to get specific LLM model, falls back to default."""
        try:
            config_path = Path(f"rag_library/corpora/{corpus_id}/corpus.yaml")
            if config_path.exists():
                with open(config_path) as f:
                    meta = yaml.safe_load(f)
                
                # Check for models.answer section
                answer_config = meta.get("models", {}).get("answer")
                if answer_config:
                    provider = answer_config.get("provider", "ollama")
                    model = answer_config.get("model", "llama3")
                    # We assume base_url matches embedding for now or defaults
                    # Ideally config has base_url too
                    return get_llm_provider(provider, base_url="http://localhost:11434", model=model)
        except Exception as e:
            logger.warning(f"Failed to load corpus LLM config: {e}")
        
        return self.default_llm

    def query(self, query_text: str, corpus_id: Optional[str] = None, top_k: int = 5, llm_model: Optional[str] = None) -> Dict:
        start_time = time.time()
        
        # 1. Embed & Search (Only if corpus_id provided)
        hits = []
        if corpus_id:
            query_vector = self.embedder.embed([query_text])[0]
            hits = self.vector_service.search(corpus_id, query_vector, limit=top_k)
        
        # 2. Format Hits
        formatted_hits = []
        context_parts = []
        for hit in hits:
            formatted_hits.append({
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload
            })
            meta = hit.payload
            source = f"File: {meta.get('file_name', 'unknown')} (Page {meta.get('page', '?')})"
            context_parts.append(f"[{source}]: {meta.get('text', '')}")

        # 3. Resolve LLM
        # Logic: 
        # - If corpus_id -> use corpus config
        # - If llm_model param -> use that (Ad-Hoc)
        # - Else -> default_llm
        
        llm = None
        if corpus_id:
            llm = self._resolve_llm(corpus_id)
        elif llm_model:
            # Ad-Hoc override
            # Assuming Ollama for now as per v1 scope
            # We construct a transient provider
            try:
                llm = get_llm_provider("ollama", base_url="http://localhost:11434", model=llm_model)
            except Exception:
                llm = self.default_llm
        else:
            llm = self.default_llm

        # 4. Generate Answer
        answer = None
        if llm:
            if corpus_id and formatted_hits:
                # RAG Mode
                system_prompt = (
                    "You are an intelligent librarian assistant. "
                    "Answer the user question based ONLY on the provided context excerpts. "
                    "If the answer is not in the context, say you don't know."
                )
                context_str = "\n\n".join(context_parts)
                user_prompt = f"Context:\n{context_str}\n\nQuestion: {query_text}\nAnswer:"
            else:
                # Chat Mode (Ad-Hoc)
                system_prompt = "You are a helpful AI assistant."
                user_prompt = query_text
            
            try:
                answer = llm.generate(user_prompt, system_prompt=system_prompt)
            except Exception as e:
                logger.error(f"LLM Generation failed: {e}")
                answer = f"Error generating answer: {e}"
        else:
            if not corpus_id:
                answer = "No LLM selected for chat."
        
        return {
            "query": query_text,
            "hits": formatted_hits,
            "answer": answer,
            "time": time.time() - start_time
        }
