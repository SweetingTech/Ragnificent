import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

class PdfEngine:
    def __init__(self, config):
        self.config = config
        self.min_chars = config.ingest.ocr_trigger.get('min_chars_per_page', 200)
        
        # Check if Tesseract is available? 
        # Pytesseract usually lazy loads, but we can try/except during init or first run.

    def extract(self, file_path: str) -> str:
        """
        Extracts text from PDF.
        Iterates pages:
        1. Try native text extract.
        2. If len(text) < threshold, render page image -> OCR.
        3. Append to total text.
        """
        full_text = []
        try:
            doc = fitz.open(file_path)
            for page_num, page in enumerate(doc):
                # 1. Native Extraction
                text = page.get_text()
                
                # Check quality (heuristic: length)
                # Cleaning whitespace for count
                clean_text = text.strip().replace("\n", "").replace(" ", "")
                
                if len(clean_text) < self.min_chars:
                    logger.info(f"Page {page_num+1} has low text count ({len(clean_text)}). Attempting OCR...")
                    try:
                        # 2. OCR Fallback
                        # Zoom matrix for better resolution (2x)
                        mat = fitz.Matrix(2, 2)
                        pix = page.get_pixmap(matrix=mat)
                        
                        # Convert to PIL Image
                        img_data = pix.tobytes("png")
                        image = Image.open(io.BytesIO(img_data))
                        
                        # Run Tesseract
                        ocr_text = pytesseract.image_to_string(image)
                        
                        # Basic consolidation: If OCR gave us significantly more, use it. 
                        # Or just append it? Usually if native is empty, OCR is the truth.
                        # If native has garbage, OCR might be better.
                        # Simple logic: If native < threshold, USE OCR only.
                        text = ocr_text
                        
                        logger.info(f"OCR extracted {len(text)} chars from Page {page_num+1}.")
                    except Exception as e:
                        logger.error(f"OCR failed for page {page_num+1}: {e}")
                        # Fallback to whatever native gave us (even if empty)
                
                full_text.append(text)
                
            doc.close()
        except Exception as e:
            logger.error(f"Failed to open PDF {file_path}: {e}")
            raise e

        # Join pages with generic separator or just newlines
        full_text_str = "\n\n".join(full_text)
        
        # Basic metadata
        metadata = {
            "page_count": len(full_text),
            "ocr_applied": any(len(p) > 0 and "OCR extracted" in str(p) for p in full_text) # Rough check or we track flag
        }
        
        return {
            "text": full_text_str,
            "metadata": metadata
        }
