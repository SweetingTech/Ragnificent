import fitz  # PyMuPDF
from typing import Dict, Any, List

class PdfEngine:
    def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Returns {
            'text': str,
            'pages': [{'page': 1, 'text': '...'}, ...],
            'metadata': dict
        }
        """
        doc = fitz.open(file_path)
        pages_output = []
        full_text = []
        
        for i, page in enumerate(doc):
            text = page.get_text()
            full_text.append(text)
            pages_output.append({
                "page": i + 1,
                "text": text
            })
            
        return {
            "text": "\n".join(full_text),
            "pages": pages_output,
            "metadata": doc.metadata
        }
