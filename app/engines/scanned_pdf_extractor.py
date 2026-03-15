"""
Scanned PDF Extractor.
Routes PDFs entirely through OCRmyPDF when they are known to be scanned,
or as configured.
"""
from typing import Dict, Any, Optional
from .base import Extractor, ExtractionResult
from .ocr_my_pdf import OCRmyPDFEngine
from ..config.schema import GlobalConfig

class ScannedPdfExtractor(Extractor):
    """Extractor for scanned PDF files using OCRmyPDF."""

    def __init__(self, config: GlobalConfig, ocr_engine: Optional[OCRmyPDFEngine] = None):
        """
        Initialize the scanned PDF extractor.

        Args:
            config: Global configuration object
            ocr_engine: Optional OCRmyPDFEngine to use.
        """
        self.config = config
        self.ocr_engine = ocr_engine or OCRmyPDFEngine(config)

    def extract(self, file_path: str) -> ExtractionResult:
        """
        Extract text from a scanned PDF using OCRmyPDF.
        """
        text = self.ocr_engine.extract_file(file_path)

        metadata: Dict[str, Any] = {
            "source_type": "pdf_scanned",
            "ocr_applied": True,
            "ocr_engine": self.ocr_engine.__class__.__name__
        }

        return {
            "text": text,
            "metadata": metadata
        }
