"""
Document ingestion pipeline for processing and indexing documents.
Handles file scanning, extraction, chunking, embedding, and storage.
"""
from typing import Optional, List, Dict, Any, Callable
import os
import glob
import time
import uuid

from ..config.schema import GlobalConfig
from ..state.db import Database
from ..vector.qdrant_client import VectorService
from ..utils.logging import setup_logging
from ..utils.hashing import hash_file
from ..engines.pdf_engine import PdfEngine
from ..engines.epub_extractor import EpubExtractor
from ..engines.image_extractor import ImageExtractor
from ..providers.factory import (
    PROVIDER_DEFAULT_BASE_URLS,
    get_embedding_provider,
)
from ..services.corpus_service import CorpusService, validate_corpus_id, CorpusValidationError
from .chunkers.pdf_sections import PdfSectionChunker
from .chunkers.code_symbols import CodeSymbolChunker
from .chunkers.markdown import MarkdownChunker

logger = setup_logging()

# Supported file extensions
SUPPORTED_EXTENSIONS = [
    '**/*.pres', '**/*.pdf', '**/*.md', '**/*.txt', '**/*.py',
    '**/*.epub', '**/*.png', '**/*.jpg', '**/*.jpeg', '**/*.tiff'
]
CHUNK_STRATEGY_ALIASES = {
    "heading_then_paragraph": "markdown",
    "markdown": "markdown",
    "paragraph_sections": "pdf_sections",
    "pdf_sections": "pdf_sections",
    "code_symbols": "code_symbols",
}

OLLAMA_EMBED_MAX_TOKENS_CAP = 220
OLLAMA_EMBED_OVERLAP_CAP = 40
OLLAMA_EMBED_MAX_CHARS_CAP = 800


