import pytest
import os
import zipfile
import tempfile
from app.engines.epub_extractor import EpubExtractor
from app.engines.image_extractor import ImageExtractor
from app.ingest.chunkers.markdown import MarkdownChunker
from app.providers.ollama import OllamaProvider
from app.engines.ocr_base import OCREngine
from unittest.mock import Mock, patch

class DummyConfig:
    pass

class DummyOCREngine(OCREngine):
    def extract_text(self, image_data):
        return "Mocked OCR text from bytes"
    def extract_file(self, file_path):
        return "Mocked OCR text from file"

def test_markdown_chunker_metadata():
    # Set max_tokens very low to force a split so we can verify metadata is passed to chunks
    chunker = MarkdownChunker(max_tokens=5)
    text = "# Main Title\n\nSome paragraph.\n\n## Subtitle\n\nMore detailed info here."
    base_meta = {"source_path": "doc.md", "corpus_id": "test"}

    chunks = chunker.chunk(text, metadata=base_meta)
    assert len(chunks) >= 2

    # Check first chunk metadata
    assert chunks[0]["metadata"]["chunk_index"] == 0
    assert chunks[0]["metadata"]["section_title"] == "Main Title"
    assert chunks[0]["metadata"]["source_path"] == "doc.md"
    assert chunks[0]["metadata"]["corpus_id"] == "test"

def test_markdown_chunker_merging():
    # Set tiny max_tokens to force chunking, but large enough to merge small ones
    chunker = MarkdownChunker(max_tokens=500)
    text = "# A\n\nShort.\n\n# B\n\nAlso short."

    chunks = chunker.chunk(text)
    # The two small sections should be merged if they fit in 500 tokens
    assert len(chunks) == 1
    assert "Short." in chunks[0]["content"]
    assert "Also short." in chunks[0]["content"]

def test_epub_extraction():
    # Create a dummy epub file
    fd, epub_path = tempfile.mkstemp(suffix=".epub")
    os.close(fd)

    try:
        with zipfile.ZipFile(epub_path, 'w') as z:
            z.writestr("OEBPS/content.html", "<html><body><h1>Chapter 1</h1><p>This is a test.</p></body></html>")

        extractor = EpubExtractor(DummyConfig())
        result = extractor.extract(epub_path)

        # Checking that our naive extraction removed tags and kept text
        assert "Chapter 1" in result["text"]
        assert "This is a test." in result["text"]
        assert result["metadata"]["source_type"] == "epub"
    finally:
        os.unlink(epub_path)

def test_image_routing_and_ocr():
    extractor = ImageExtractor(DummyConfig(), ocr_engine=DummyOCREngine())

    result = extractor.extract("fake_image.png")
    assert result["text"] == "Mocked OCR text from file"
    assert result["metadata"]["source_type"] == "image"
    assert result["metadata"]["ocr_applied"] is True

@patch('app.providers.ollama.Client')
def test_batch_embedding(mock_client_class):
    mock_instance = Mock()
    mock_response = Mock()
    # Mock returning exactly 2 embeddings (lists of floats)
    mock_response.embeddings = [[0.1, 0.2], [0.3, 0.4]]
    mock_instance.embed.return_value = mock_response
    mock_client_class.return_value = mock_instance

    provider = OllamaProvider()

    # Send a batch of two texts
    texts = ["text1", "text2"]
    res = provider.embed(texts)

    # Check if the mock instance was called with the array
    mock_instance.embed.assert_called_once_with(model="nomic-embed-text", input=["text1", "text2"])

    # Validate result
    assert len(res) == 2
    assert res[0] == [0.1, 0.2]
    assert res[1] == [0.3, 0.4]
