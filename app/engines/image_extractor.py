"""
Image extractor using OCR.
"""
from typing import Dict, Any, Optional
from .base import Extractor, ExtractionResult
from .ocr_base import OCREngine
from ..config.schema import GlobalConfig


class ImageExtractor(Extractor):
    """Extractor for image files (png, jpg, tiff)."""

    def __init__(self, config: GlobalConfig, ocr_engine: Optional[OCREngine] = None):
        """
        Initialize the image extractor.

        Args:
            config: Global configuration object
            ocr_engine: Optional OCREngine to use. Defaults to TesseractEngine lazily.
        """
        self.config = config

        if ocr_engine is not None:
            self.ocr_engine = ocr_engine
        else:
            from .ocr_tesseract import TesseractEngine
            self.ocr_engine = TesseractEngine()

    def extract(self, file_path: str) -> ExtractionResult:
        """
        Extract text from an image file using the OCR engine.
        """
        text = self.ocr_engine.extract_file(file_path)

        metadata: Dict[str, Any] = {
            "source_type": "image",
            "ocr_applied": True,
            "ocr_engine": self.ocr_engine.__class__.__name__
        }

        return {
            "text": text,
            "metadata": metadata
        }
