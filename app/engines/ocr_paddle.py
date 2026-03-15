"""
PaddleOCR engine implementation (Optional).
"""
import io
from typing import Optional
from .ocr_base import OCREngine
from ..utils.logging import setup_logging

logger = setup_logging()

class PaddleOCREngine(OCREngine):
    """Engine for extracting text from images using PaddleOCR."""

    def __init__(self, lang: str = "en"):
        try:
            from paddleocr import PaddleOCR
            # Initialize with standard options
            self.ocr = PaddleOCR(use_angle_cls=True, lang=lang)
        except ImportError:
            logger.error("PaddleOCR not installed. Install via `pip install paddleocr paddlepaddle`.")
            raise

    def extract_text(self, image_data: bytes) -> str:
        """
        Extract text from raw image data using PaddleOCR.
        """
        try:
            # We can use PIL or OpenCV, PaddleOCR supports numpy arrays or file paths
            import numpy as np
            import cv2

            # Convert bytes to numpy array
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            result = self.ocr.ocr(img, cls=True)

            text_lines = []
            if result and result[0]:
                for line in result[0]:
                    # line format: [[bbox], (text, confidence)]
                    text_lines.append(line[1][0])

            return "\n".join(text_lines)
        except Exception as e:
            logger.error(f"PaddleOCR failed on image bytes: {e}")
            raise

    def extract_file(self, file_path: str) -> str:
        """
        Extract text directly from an image file using PaddleOCR.
        """
        try:
            result = self.ocr.ocr(file_path, cls=True)

            text_lines = []
            if result and result[0]:
                for line in result[0]:
                    text_lines.append(line[1][0])

            return "\n".join(text_lines)
        except Exception as e:
            logger.error(f"PaddleOCR failed on file {file_path}: {e}")
            raise
