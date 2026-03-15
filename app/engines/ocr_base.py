"""
Base interfaces for OCR engines.
"""
from typing import Optional
from abc import ABC, abstractmethod


class OCREngine(ABC):
    """Base interface for all OCR engines."""

    @abstractmethod
    def extract_text(self, image_data: bytes) -> str:
        """
        Extract text from raw image data.

        Args:
            image_data: Raw bytes of the image

        Returns:
            Extracted text
        """
        pass

    @abstractmethod
    def extract_file(self, file_path: str) -> str:
        """
        Extract text directly from an image file.

        Args:
            file_path: Path to the image file

        Returns:
            Extracted text
        """
        pass
