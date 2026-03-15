"""
Document ingestion pipeline for processing and indexing documents.
Handles file scanning, extraction, chunking, embedding, and storage.
"""
from typing import Optional, List, Dict, Any
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
from ..providers.factory import get_embedding_provider
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
        from ..engines.ocr_tesseract import TesseractEngine
        from ..engines.ocr_my_pdf import OCRmyPDFEngine

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
            name=config.models.embeddings.provider,
            base_url=config.models.embeddings.base_url,
            model=config.models.embeddings.model
        )

        # Chunker registry
        self.chunkers = {
            "pdf_sections": PdfSectionChunker(),
            "code_symbols": CodeSymbolChunker(),
            "markdown": MarkdownChunker(),
            "default": PdfSectionChunker()
        }

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

    def run_once(self, corpus_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Run a single ingestion pass.

        Args:
            corpus_id: Optional specific corpus to process

        Returns:
            Summary of the ingestion run
        """
        logger.info(f"Starting ingestion run (corpus={corpus_id or 'all'})...")

        corpora = self._get_corpora(corpus_id)
        summary = {
            "corpora_processed": 0,
            "files_processed": 0,
            "files_skipped": 0,
            "files_failed": 0
        }

        for corpus in corpora:
            cid = corpus['id']
            scan_path = corpus.get('source_path') or corpus.get('inbox_path')

            logger.info(f"Scanning corpus: {cid} at {scan_path}")

            if not os.path.exists(scan_path):
                logger.warning(f"Path does not exist: {scan_path}")
                continue

            files = self._scan_files(scan_path)
            logger.info(f"Found {len(files)} candidates.")

            for file_path in files:
                result = self._process_file(file_path, cid)
                if result == "processed":
                    summary["files_processed"] += 1
                elif result == "skipped":
                    summary["files_skipped"] += 1
                else:
                    summary["files_failed"] += 1

            summary["corpora_processed"] += 1

        logger.info(f"Ingestion run complete. Summary: {summary}")
        return summary

    def _process_file(self, file_path: str, corpus_id: str) -> str:
        """
        Process a single file through the ingestion pipeline.

        Args:
            file_path: Path to the file
            corpus_id: ID of the corpus

        Returns:
            Status string: "processed", "skipped", or "failed"
        """
        try:
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
            chunker = self.chunkers['default']
            if ext == '.py':
                chunker = self.chunkers['code_symbols']
            elif ext == '.md' or ext == '.epub':
                chunker = self.chunkers['markdown']

            # Chunk the text
            chunks = chunker.chunk(text, metadata)
            logger.info(f"Generated {len(chunks)} chunks.")

            if not chunks:
                logger.warning(f"No text extracted for {file_path}")
                self._record_failure(file_path, corpus_id, current_hash, "No text extracted")
                return "failed"

            # Embed chunks
            chunk_texts = [c['content'] for c in chunks]
            start_time = time.time()
            embeddings = self.embedder.embed(chunk_texts)
            logger.info(f"Embedded {len(embeddings)} chunks in {time.time() - start_time:.2f}s")

            if not embeddings:
                logger.warning(f"No embeddings generated for {file_path}")
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
            return "processed"

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            try:
                self._record_failure(file_path, corpus_id, hash_file(file_path), str(e))
            except Exception as record_err:
                # Log the error when recording failure, but don't fail the overall process
                logger.warning(f"Failed to record failure for {file_path}: {record_err}")
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
