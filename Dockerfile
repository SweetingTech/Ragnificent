FROM python:3.11-slim

# Install system dependencies for OCR and PDF processing
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    ghostscript \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install poetry or use pip. The template uses pyproject.toml but implies direct usage or maybe pip.
# I'll stick to pip install from pyproject.toml or requirements. 
# Since I made a pyproject.toml, I'll use poetry or just pip install .
# To keep it simple and robust:
COPY pyproject.toml .
RUN pip install "poetry-core>=1.0.0"
RUN pip install .

# Copy application code
COPY app /app/app
COPY scripts /app/scripts

# Default command
CMD ["python", "-m", "app.cli", "serve"]
