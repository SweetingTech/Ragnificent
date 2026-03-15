"""
Base interfaces for document extraction.
"""
from typing import Dict, Any, TypedDict
from abc import ABC, abstractmethod


class ExtractionResult(TypedDict):
    """Type definition for extraction results."""
    text: str
    metadata: Dict[str, Any]


class Extractor(ABC):
    """Base interface for all document extractors."""

    @abstractmethod
    def extract(self, file_path: str) -> ExtractionResult:
        """
        Extract text and metadata from a file.

        Args:
            file_path: Path to the file to extract

        Returns:
            ExtractionResult dictionary with 'text' and 'metadata'
        """
        pass
