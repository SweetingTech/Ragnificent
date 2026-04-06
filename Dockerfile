FROM python:3.11-slim

# Install system dependencies for OCR and PDF processing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    libgl1 \
    libglib2.0-0 \
    ocrmypdf \
    qpdf \
    tesseract-ocr \
    unpaper \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY README.md pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY config.docker.yaml ./config.yaml
COPY embedding_presets.yaml models_catalog.yaml watcher.py ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "poetry-core>=1.9.0" \
    && pip install --no-cache-dir .

EXPOSE 8008

CMD ["python", "-m", "app.cli", "--config", "config.yaml", "serve"]
