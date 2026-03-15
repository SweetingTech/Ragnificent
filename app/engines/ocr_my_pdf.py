"""
OCRmyPDF engine implementation.
Provides OCR functionality for PDF files, which is different from typical
image-to-text engines because OCRmyPDF creates a new PDF with a text layer.
"""
import subprocess
import tempfile
import os
import fitz
from typing import Optional
from .ocr_base import OCREngine
from ..config.schema import GlobalConfig
from ..utils.logging import setup_logging

logger = setup_logging()

class OCRmyPDFEngine(OCREngine):
    """Engine for processing files with OCRmyPDF."""

    def __init__(self, config: GlobalConfig):
        self.config = config
        self.ocr_config = config.ocr.ocrmypdf

    def extract_text(self, image_data: bytes) -> str:
        """
        Not directly supported by OCRmyPDF since it operates on files.
        We would need to write the bytes to a temp file, potentially convert
        to PDF, then run OCRmyPDF. For simplicity, we implement a naive fallback
        or raise an exception.
        """
        raise NotImplementedError("OCRmyPDF operates on PDF files, not raw image bytes.")

    def extract_file(self, file_path: str) -> str:
        """
        Extract text from a file (typically a PDF) using OCRmyPDF.
        Creates a temporary searchable PDF and extracts text from it.
        """
        if not file_path.lower().endswith(".pdf"):
            logger.warning(f"OCRmyPDF is optimized for PDFs, but got {file_path}")
            # If we were strictly supporting images, we'd use tesseract for images
            # or convert the image to PDF first. Since OCRmyPDF is mostly a PDF tool,
            # this implementation handles PDFs.

        fd, temp_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        try:
            # Build command
            cmd = ["ocrmypdf", "--force-ocr"]
            if self.ocr_config.language:
                cmd.extend(["-l", self.ocr_config.language])
            if self.ocr_config.deskew:
                cmd.append("--deskew")
            if self.ocr_config.rotate_pages:
                cmd.append("--rotate-pages")
            if self.ocr_config.clean:
                cmd.append("--clean")

            cmd.extend([file_path, temp_pdf])

            logger.info(f"Running OCRmyPDF on {file_path}")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"OCRmyPDF failed: {result.stderr}")
                raise RuntimeError(f"OCRmyPDF failed: {result.stderr}")

            # Now extract the text from the searchable PDF
            logger.info("Extracting text from OCR'd PDF")
            doc = fitz.open(temp_pdf)
            try:
                full_text = []
                for page in doc:
                    full_text.append(page.get_text())
                return "\n\n".join(full_text)
            finally:
                doc.close()

        finally:
            if os.path.exists(temp_pdf):
                os.unlink(temp_pdf)
