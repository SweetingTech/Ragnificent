"""
PDF section-based text chunker with overlap support.
Splits text into chunks by paragraphs while respecting token limits.
"""
from typing import List, Dict, Any, Optional

# Constants
DEFAULT_MAX_TOKENS = 700
DEFAULT_OVERLAP_TOKENS = 80
WORDS_TO_TOKENS_RATIO = 1.3  # Approximate ratio of words to tokens


class PdfSectionChunker:
    """
    Chunker that splits text into sections based on paragraphs.

    Supports configurable maximum chunk size and overlap between chunks
    for better context preservation during retrieval.
    """

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS
    ):
        """
        Initialize the chunker.

        Args:
            max_tokens: Maximum number of tokens per chunk
            overlap_tokens: Number of tokens to overlap between chunks
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def _estimate_tokens(self, text: str) -> float:
        """
        Estimate the number of tokens in text.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        word_count = len(text.split())
        return word_count * WORDS_TO_TOKENS_RATIO

    def _calculate_overlap_paragraphs(
        self,
        paragraphs: List[str],
        target_tokens: int
    ) -> List[str]:
        """
        Calculate how many paragraphs to keep for overlap.

        Args:
            paragraphs: List of paragraphs from previous chunk
            target_tokens: Target number of overlap tokens

        Returns:
            List of paragraphs to include in overlap
        """
        if not paragraphs or target_tokens <= 0:
            return []

        overlap_paras = []
        overlap_tokens = 0

        # Work backwards through paragraphs to build overlap
        for para in reversed(paragraphs):
            para_tokens = self._estimate_tokens(para)
            if overlap_tokens + para_tokens <= target_tokens:
                overlap_paras.insert(0, para)
                overlap_tokens += para_tokens
            else:
                break

        return overlap_paras

    def chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Split text into chunks with overlap.

        Args:
            text: The text to chunk
            metadata: Optional metadata to include with each chunk

        Returns:
            List of chunk dictionaries with 'content', 'token_count', and 'metadata' keys
        """
        if not text or not text.strip():
            return []

        # Split by double newlines (paragraphs)
        paragraphs = [p for p in text.split('\n\n') if p.strip()]

        if not paragraphs:
            return []

        chunks = []
        current_chunk: List[str] = []
        current_tokens = 0.0
        chunk_index = 0

        for para in paragraphs:
            para_tokens = self._estimate_tokens(para)

            # Check if adding this paragraph would exceed the limit
            if current_tokens + para_tokens > self.max_tokens and current_chunk:
                # Flush the current chunk
                chunk_text = "\n\n".join(current_chunk)
                chunk_metadata = dict(metadata) if metadata else {}
                chunk_metadata['chunk_index'] = chunk_index

                chunks.append({
                    "content": chunk_text,
                    "token_count": int(current_tokens),
                    "metadata": chunk_metadata
                })
                chunk_index += 1

                # Calculate overlap - keep some paragraphs from the end
                overlap_paras = self._calculate_overlap_paragraphs(
                    current_chunk,
                    self.overlap_tokens
                )

                # Start new chunk with overlap
                current_chunk = overlap_paras.copy()
                current_tokens = sum(self._estimate_tokens(p) for p in current_chunk)

            current_chunk.append(para)
            current_tokens += para_tokens

        # Don't forget the last chunk
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunk_metadata = dict(metadata) if metadata else {}
            chunk_metadata['chunk_index'] = chunk_index

            chunks.append({
                "content": chunk_text,
                "token_count": int(current_tokens),
                "metadata": chunk_metadata
            })

        return chunks
