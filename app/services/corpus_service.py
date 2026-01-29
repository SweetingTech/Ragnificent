"""
Corpus service for managing corpus operations with proper validation.
Consolidates duplicate get_corpora() logic and adds security measures.
"""
from typing import List, Dict, Optional
from pathlib import Path
import yaml
import re
import os

from ..utils.logging import setup_logging

logger = setup_logging()

# Constants for validation
CORPUS_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
MAX_CORPUS_ID_LENGTH = 64


class CorpusValidationError(Exception):
    """Raised when corpus validation fails."""
    pass


def validate_corpus_id(corpus_id: str) -> bool:
    """
    Validates a corpus_id to prevent path traversal and injection attacks.

    Args:
        corpus_id: The corpus identifier to validate

    Returns:
        True if valid

    Raises:
        CorpusValidationError: If validation fails
    """
    if not corpus_id:
        raise CorpusValidationError("Corpus ID cannot be empty")

    if len(corpus_id) > MAX_CORPUS_ID_LENGTH:
        raise CorpusValidationError(f"Corpus ID exceeds maximum length of {MAX_CORPUS_ID_LENGTH}")

    if not CORPUS_ID_PATTERN.match(corpus_id):
        raise CorpusValidationError("Corpus ID must contain only alphanumeric characters, underscores, and hyphens")

    # Additional path traversal checks
    if '..' in corpus_id or corpus_id.startswith('/') or corpus_id.startswith('\\'):
        raise CorpusValidationError("Corpus ID contains invalid path characters")

    return True


def sanitize_yaml_string(value: str) -> str:
    """
    Sanitizes a string value for safe YAML output.

    Args:
        value: The string to sanitize

    Returns:
        Sanitized string safe for YAML
    """
    if not isinstance(value, str):
        return str(value)

    # Remove control characters except newlines and tabs
    sanitized = ''.join(char for char in value if char == '\n' or char == '\t' or (ord(char) >= 32))

    return sanitized


class CorpusService:
    """Service for managing corpus operations."""

    def __init__(self, library_root: str):
        """
        Initialize the corpus service.

        Args:
            library_root: Root path to the library (e.g., rag_library)
        """
        self.library_root = Path(library_root)
        self.corpora_path = self.library_root / "corpora"

    def get_corpus_path(self, corpus_id: str) -> Path:
        """
        Get the validated path for a corpus.

        Args:
            corpus_id: The corpus identifier

        Returns:
            Path object to the corpus directory

        Raises:
            CorpusValidationError: If corpus_id is invalid
        """
        validate_corpus_id(corpus_id)
        corpus_path = self.corpora_path / corpus_id

        # Resolve and verify the path stays within corpora directory
        resolved = corpus_path.resolve()
        corpora_resolved = self.corpora_path.resolve()

        # Use path-aware containment check instead of string prefix
        try:
            resolved.relative_to(corpora_resolved)
        except ValueError:
            raise CorpusValidationError("Invalid corpus path - path traversal detected")

        return corpus_path

    def corpus_exists(self, corpus_id: str) -> bool:
        """
        Check if a corpus exists.

        Args:
            corpus_id: The corpus identifier

        Returns:
            True if corpus exists and has valid configuration
        """
        try:
            corpus_path = self.get_corpus_path(corpus_id)
            return corpus_path.is_dir() and (corpus_path / "corpus.yaml").exists()
        except CorpusValidationError:
            return False

    def get_corpus_metadata(self, corpus_id: str) -> Optional[Dict]:
        """
        Get metadata for a specific corpus.

        Args:
            corpus_id: The corpus identifier

        Returns:
            Dictionary with corpus metadata or None if not found
        """
        try:
            corpus_path = self.get_corpus_path(corpus_id)
            config_path = corpus_path / "corpus.yaml"

            if not config_path.exists():
                return None

            with open(config_path) as f:
                meta = yaml.safe_load(f)

            return {
                "corpus_id": meta.get("corpus_id", corpus_id),
                "description": meta.get("description", ""),
                "source_path": meta.get("source_path"),
                "inbox_path": str((corpus_path / "inbox").resolve()),
                "config": meta
            }
        except (CorpusValidationError, Exception) as e:
            logger.error(f"Failed to load corpus metadata for {corpus_id}: {e}")
            return None

    def get_all_corpora(self) -> List[Dict]:
        """
        Get all available corpora.

        Returns:
            List of corpus metadata dictionaries
        """
        corpora = []

        if not self.corpora_path.exists():
            return corpora

        for directory in self.corpora_path.iterdir():
            if not directory.is_dir():
                continue

            corpus_id = directory.name

            # Skip invalid corpus IDs
            try:
                validate_corpus_id(corpus_id)
            except CorpusValidationError:
                logger.warning(f"Skipping invalid corpus directory: {corpus_id}")
                continue

            metadata = self.get_corpus_metadata(corpus_id)
            if metadata:
                corpora.append(metadata)

        return corpora

    def create_corpus(
        self,
        corpus_id: str,
        description: str,
        source_path: str,
        llm_model: str = "llama3",
        llm_provider: str = "ollama"
    ) -> Path:
        """
        Create a new corpus with directory structure and configuration.

        Args:
            corpus_id: Unique identifier for the corpus
            description: Human-readable description
            source_path: Path to source documents
            llm_model: LLM model to use for answers
            llm_provider: LLM provider name

        Returns:
            Path to the created corpus directory

        Raises:
            CorpusValidationError: If validation fails
        """
        validate_corpus_id(corpus_id)

        corpus_path = self.get_corpus_path(corpus_id)
        inbox_path = corpus_path / "inbox"

        # Create directory structure
        os.makedirs(inbox_path, exist_ok=True)

        # Sanitize user inputs
        safe_description = sanitize_yaml_string(description)
        safe_source_path = sanitize_yaml_string(source_path)

        # Create corpus.yaml with sanitized values
        config_content = {
            "corpus_id": corpus_id,
            "description": safe_description,
            "source_path": safe_source_path,
            "retain_on_missing": True,
            "models": {
                "answer": {
                    "provider": llm_provider,
                    "model": llm_model
                }
            },
            "chunking": {
                "default": {
                    "strategy": "pdf_sections",
                    "max_tokens": 700,
                    "overlap_tokens": 80
                }
            }
        }

        config_path = corpus_path / "corpus.yaml"
        with open(config_path, "w") as f:
            # Use safe_dump to keep YAML in safe subset
            yaml.safe_dump(config_content, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Created corpus: {corpus_id} at {corpus_path}")

        return corpus_path
