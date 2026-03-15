"""
Tesseract OCR engine implementation.
"""
import pytesseract
from PIL import Image
import io
from typing import Optional
from .ocr_base import OCREngine
from ..utils.logging import setup_logging

logger = setup_logging()

class TesseractEngine(OCREngine):
    """Engine for extracting text from images using Tesseract."""

    def extract_text(self, image_data: bytes) -> str:
        """
        Extract text from raw image data using Tesseract.
        """
        try:
            image = Image.open(io.BytesIO(image_data))
            text = pytesseract.image_to_string(image)
            return text
        except Exception as e:
            logger.error(f"Tesseract OCR failed on image bytes: {e}")
            raise

    def extract_file(self, file_path: str) -> str:
        """
        Extract text directly from an image file using Tesseract.
        """
        try:
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text
        except Exception as e:
            logger.error(f"Tesseract OCR failed on file {file_path}: {e}")
            raise
