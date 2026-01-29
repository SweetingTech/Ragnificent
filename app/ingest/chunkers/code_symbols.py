"""
Code-aware chunker that splits by function and class definitions.
Designed for Python code but can be extended for other languages.
"""
from typing import List, Dict, Any, Optional

# Constants
DEFAULT_MAX_TOKENS = 900
MIN_CHUNK_SIZE_CHARS = 200  # Minimum chunk size before allowing split
SYMBOL_PREFIXES = ('def ', 'class ', 'async def ')  # Python symbol markers


class CodeSymbolChunker:
    """
    Chunker that splits code by function and class definitions.

    Attempts to keep logical code units together while respecting
    size constraints.
    """

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = 0
    ):
        """
        Initialize the chunker.

        Args:
            max_tokens: Maximum number of tokens per chunk (currently unused, kept for API compatibility)
            overlap_tokens: Number of tokens to overlap (currently unused, kept for API compatibility)
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def _is_symbol_start(self, line: str) -> bool:
        """
        Check if a line starts a new symbol (function/class).

        Args:
            line: Line of code to check

        Returns:
            True if line starts a symbol definition
        """
        stripped = line.lstrip()
        return any(stripped.startswith(prefix) for prefix in SYMBOL_PREFIXES)

    def chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Split code into chunks by symbol definitions.

        Args:
            text: The code text to chunk
            metadata: Optional metadata to include with each chunk

        Returns:
            List of chunk dictionaries with 'content' and 'metadata' keys
        """
        if not text or not text.strip():
            return []

        lines = text.splitlines()
        chunks = []
        current_chunk: List[str] = []
        chunk_index = 0

        for line in lines:
            # Check if this line starts a new symbol and we have enough content
            current_content = "\n".join(current_chunk)
            is_new_symbol = self._is_symbol_start(line)
            has_enough_content = len(current_content) > MIN_CHUNK_SIZE_CHARS

            if is_new_symbol and has_enough_content:
                # Flush current chunk
                chunk_metadata = dict(metadata) if metadata else {}
                chunk_metadata['chunk_index'] = chunk_index

                chunks.append({
                    "content": current_content,
                    "metadata": chunk_metadata
                })
                current_chunk = []
                chunk_index += 1

            current_chunk.append(line)

        # Don't forget the last chunk
        if current_chunk:
            chunk_metadata = dict(metadata) if metadata else {}
            chunk_metadata['chunk_index'] = chunk_index

            chunks.append({
                "content": "\n".join(current_chunk),
                "metadata": chunk_metadata
            })

        return chunks
