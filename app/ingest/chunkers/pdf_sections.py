from typing import List, Dict, Any
import re

class PdfSectionChunker:
    def __init__(self, max_tokens=700, overlap_tokens=80):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, text: str, metadata: Dict = None) -> List[Dict]:
        """
        Splits text into chunks respecting section headers if possible.
        For V1, we implement a simple sliding window + paragraph split fallback.
        """
        # Simple paragraph splitting for now
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_length = 0
        
        for para in paragraphs:
            # layout estimate: 1 char ~= 0.25 token (rough)
            # better: simple word count / 0.75
            token_est = len(para.split()) * 1.3 
            
            if current_length + token_est > self.max_tokens:
                # Flush
                chunk_text = "\n\n".join(current_chunk)
                chunks.append({
                    "content": chunk_text,
                    "token_count": int(current_length),
                    "metadata": metadata or {}
                })
                # Overlap logic (keep last N paragraphs?) - Simplified: clear
                current_chunk = []
                current_length = 0
            
            current_chunk.append(para)
            current_length += token_est
            
        if current_chunk:
            chunks.append({
                "content": "\n\n".join(current_chunk),
                "token_count": int(current_length),
                "metadata": metadata or {}
            })
            
        return chunks
