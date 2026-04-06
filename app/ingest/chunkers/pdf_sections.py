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
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        max_chars: Optional[int] = None,
    ):
        """
        Initialize the chunker.

        Args:
            max_tokens: Maximum number of tokens per chunk
            overlap_tokens: Number of tokens to overlap between chunks
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.max_chars = max_chars

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

    def _max_words_per_chunk(self) -> int:
        return max(1, int(self.max_tokens / WORDS_TO_TOKENS_RATIO))

    def _overlap_words(self) -> int:
        if self.overlap_tokens <= 0:
            return 0
        return max(0, int(self.overlap_tokens / WORDS_TO_TOKENS_RATIO))

    def _split_large_block(self, text: str) -> List[str]:
        """
        Force-split a large block when paragraph boundaries are insufficient.

        This is the safety valve for PDFs that extract as one giant paragraph or
        otherwise exceed the embedding model's input window.
        """
        words = text.split()
        if not words:
            return []

        max_words = self._max_words_per_chunk()
        overlap_words = min(self._overlap_words(), max_words - 1) if max_words > 1 else 0
        chunks: List[str] = []
        current: List[str] = []

        for word in words:
            candidate_words = current + [word]
            candidate = " ".join(candidate_words)
            too_many_words = len(candidate_words) > max_words
            too_many_chars = self.max_chars is not None and len(candidate) > self.max_chars

            if current and (too_many_words or too_many_chars):
                chunks.append(" ".join(current))
                if overlap_words > 0:
                    current = current[-overlap_words:]
                    overlap_candidate = " ".join(current + [word])
                    if self.max_chars is not None and len(overlap_candidate) > self.max_chars:
                        current = []
                else:
                    current = []

            current.append(word)

        if current:
            chunks.append(" ".join(current))

        return chunks

    def _append_chunk(
        self,
        chunks: List[Dict[str, Any]],
        chunk_paragraphs: List[str],
        token_count: float,
        metadata: Optional[Dict[str, Any]],
        chunk_index: int,
    ) -> None:
        chunk_text = "\n\n".join(chunk_paragraphs)
        chunk_metadata = dict(metadata) if metadata else {}
        chunk_metadata["chunk_index"] = chunk_index
        chunks.append({
            "content": chunk_text,
            "token_count": int(token_count),
            "metadata": chunk_metadata,
        })

    def _enforce_max_chunk_size(
        self,
        chunks: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Final safety pass so no chunk leaves this chunker above max_tokens.
        """
        bounded: List[Dict[str, Any]] = []
        next_index = 0

        for chunk in chunks:
            content = chunk.get("content", "")
            token_count = self._estimate_tokens(content)
            within_token_limit = token_count <= self.max_tokens
            within_char_limit = self.max_chars is None or len(content) <= self.max_chars
            if within_token_limit and within_char_limit:
                chunk_metadata = dict(metadata) if metadata else {}
                chunk_metadata.update(
                    {
                        k: v
                        for k, v in chunk.get("metadata", {}).items()
                        if k != "chunk_index"
                    }
                )
                chunk_metadata["chunk_index"] = next_index
                bounded.append({
                    "content": content,
                    "token_count": int(token_count),
                    "metadata": chunk_metadata,
                })
                next_index += 1
                continue

            inherited_metadata = {
                k: v
                for k, v in chunk.get("metadata", {}).items()
                if k != "chunk_index"
            }
            merged_metadata = dict(metadata) if metadata else {}
            merged_metadata.update(inherited_metadata)
            for split_block in self._split_large_block(content):
                split_tokens = self._estimate_tokens(split_block)
                self._append_chunk(
                    bounded,
                    [split_block],
                    split_tokens,
                    merged_metadata,
                    next_index,
                )
                next_index += 1

        return bounded

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

            if para_tokens > self.max_tokens:
                if current_chunk:
                    self._append_chunk(chunks, current_chunk, current_tokens, metadata, chunk_index)
                    chunk_index += 1
                    current_chunk = []
                    current_tokens = 0.0

                for split_block in self._split_large_block(para):
                    split_tokens = self._estimate_tokens(split_block)
                    self._append_chunk(chunks, [split_block], split_tokens, metadata, chunk_index)
                    chunk_index += 1
                continue

            # Check if adding this paragraph would exceed the limit
            if current_tokens + para_tokens > self.max_tokens and current_chunk:
                self._append_chunk(chunks, current_chunk, current_tokens, metadata, chunk_index)
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
            self._append_chunk(chunks, current_chunk, current_tokens, metadata, chunk_index)

        return self._enforce_max_chunk_size(chunks, metadata)
