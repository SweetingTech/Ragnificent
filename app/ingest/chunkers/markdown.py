"""
Markdown-aware text chunker.
Splits text into chunks by headings while respecting size limits, merging small
sections, and falling back to paragraph chunking when structure is absent.
Preserves page/source metadata.
"""
from typing import List, Dict, Any, Optional, Tuple
import re

# Constants
DEFAULT_MAX_TOKENS = 700
DEFAULT_OVERLAP_TOKENS = 80
MIN_TOKENS_PER_CHUNK = 100
WORDS_TO_TOKENS_RATIO = 1.3  # Approximate ratio of words to tokens


class MarkdownChunker:
    """
    Chunker that splits markdown text based on headers, merging small sections.
    """

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        min_tokens: int = MIN_TOKENS_PER_CHUNK
    ):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_tokens = min_tokens

        # Regex to match Markdown headings (e.g. "# Heading", "## Subheading")
        self.heading_pattern = re.compile(r'^(#{1,6})\s+(.*)$', re.MULTILINE)

    def _estimate_tokens(self, text: str) -> float:
        """Estimate the number of tokens in text."""
        if not text:
            return 0
        word_count = len(text.split())
        return word_count * WORDS_TO_TOKENS_RATIO

    def _split_into_sections(self, text: str) -> List[Dict[str, Any]]:
        """Split text by markdown headers."""
        sections = []

        # Find all headings
        matches = list(self.heading_pattern.finditer(text))

        if not matches:
            # No headings, return single section
            return [{"title": None, "content": text.strip(), "level": 0}]

        # Handle text before first heading
        if matches[0].start() > 0:
            pre_text = text[:matches[0].start()].strip()
            if pre_text:
                sections.append({"title": None, "content": pre_text, "level": 0})

        # Handle each heading block
        for i, match in enumerate(matches):
            level = len(match.group(1))
            title = match.group(2).strip()

            start_pos = match.end()
            end_pos = matches[i+1].start() if i + 1 < len(matches) else len(text)

            content = text[start_pos:end_pos].strip()
            # Include the heading itself in the content for context
            full_content = match.group(0) + ("\n\n" + content if content else "")

            sections.append({
                "title": title,
                "level": level,
                "content": full_content
            })

        return sections

    def _estimate_tokens_from_text(self, text: str) -> float:
        return self._estimate_tokens(text)

    def _chunk_large_section(self, section: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fallback to paragraph chunking for a single large section.
        Uses `self.min_tokens` to merge adjacent small chunks so that each
        resulting chunk meets a minimum estimated token count.
        """
        from .pdf_sections import PdfSectionChunker
        paragraph_chunker = PdfSectionChunker(
            max_tokens=self.max_tokens,
            overlap_tokens=self.overlap_tokens
        )

        # We don't pass metadata here, we'll attach it later
        raw_chunks = paragraph_chunker.chunk(section["content"])

        # Merge adjacent small chunks to respect the minimum token threshold.
        merged_contents: List[str] = []
        current_content_parts: List[str] = []

        for rc in raw_chunks:
            chunk_text = rc.get("content", "")
            if not chunk_text:
                continue

            if not current_content_parts:
                current_content_parts.append(chunk_text)
                continue

            tentative = "\n\n".join(current_content_parts + [chunk_text])
            if self._estimate_tokens(tentative) < self.min_tokens:
                current_content_parts.append(chunk_text)
            else:
                merged_contents.append("\n\n".join(current_content_parts))
                current_content_parts = [chunk_text]

        if current_content_parts:
            merged_contents.append("\n\n".join(current_content_parts))

        return [{
            "title": section["title"],
            "level": section["level"],
            "content": content
        } for content in merged_contents]

    def chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Split text into chunks by headings.
        """
        if not text or not text.strip():
            return []

        base_metadata = dict(metadata) if metadata else {}

        # 1. Split into natural sections
        raw_sections = self._split_into_sections(text)

        # 2. Merge small sections and split large ones
        processed_sections = []
        current_merged = None
        current_tokens = 0

        for section in raw_sections:
            sec_tokens = self._estimate_tokens(section["content"])

            # If section is too large, process what we have, then chunk this section
            if sec_tokens > self.max_tokens:
                if current_merged:
                    processed_sections.append(current_merged)
                    current_merged = None
                    current_tokens = 0

                sub_chunks = self._chunk_large_section(section)
                processed_sections.extend(sub_chunks)
                continue

            # If section is small, try to merge
            if current_merged:
                if current_tokens + sec_tokens <= self.max_tokens:
                    # Merge
                    current_merged["content"] += "\n\n" + section["content"]
                    # Update title only if it's logically grouped (e.g. keeping highest level)
                    # For simplicity, we just keep the title of the first section in the merged block
                    current_tokens += sec_tokens
                else:
                    # Flush and start new
                    processed_sections.append(current_merged)
                    current_merged = dict(section)
                    current_tokens = sec_tokens
            else:
                current_merged = dict(section)
                current_tokens = sec_tokens

        if current_merged:
            processed_sections.append(current_merged)

        # 3. Build final output with metadata
        final_chunks = []
        for i, sec in enumerate(processed_sections):
            chunk_metadata = dict(base_metadata)
            chunk_metadata["chunk_index"] = i
            if sec["title"]:
                chunk_metadata["section_title"] = sec["title"]

            final_chunks.append({
                "content": sec["content"],
                "token_count": int(self._estimate_tokens(sec["content"])),
                "metadata": chunk_metadata
            })

        return final_chunks
