from app.config.schema import GlobalConfig
from app.state.db import Database
from app.vector.qdrant_client import VectorService
from app.utils.logging import setup_logging
from app.utils.hashing import hash_file
from app.engines.pdf_engine import PdfEngine
from app.providers.ollama import OllamaProvider
from app.ingest.chunkers.pdf_sections import PdfSectionChunker
from app.ingest.chunkers.code_symbols import CodeSymbolChunker

import os
import yaml
import glob
from pathlib import Path
from typing import Optional, List, Dict
import time
import uuid

logger = setup_logging()

from app.providers.factory import get_embedding_provider
# ... imports

class IngestionPipeline:
    def __init__(self, config: GlobalConfig, db: Database, vector_service: VectorService):
        self.config = config
        self.db = db
        self.vector_service = vector_service
        self.pdf_engine = PdfEngine(config)
        
        # Use factory
        self.embedder = get_embedding_provider(
            name=config.models.embeddings.provider,
            base_url=config.models.embeddings.base_url,
            model=config.models.embeddings.model
        )
        
        # Chunker registry
        self.chunkers = {
            "pdf_sections": PdfSectionChunker(),
            "code_symbols": CodeSymbolChunker(),
            "default": PdfSectionChunker() # Fallback
        }

    def _get_corpora(self, corpus_id: Optional[str] = None):
        """
        Scan config/disk for requested corpora.
        """
        corpora = []
        # TODO: Use config.library_root
        # For now, we scan rag_library/corpora
        root = Path("rag_library/corpora")
        
        target_dirs = [root / corpus_id] if corpus_id else root.iterdir()
        
        for d in target_dirs:
            if d.is_dir() and (d / "corpus.yaml").exists():
                try:
                    with open(d / "corpus.yaml") as f:
                        meta = yaml.safe_load(f)
                    corpora.append({
                        "id": meta.get("corpus_id"),
                        "source_path": meta.get("source_path"),
                        "inbox_path": str((d / "inbox").resolve()), # Fallback if source_path not set
                        "config": meta
                    })
                except Exception as e:
                    logger.error(f"Failed to load corpus {d}: {e}")
        return corpora

    def _scan_files(self, source_path: str) -> List[str]:
        # Recursive scan
        # Supporting PDF, MD, TXT, PY for now
        extensions = ['**/*.pres', '**/*.pdf', '**/*.md', '**/*.txt', '**/*.py']
        files = []
        for ext in extensions:
            # glob.glob with recursive=True
            found = glob.glob(os.path.join(source_path, ext), recursive=True)
            files.extend(found)
        return files

    def run_once(self, corpus_id: Optional[str] = None):
        logger.info(f"Starting ingestion run (corpus={corpus_id or 'all'})...")
        
        conn = self.db.get_connection()
        corpora = self._get_corpora(corpus_id)
        
        for corpus in corpora:
            cid = corpus['id']
            # Determine path to scan: source_path (external) or inbox_path (internal)
            scan_path = corpus.get('source_path') or corpus.get('inbox_path')
            
            logger.info(f"Scanning corpus: {cid} at {scan_path}")
            if not os.path.exists(scan_path):
                logger.warning(f"Path does not exist: {scan_path}")
                continue
                
            files = self._scan_files(scan_path)
            logger.info(f"Found {len(files)} candidates.")
            
            for file_path in files:
                try:
                    self._process_file(file_path, cid, conn)
                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")
                    # Update DB status to FAILED via helper if needed
        
        logger.info("Ingestion run complete.")

    def _process_file(self, file_path: str, corpus_id: str, conn):
        # 1. Start Transaction (implicit or explicit)
        
        # 2. Hash File
        current_hash = hash_file(file_path)
        
        # 3. Check DB
        cursor = conn.cursor()
        cursor.execute("SELECT file_hash, status FROM files WHERE file_path = ? AND corpus_id = ?", (file_path, corpus_id))
        row = cursor.fetchone()
        
        if row:
            db_hash, status = row
            if db_hash == current_hash and status == 'SUCCESS':
                logger.debug(f"Skipping unchanged file: {file_path}")
                return
            else:
                logger.info(f"File changed or failed previously: {file_path}")
                # We need to re-ingest. First, delete old chunks if any?
                # Ideally we delete by old hash, but here we just upsert new
                pass
        
        # 4. Extract
        logger.info(f"Extracting {file_path}...")
        ext = os.path.splitext(file_path)[1].lower()
        text = ""
        metadata = {"source": file_path}
        
        if ext == '.pdf':
            res = self.pdf_engine.extract(file_path)
            text = res['text']
            metadata.update(res['metadata'])
        else:
            # Text based fallback
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        
        # 5. Chunk
        # Select chunker based on config or extension
        # Simplified selection:
        chunker = self.chunkers['default']
        if ext == '.py':
            chunker = self.chunkers['code_symbols']
        
        chunks = chunker.chunk(text, metadata)
        logger.info(f"Generated {len(chunks)} chunks.")
        
        if not chunks:
            logger.warning(f"No text extracted for {file_path}")
            # Mark FAILED
            return

        # 6. Embed
        chunk_texts = [c['content'] for c in chunks]
        start_time = time.time()
        embeddings = self.embedder.embed(chunk_texts)
        logger.info(f"Embedded {len(embeddings)} chunks in {time.time() - start_time:.2f}s")
        
        # 7. Upsert to Vector DB
        vectors_payload = []
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{current_hash}:{i}"))
            
            # Enrich payload
            payload = chunk['metadata'].copy()
            payload['text'] = chunk['content']
            payload['file_hash'] = current_hash
            payload['file_name'] = os.path.basename(file_path)
            payload['corpus_id'] = corpus_id
            
            vectors_payload.append({
                "id": chunk_id,
                "vector": vector,
                "payload": payload
            })
            
        self.vector_service.upsert_chunks(corpus_id, vectors_payload)
        
        # 8. Record Success in DB
        cursor.execute("""
            INSERT OR REPLACE INTO files (file_hash, file_path, corpus_id, size_bytes, last_modified, status, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'SUCCESS', CURRENT_TIMESTAMP)
        """, (current_hash, file_path, corpus_id, os.path.getsize(file_path)))
        conn.commit()
        logger.info(f"Successfully ingested {file_path}")
