# RAG Librarian (Custodian)

A local-first "Librarian" service that ingests documents from themed folders (corpora), deduplicates them by content hash, extracts text, chunks intelligently, embeds, and stores everything in a persistent vector index (Qdrant) for retrieval with citations.

## Features

- **Local-first**: Designed for on-prem usage.
- **Idempotent Ingestion**: Skips duplicates, handles incremental updates.
- **Lane-based Extraction**: Native PDF or OCR (Tesseract/OCRmyPDF).
- **Persistent State**: SQLite tracking of every file and chunk.

## Requirements

- Python 3.11+
- Qdrant (via Docker recommended)
- Optional: Tesseract OCR, Ghostscript (for OCR features)

## Quickstart

### 1. Setup

Run the setup script to create folders and install dependencies:

```powershell
./scripts/windows/setup.ps1
```

### 2. Configure

Edit `config.yaml` to set your paths and provider settings.
Edit `rag_library/corpora/*/corpus.yaml` for corpus-specific settings.

### 3. Start Infrastructure

Start Qdrant using Docker:

```bash
docker-compose up -d qdrant
```

### 4. Initialize Database

```powershell
./scripts/windows/init_state_db.ps1
```

### 5. Run the Service

```powershell
./scripts/windows/run.ps1
```

The API will be available at `http://localhost:8008`.

## Folder Structure

- `app/`: Source code
- `rag_library/`: Default location for your documents (inbox) and database.
- `scripts/`: Helper scripts for Windows and Docker.

## Usage

Drop files into `rag_library/corpora/<corpus_id>/inbox` and run ingestion (API or script coming soon).
transcripts