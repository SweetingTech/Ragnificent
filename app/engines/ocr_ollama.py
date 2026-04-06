"""
Ollama OCR engine implementation.

Uses a vision-capable Ollama model, such as GLM-OCR, to turn page images into
text. Falls back to Tesseract when the Ollama runner is unavailable.
"""
import os
import tempfile
from pathlib import Path
from typing import Optional

import fitz
from ollama import Client

from .ocr_base import OCREngine
from ..config.schema import GlobalConfig
from ..utils.logging import setup_logging

logger = setup_logging()

OCR_ZOOM_FACTOR = 2


class OllamaOCREngine(OCREngine):
    """OCR engine backed by a vision-capable Ollama model."""

    def __init__(
        self,
        config: GlobalConfig,
        fallback_engine: Optional[OCREngine] = None,
    ):
        ocr_config = config.ocr.ollama
        if ocr_config is None:
            raise ValueError("OCR backend is set to Ollama but ocr.ollama is missing.")

        self.base_url = ocr_config.base_url
        self.model = ocr_config.model
        self.prompt = ocr_config.prompt
        self._client = Client(host=self.base_url)
        self._fallback_engine = fallback_engine

    def _generate(self, image_path: str) -> str:
        response = self._client.generate(
            model=self.model,
            prompt=self.prompt,
            images=[image_path],
            stream=False,
        )
        text = response.get("response", "")
        return text.strip()

    def _fallback_bytes(self, image_data: bytes, error: Exception) -> str:
        if self._fallback_engine is None:
            raise error
        logger.warning(
            "Ollama OCR failed, falling back to %s: %s",
            self._fallback_engine.__class__.__name__,
            error,
        )
        return self._fallback_engine.extract_text(image_data)

    def _fallback_file(self, file_path: str, error: Exception) -> str:
        if self._fallback_engine is None:
            raise error
        logger.warning(
            "Ollama OCR failed on %s, falling back to %s: %s",
            file_path,
            self._fallback_engine.__class__.__name__,
            error,
        )
        return self._fallback_engine.extract_file(file_path)

    def extract_text(self, image_data: bytes) -> str:
        fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            with open(temp_path, "wb") as handle:
                handle.write(image_data)
            try:
                return self._generate(temp_path)
            except Exception as exc:
                return self._fallback_bytes(image_data, exc)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def extract_file(self, file_path: str) -> str:
        suffix = Path(file_path).suffix.lower()

        if suffix != ".pdf":
            try:
                return self._generate(file_path)
            except Exception as exc:
                return self._fallback_file(file_path, exc)

        doc = None
        try:
            doc = fitz.open(file_path)
            pages = []
            for page_num, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(OCR_ZOOM_FACTOR, OCR_ZOOM_FACTOR))
                img_data = pix.tobytes("png")
                page_text = self.extract_text(img_data)
                logger.info(
                    "Ollama OCR extracted %s chars from PDF page %s",
                    len(page_text),
                    page_num,
                )
                pages.append(page_text)
            return "\n\n".join(pages)
        except Exception as exc:
            return self._fallback_file(file_path, exc)
        finally:
            if doc is not None:
                doc.close()