class IngestionPipeline:
    """Pipeline for ingesting documents into the vector database."""

    def __init__(self, config: GlobalConfig, db: Database, vector_service: VectorService):
        """
        Initialize the ingestion pipeline.

        Args:
            config: Global configuration object
            db: Database instance for state management
            vector_service: Vector database service
        """
        self.config = config
        self.db = db
        self.vector_service = vector_service

        # Select OCR Engine
        from ..engines.ocr_ollama import OllamaOCREngine
        from ..engines.ocr_my_pdf import OCRmyPDFEngine
        from ..engines.ocr_tesseract import TesseractEngine

        # Determine the OCR engine based on config
        ocr_backend = config.ocr.backend.lower()

        # Create engines based on config or defaults
        pdf_ocr_engine = OCRmyPDFEngine(config)
        image_ocr_engine = TesseractEngine()

        if ocr_backend == "paddleocr":
            try:
                from ..engines.ocr_paddle import PaddleOCREngine
                paddle_engine = PaddleOCREngine()
                pdf_ocr_engine = paddle_engine
                image_ocr_engine = paddle_engine
            except ImportError:
                logger.warning("PaddleOCR not installed, falling back to defaults")
        elif ocr_backend in {"ollama", "ollama_glm_ocr", "glm_ocr"}:
            try:
                ollama_engine = OllamaOCREngine(config, fallback_engine=TesseractEngine())
                pdf_ocr_engine = ollama_engine
                image_ocr_engine = ollama_engine
            except Exception:
                logger.exception("Failed to initialize Ollama OCR, falling back to defaults")

        # Initialize extractors
        from ..engines.scanned_pdf_extractor import ScannedPdfExtractor

        # If OCR backend is explicitly ocrmypdf, we use the ScannedPdfExtractor.
        # But generally, we want PdfEngine to try native extraction first,
        # then fall back to OCR on a per-page basis. The Prompt states:
        # "PDF: native extraction first, OCR fallback if text is low/empty... default backend should be Tesseract for images and OCRmyPDF for scanned PDFs."
        # Meaning: if we must run OCRmyPDF on the *entire* PDF, we can use ScannedPdfExtractor.
        # However, OCRmyPDF doesn't work well as a per-page fallback because it generates a new file.
        # Thus, PdfEngine internally falls back to Tesseract for per-page OCR (implemented via a try-except in PdfEngine).

        self.pdf_engine = PdfEngine(config, ocr_engine=pdf_ocr_engine)
        self.scanned_pdf_extractor = ScannedPdfExtractor(config, ocr_engine=pdf_ocr_engine)
        self.epub_extractor = EpubExtractor(config)
        self.image_extractor = ImageExtractor(config, ocr_engine=image_ocr_engine)

        self.corpus_service = CorpusService(config.library_root)

        # Initialize embedding provider from config
        self.embedder = get_embedding_provider(
            config.models.embeddings.provider,
            config.models.embeddings.base_url,
            config.models.embeddings.model,
            config.models.embeddings.api_key,
        )

    def _get_corpora(self, corpus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get corpora to process.

        Args:
            corpus_id: Optional specific corpus to process

        Returns:
            List of corpus metadata dictionaries
        """
        if corpus_id:
            try:
                validate_corpus_id(corpus_id)
                metadata = self.corpus_service.get_corpus_metadata(corpus_id)
                if metadata:
                    return [{
                        "id": metadata["corpus_id"],
                        "source_path": metadata.get("source_path"),
                        "inbox_path": metadata["inbox_path"],
                        "config": metadata.get("config", {})
                    }]
            except CorpusValidationError as e:
                logger.error(f"Invalid corpus ID: {e}")
            return []

        # Get all corpora
        all_corpora = self.corpus_service.get_all_corpora()
        return [{
            "id": c["corpus_id"],
            "source_path": c.get("source_path"),
            "inbox_path": c["inbox_path"],
            "config": c.get("config", {})
        } for c in all_corpora]

    def _scan_files(self, source_path: str) -> List[str]:
        """
        Recursively scan for supported files.

        Args:
            source_path: Directory to scan

        Returns:
            List of file paths
        """
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            found = glob.glob(os.path.join(source_path, ext), recursive=True)
            files.extend(found)
        return files

    def _get_failed_files(self, corpus_id: str) -> List[str]:
        """Return existing failed file paths for a corpus."""
        with self.db.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT file_path
                FROM files
                WHERE corpus_id = ? AND status = 'FAILED'
                ORDER BY updated_at DESC
                """,
                (corpus_id,),
            )
            rows = cursor.fetchall()

        failed_paths = []
        missing_count = 0
        for row in rows:
            path = row["file_path"]
            if path and os.path.exists(path):
                failed_paths.append(path)
            else:
                missing_count += 1
        if missing_count:
            logger.warning(
                f"Skipped {missing_count} missing failed-file entries while retrying corpus {corpus_id}"
            )
        return failed_paths

    def _get_embedding_settings(self, corpus_config: Dict[str, Any]) -> Dict[str, Any]:
        embedding_config = corpus_config.get("models", {}).get("embeddings", {})
        default_embeddings = self.config.models.embeddings
        provider = embedding_config.get("provider", self.config.models.embeddings.provider)
        model = embedding_config.get("model", self.config.models.embeddings.model)
        base_url = (
            embedding_config.get("base_url")
            or PROVIDER_DEFAULT_BASE_URLS.get(provider, default_embeddings.base_url)
        )
        if "api_key" in embedding_config:
            api_key = embedding_config.get("api_key")
        elif provider == default_embeddings.provider:
            api_key = default_embeddings.api_key
        else:
            api_key = None
        return {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
        }

    def _get_embedder_for_corpus(self, corpus_config: Dict[str, Any]):
        settings = self._get_embedding_settings(corpus_config)
        if (
            settings["provider"] == self.config.models.embeddings.provider
            and settings["model"] == self.config.models.embeddings.model
            and settings["base_url"] == self.config.models.embeddings.base_url
            and settings["api_key"] == self.config.models.embeddings.api_key
        ):
            return self.embedder
        return get_embedding_provider(
            settings["provider"],
            settings["base_url"],
            settings["model"],
            settings["api_key"],
        )

    def _get_chunker(self, file_ext: str, corpus_config: Dict[str, Any]):
        chunk_defaults = corpus_config.get("chunking", {}).get("default", {})
        strategy_name = chunk_defaults.get("strategy", "pdf_sections")
        strategy = CHUNK_STRATEGY_ALIASES.get(strategy_name, "pdf_sections")
        max_tokens = int(chunk_defaults.get("max_tokens", 700))
        overlap_tokens = int(chunk_defaults.get("overlap_tokens", 80))
        embed_settings = self._get_embedding_settings(corpus_config)
        max_chars = None

        # Ollama embedding models can reject chunks well below the user-configured
        # size when PDF extraction produces dense tokenization. Apply a conservative
        # runtime cap so ingest succeeds without forcing users to hand-tune per corpus.
        if embed_settings["provider"] == "ollama":
            max_tokens = min(max_tokens, OLLAMA_EMBED_MAX_TOKENS_CAP)
            overlap_tokens = min(overlap_tokens, OLLAMA_EMBED_OVERLAP_CAP)
            max_chars = OLLAMA_EMBED_MAX_CHARS_CAP

        if strategy == "code_symbols":
            return CodeSymbolChunker(max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        if strategy == "markdown":
            return MarkdownChunker(max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        if file_ext == ".py":
            return CodeSymbolChunker(max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        if file_ext in {".md", ".epub"}:
            return MarkdownChunker(max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        return PdfSectionChunker(
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            max_chars=max_chars,
        )

    def _emit_progress(
        self,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        payload: Dict[str, Any],
    ) -> None:
        """Send a progress update if the caller provided a callback."""
        if progress_callback:
            progress_callback(payload)

    def run_once(
        self,
        corpus_id: Optional[str] = None,
        source_path_override: Optional[str] = None,
        retry_failed_only: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        run_logger: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Run a single ingestion pass.

        Args:
            corpus_id: Optional specific corpus to process.
            source_path_override: Optional path to scan instead of the corpus-configured
                                  source/inbox path.  Can be any absolute or relative path
                                  accessible to the server (e.g. "D:/Books").
                                  Requires corpus_id to be set.
            progress_callback: Optional callback invoked with status updates.

        Returns:
            Summary of the ingestion run
        """
        logger.info(
            f"Starting ingestion run (corpus={corpus_id or 'all'}, "
            f"source_override={source_path_override}, retry_failed_only={retry_failed_only})..."
        )
        if run_logger:
            run_logger(
                "RUN START "
                f"corpus={corpus_id or 'all'} "
                f"source_override={source_path_override or '-'} "
                f"retry_failed_only={retry_failed_only}"
            )

        corpora = self._get_corpora(corpus_id)
        summary = {
            "corpora_processed": 0,
            "total_files": 0,
            "files_completed": 0,
            "files_processed": 0,
            "files_skipped": 0,
            "files_failed": 0,
        }
        queued_corpora = []

        for corpus in corpora:
            cid = corpus['id']
            # Use the caller-supplied override if given, otherwise fall back to
            # the corpus-configured path (source_path > inbox_path).
            scan_path = source_path_override or corpus.get('source_path') or corpus.get('inbox_path')

            logger.info(f"Scanning corpus: {cid} at {scan_path}")
            if run_logger:
                embed_settings = self._get_embedding_settings(corpus["config"])
                chunk_defaults = corpus["config"].get("chunking", {}).get("default", {})
                run_logger(
                    "CORPUS "
                    f"id={cid} scan_path={scan_path} "
                    f"embedding={embed_settings['provider']}/{embed_settings['model']} "
                    f"chunking={chunk_defaults.get('strategy', 'pdf_sections')}/"
                    f"{chunk_defaults.get('max_tokens', 700)}/"
                    f"{chunk_defaults.get('overlap_tokens', 80)}"
                )

            if not os.path.exists(scan_path):
                logger.warning(f"Path does not exist: {scan_path}")
                if run_logger:
                    run_logger(f"CORPUS SKIP id={cid} reason=missing_scan_path")
                continue

            files = self._get_failed_files(cid) if retry_failed_only else self._scan_files(scan_path)
            logger.info(f"Found {len(files)} candidates.")
            if run_logger:
                run_logger(f"CORPUS QUEUED id={cid} files={len(files)}")
            summary["total_files"] += len(files)
            queued_corpora.append({
                "id": cid,
                "scan_path": scan_path,
                "files": files,
                "config": corpus["config"],
            })

        self._emit_progress(progress_callback, {
            "status": "running",
            "corpora_total": len(queued_corpora),
            "corpora_processed": 0,
            "total_files": summary["total_files"],
            "files_completed": 0,
            "files_processed": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "percent_complete": 0.0,
            "current_corpus": queued_corpora[0]["id"] if queued_corpora else None,
            "current_file": None,
            "message": (
                f"Queued {summary['total_files']} failed files for retry."
                if retry_failed_only
                else f"Queued {summary['total_files']} files for ingestion."
            ),
        })

        for corpus in queued_corpora:
            cid = corpus["id"]
            files = corpus["files"]
            corpus_config = corpus["config"]
            embedder = self._get_embedder_for_corpus(corpus_config)

            for file_path in files:
                self._emit_progress(progress_callback, {
                    "status": "running",
                    "corpora_total": len(queued_corpora),
                    "corpora_processed": summary["corpora_processed"],
                    "total_files": summary["total_files"],
                    "files_completed": summary["files_completed"],
                    "files_processed": summary["files_processed"],
                    "files_skipped": summary["files_skipped"],
                    "files_failed": summary["files_failed"],
                    "percent_complete": round(
                        (summary["files_completed"] / summary["total_files"]) * 100, 1
                    ) if summary["total_files"] else 100.0,
                    "current_corpus": cid,
                    "current_file": file_path,
                    "message": f"Processing {summary['files_completed'] + 1} of {summary['total_files']}",
                })
                result = self._process_file(file_path, cid, corpus_config, embedder, run_logger)
                summary["files_completed"] += 1
                if result == "processed":
                    summary["files_processed"] += 1
                elif result == "skipped":
                    summary["files_skipped"] += 1
                else:
                    summary["files_failed"] += 1

                self._emit_progress(progress_callback, {
                    "status": "running",
                    "corpora_total": len(queued_corpora),
                    "corpora_processed": summary["corpora_processed"],
                    "total_files": summary["total_files"],
                    "files_completed": summary["files_completed"],
                    "files_processed": summary["files_processed"],
                    "files_skipped": summary["files_skipped"],
                    "files_failed": summary["files_failed"],
                    "percent_complete": round(
                        (summary["files_completed"] / summary["total_files"]) * 100, 1
                    ) if summary["total_files"] else 100.0,
                    "current_corpus": cid,
                    "current_file": file_path,
                    "message": f"Completed {summary['files_completed']} of {summary['total_files']}",
                })

            summary["corpora_processed"] += 1

        logger.info(f"Ingestion run complete. Summary: {summary}")
        if run_logger:
            run_logger(
                "RUN COMPLETE "
                f"corpora_processed={summary['corpora_processed']} "
                f"total_files={summary['total_files']} "
                f"files_processed={summary['files_processed']} "
                f"files_skipped={summary['files_skipped']} "
                f"files_failed={summary['files_failed']}"
            )
        return summary

    def _process_file(
        self,
        file_path: str,
        corpus_id: str,
        corpus_config: Dict[str, Any],
        embedder,
        run_logger: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Process a single file through the ingestion pipeline.

        Args:
            file_path: Path to the file
            corpus_id: ID of the corpus

        Returns:
            Status string: "processed", "skipped", or "failed"
        """
        try:
            if run_logger:
                run_logger(f"FILE START corpus={corpus_id} path={file_path}")
            # Hash file for deduplication
            current_hash = hash_file(file_path)

            # Check if file already processed (use context manager for proper cleanup)
            with self.db.cursor() as cursor:
                cursor.execute(
                    "SELECT file_hash, status FROM files WHERE file_hash = ?",
                    (current_hash,)
                )
                row = cursor.fetchone()

            if row:
                db_hash, status = row[0], row[1]
                if db_hash == current_hash and status == 'SUCCESS':
                    logger.debug(f"Skipping unchanged file: {file_path}")
                    if run_logger:
                        run_logger(f"FILE SKIPPED corpus={corpus_id} path={file_path} reason=unchanged")
                    return "skipped"
                logger.info(f"File changed or failed previously: {file_path}")

            # Extract text
            logger.info(f"Extracting {file_path}...")
            ext = os.path.splitext(file_path)[1].lower()
            text = ""
            metadata: Dict[str, Any] = {"source": file_path}

            if ext == '.pdf':
                # Route: Native text first, OCR fallback inside
                # For scanned pdfs, we could route to ScannedPdfExtractor based on heuristic,
                # but the prompt specifies "native extraction first, OCR fallback if text is low/empty".
                # To fulfill "OCRmyPDF for scanned PDFs" we can run the ScannedPdfExtractor
                # if the PdfEngine detects the entire document is scanned.
                # For simplicity and given the architectural constraint, we'll run PdfEngine first.
                result = self.pdf_engine.extract(file_path)
                text = result['text']
                metadata.update(result['metadata'])

                # Heuristic: if PDF is mostly images (very low chars) and OCRmyPDF is default,
                # we could run it through scanned pdf extractor. However, PdfEngine already
                # handles per-page OCR fallback, which is the requested "OCR fallback if text is low".
                # To properly satisfy the "OCRmyPDF for scanned PDFs" prompt instruction while keeping
                # "native extraction first", we check if the entire doc had very low text and we need to OCR it all.
                if len(text.strip()) < self.config.ingest.ocr_trigger.get('min_chars_per_page', 200) * result['metadata'].get('page_count', 1) * 0.1:
                    # If less than 10% of expected text was extracted even after fallback
                    # OR if the user explicitly prefers OCRmyPDF for the whole document
                    if self.scanned_pdf_extractor.ocr_engine is not None:
                        try:
                            logger.info(f"PDF {file_path} appears to be fully scanned, routing to OCRmyPDF...")
                            result = self.scanned_pdf_extractor.extract(file_path)
                            text = result['text']
                            metadata.update(result['metadata'])
                        except Exception as e:
                            logger.error(f"OCRmyPDF fallback failed, using original extraction: {e}")
            elif ext == '.epub':
                result = self.epub_extractor.extract(file_path)
                text = result['text']
                metadata.update(result['metadata'])
            elif ext in ['.png', '.jpg', '.jpeg', '.tiff']:
                result = self.image_extractor.extract(file_path)
                text = result['text']
                metadata.update(result['metadata'])
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()

            # Select chunker based on extension
            chunker = self._get_chunker(ext, corpus_config)

            # Chunk the text
            chunks = chunker.chunk(text, metadata)
            logger.info(f"Generated {len(chunks)} chunks.")

            if not chunks:
                logger.warning(f"No text extracted for {file_path}")
                self._record_failure(file_path, corpus_id, current_hash, "No text extracted")
                if run_logger:
                    run_logger(f"FILE FAILED corpus={corpus_id} path={file_path} reason=No text extracted")
                return "failed"

            # Embed chunks
            chunk_texts = [c['content'] for c in chunks]
            start_time = time.time()
            embeddings = embedder.embed(chunk_texts)
            logger.info(f"Embedded {len(embeddings)} chunks in {time.time() - start_time:.2f}s")

            if not embeddings:
                logger.warning(f"No embeddings generated for {file_path}")
                if run_logger:
                    run_logger(f"FILE FAILED corpus={corpus_id} path={file_path} reason=No embeddings generated")
                return "failed"

            actual_dim = len(embeddings[0])
            expected_dim = self.config.vector_db.vector_size

            if expected_dim is not None:
                if actual_dim != expected_dim:
                    error_msg = f"Dimension mismatch: embedding is {actual_dim}, but config expects {expected_dim}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            else:
                # If null, we use the inferred actual_dim.
                # (In a larger setup, we could persist it to config/state, but passing it to qdrant is enough)
                expected_dim = actual_dim

            # Build vector payloads
            vectors_payload = []
            for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
                chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{current_hash}:{i}"))

                payload = dict(chunk.get('metadata', {}))
                payload['text'] = chunk['content']
                payload['file_hash'] = current_hash
                payload['file_name'] = os.path.basename(file_path)
                payload['corpus_id'] = corpus_id

                vectors_payload.append({
                    "id": chunk_id,
                    "vector": vector,
                    "payload": payload
                })

            # Upsert to vector DB
            self.vector_service.upsert_chunks(
                corpus_id=corpus_id,
                chunks=vectors_payload,
                vector_size=expected_dim,
                on_disk=self.config.vector_db.on_disk,
                hnsw_on_disk=self.config.vector_db.hnsw_on_disk
            )

            # Record success
            self._record_success(file_path, corpus_id, current_hash)
            logger.info(f"Successfully ingested {file_path}")
            if run_logger:
                run_logger(
                    f"FILE SUCCESS corpus={corpus_id} path={file_path} "
                    f"chunks={len(chunks)} vectors={len(vectors_payload)}"
                )
            return "processed"

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            try:
                self._record_failure(file_path, corpus_id, hash_file(file_path), str(e))
            except Exception as record_err:
                # Log the error when recording failure, but don't fail the overall process
                logger.warning(f"Failed to record failure for {file_path}: {record_err}")
            if run_logger:
                run_logger(f"FILE FAILED corpus={corpus_id} path={file_path} reason={e}")
            return "failed"

    def _record_success(self, file_path: str, corpus_id: str, file_hash: str) -> None:
        """Record successful file processing."""
        with self.db.cursor() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO files
                (file_hash, file_path, corpus_id, size_bytes, last_modified, status, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'SUCCESS', CURRENT_TIMESTAMP)
            """, (file_hash, file_path, corpus_id, os.path.getsize(file_path)))

    def _record_failure(self, file_path: str, corpus_id: str, file_hash: str, error: str) -> None:
        """Record failed file processing."""
        with self.db.cursor() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO files
                (file_hash, file_path, corpus_id, size_bytes, last_modified, status, last_error, failure_count, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'FAILED', ?,
                    COALESCE((SELECT failure_count FROM files WHERE file_hash = ?), 0) + 1,
                    CURRENT_TIMESTAMP)
            """, (file_hash, file_path, corpus_id, os.path.getsize(file_path), error, file_hash))
