from typing import List, Dict

class CodeSymbolChunker:
    def __init__(self, max_tokens=900, overlap_tokens=0):
        self.max_tokens = max_tokens
        
    def chunk(self, text: str, metadata: Dict = None) -> List[Dict]:
        """
        Naive split by functions/classes for python.
        """
        lines = text.splitlines()
        chunks = []
        current_chunk = []
        
        for line in lines:
            # If line starts with 'def ' or 'class ', it's a potential break point
            if (line.startswith('def ') or line.startswith('class ')) and len("\n".join(current_chunk)) > 200:
                chunks.append({
                    "content": "\n".join(current_chunk),
                    "metadata": metadata
                })
                current_chunk = []
            current_chunk.append(line)
            
        if current_chunk:
            chunks.append({"content": "\n".join(current_chunk), "metadata": metadata})
            
        return chunks
