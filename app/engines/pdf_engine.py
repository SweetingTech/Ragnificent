"""
PDF extraction engine with OCR fallback support.
Uses PyMuPDF for native text extraction and Tesseract for OCR.
"""
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
from typing import Dict, Any, TypedDict
from ..utils.logging import setup_logging
from ..config.schema import GlobalConfig

logger = setup_logging()

# Constants
DEFAULT_MIN_CHARS_PER_PAGE = 200
OCR_ZOOM_FACTOR = 2  # 2x zoom for better OCR accuracy


class PdfExtractionResult(TypedDict):
    """Type definition for PDF extraction results."""
    text: str
    metadata: Dict[str, Any]


class PdfEngine:
    """Engine for extracting text from PDF documents with OCR fallback."""

    def __init__(self, config: GlobalConfig):
        """
        Initialize the PDF extraction engine.

        Args:
            config: Global configuration object
        """
        self.config = config
        self.min_chars = config.ingest.ocr_trigger.get(
            'min_chars_per_page',
            DEFAULT_MIN_CHARS_PER_PAGE
        )

    def extract(self, file_path: str) -> PdfExtractionResult:
        """
        Extract text from a PDF file.

        Iterates through pages and:
        1. Tries native text extraction first
        2. Falls back to OCR if text is below threshold
        3. Collects metadata about the extraction process

        Args:
            file_path: Path to the PDF file

        Returns:
            Dictionary with 'text' and 'metadata' keys

        Raises:
            Exception: If PDF cannot be opened or processed
        """
        full_text = []
        ocr_applied = False
        ocr_page_count = 0

        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)

            for page_num, page in enumerate(doc):
                # 1. Native Extraction
                text = page.get_text()

                # Check quality (heuristic: length of non-whitespace characters)
                clean_text = text.strip().replace("\n", "").replace(" ", "")

                if len(clean_text) < self.min_chars:
                    logger.info(
                        f"Page {page_num + 1}/{total_pages} has low text count "
                        f"({len(clean_text)} chars). Attempting OCR..."
                    )
                    ocr_result = self._extract_page_ocr(page, page_num + 1)
                    if ocr_result is not None:
                        text = ocr_result
                        ocr_applied = True
                        ocr_page_count += 1

                full_text.append(text)

            doc.close()

        except Exception as e:
            logger.error(f"Failed to open PDF {file_path}: {e}")
            raise

        # Join pages with double newlines
        full_text_str = "\n\n".join(full_text)

        # Build metadata with reliable tracking
        metadata: Dict[str, Any] = {
            "page_count": len(full_text),
            "ocr_applied": ocr_applied,
            "ocr_page_count": ocr_page_count,
            "source_type": "pdf"
        }

        return {
            "text": full_text_str,
            "metadata": metadata
        }

    def _extract_page_ocr(self, page, page_num: int) -> str | None:
        """
        Extract text from a page using OCR.

        Args:
            page: PyMuPDF page object
            page_num: Page number for logging

        Returns:
            Extracted text or None if OCR fails
        """
        try:
            # Zoom matrix for better resolution
            mat = fitz.Matrix(OCR_ZOOM_FACTOR, OCR_ZOOM_FACTOR)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img_data = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_data))

            # Run Tesseract OCR
            ocr_text = pytesseract.image_to_string(image)

            logger.info(f"OCR extracted {len(ocr_text)} chars from page {page_num}")
            return ocr_text

        except Exception as e:
            logger.error(f"OCR failed for page {page_num}: {e}")
            return None
