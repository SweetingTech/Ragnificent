"""
Tesseract OCR engine implementation.
"""
import io
import os
import shutil
from typing import Optional
from .ocr_base import OCREngine
from ..utils.logging import setup_logging

logger = setup_logging()


def _resolve_tesseract_cmd() -> Optional[str]:
    """
    Resolve the Tesseract executable path.

    On Windows, installers often place Tesseract in Program Files without
    updating PATH for already-running shells, so we probe the common install
    locations explicitly.
    """
    binary = shutil.which("tesseract")
    if binary:
        return binary

    if os.name != "nt":
        return None

    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def _load_tesseract_dependencies():
    """
    Lazily import pytesseract and Pillow's Image module.
    This avoids hard runtime dependencies when OCR functionality
    is unused or optional.
    """
    try:
        import pytesseract  # type: ignore[import]
        from PIL import Image  # type: ignore[import]
    except ImportError as exc:
        logger.error(
            "Missing OCR dependencies for TesseractEngine: %s. "
            "Install the 'pytesseract' and 'Pillow' packages to enable OCR.",
            exc,
        )
        raise RuntimeError(
            "Tesseract OCR dependencies are not installed. "
            "Install the 'pytesseract' and 'Pillow' packages to use this feature."
        ) from exc

    tesseract_cmd = _resolve_tesseract_cmd()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    else:
        logger.warning(
            "Tesseract executable was not found on PATH or in the default Windows install path."
        )
    return pytesseract, Image

class TesseractEngine(OCREngine):
    """Engine for extracting text from images using Tesseract."""

    def extract_text(self, image_data: bytes) -> str:
        """
        Extract text from raw image data using Tesseract.
        """
        try:
            pytesseract, Image = _load_tesseract_dependencies()
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
            pytesseract, Image = _load_tesseract_dependencies()
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text
        except Exception as e:
            logger.error(f"Tesseract OCR failed on file {file_path}: {e}")
            raise
