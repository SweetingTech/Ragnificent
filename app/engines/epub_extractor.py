"""
EPUB document extractor.
"""
from typing import Dict, Any
import zipfile
import re
from xml.etree import ElementTree as ET
from .base import Extractor, ExtractionResult
from ..config.schema import GlobalConfig
from ..utils.logging import setup_logging

logger = setup_logging()

class EpubExtractor(Extractor):
    """Simple extractor for EPUB files without heavy dependencies."""

    def __init__(self, config: GlobalConfig):
        """
        Initialize the EPUB extraction engine.

        Args:
            config: Global configuration object
        """
        self.config = config

    def extract(self, file_path: str) -> ExtractionResult:
        """
        Extract text from an EPUB file.
        Uses a simple zip-based approach and naive HTML/XML tag stripping
        to avoid pulling in heavy HTML parsing dependencies if possible.
        """
        text_content = []
        try:
            with zipfile.ZipFile(file_path, 'r') as z:
                # Find content documents (usually .html or .xhtml)
                for name in z.namelist():
                    if name.endswith('.html') or name.endswith('.xhtml') or name.endswith('.xml'):
                        if 'META-INF' in name or name.endswith('container.xml'):
                            continue

                        # Read and decode the file
                        raw_data = z.read(name)
                        try:
                            content = raw_data.decode('utf-8')
                        except UnicodeDecodeError:
                            continue

                        # Extremely naive tag stripping for simple text extraction
                        # In a real-world scenario, you might want to preserve some structure
                        # or use a proper parser if it gets too complex, but keeping it simple as requested.
                        # Remove script/style blocks
                        content = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', content, flags=re.IGNORECASE | re.DOTALL)
                        # Extract heading context (basic)
                        content = re.sub(r'<(h[1-6])[^>]*>(.*?)</\1>', r'\n\n# \2\n\n', content, flags=re.IGNORECASE | re.DOTALL)
                        # Remove remaining tags
                        text = re.sub(r'<[^>]+>', ' ', content)
                        # Cleanup whitespace
                        text = re.sub(r'\s+', ' ', text).strip()

                        if text:
                            text_content.append(text)

        except Exception as e:
            logger.error(f"Failed to process EPUB {file_path}: {e}")
            raise

        full_text = "\n\n".join(text_content)

        metadata: Dict[str, Any] = {
            "source_type": "epub",
            "sections_extracted": len(text_content)
        }

        return {
            "text": full_text,
            "metadata": metadata
        }
