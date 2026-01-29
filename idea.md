# Ragnificent: Technical Specification

**Ragnificent** is a local-first **Intelligent Data Custodian**. It ingests documents from filesystem folders (librarians), deduplicates them, extracts knowledge (via native text or OCR), and serves them via a semantic search API and GUI.

---

## 1. Core Architecture

### 1.1 High-Level Data Flow
1. **Librarian (Corpus)**: A distinct configuration monitoring a local directory.
2. **Ingestion Pipeline**: Scan -> Hash -> Extract -> Chunk -> Embed -> Upsert.
3. **Storage**:
   - **Properties**: SQLite (File Metadata, Hashes, Status).
   - **Vectors**: Qdrant (Embeddings + Text Payload).
4. **Access**:
   - **Query Engine**: Embed Query -> Search Qdrant -> Rerank/Format -> LLM Answer.
   - **GUI**: HTMX/Jinja2 interface for management and chat.

### 1.2 Tech Stack
- **Language**: Python 3.11+
- **Web Fx**: FastAPI + Uvicorn
- **Frontend**: Jinja2 Templates + HTMX (Server-Side Rendering)
- **Vector DB**: Qdrant
- **OCR Engine**: Tesseract / OCRmyPDF
- **PDF Engine**: PyMuPDF (fitz)
- **Models**: Ollama (for both Embeddings and LLM Generation)

---

## 2. Ingestion System

The ingestion pipeline is idempotent and lane-based.

### 2.1 Pipeline Steps
1. **Scan**: Recursive detection of supported files (`.pdf`, `.md`, `.txt`, `.py`).
2. **Hash**: Calculate SHA-256 of file content.
   - *Check*: If hash matches SQLite `SUCCESS` record, skip.
3. **Extraction Lane**:
   - **PDF**: Attempt native text extraction.
     - *Heuristic*: If chars < `min_chars_per_page` (default 200), trigger **OCR Lane** (Tesseract) for that page.
   - **Text/Code**: Native read.
4. **Chunking**:
   - Files are split into `Chunk` objects with lineage metadata.
   - Strategies: `PdfSectionChunker`, `CodeSymbolChunker`, `RecursiveCharacter`.
5. **Embedding**: Batched generation using configured provider (Ollama `nomic-embed-text`).
6. **Persistence**:
   - Upsert vectors to Qdrant.
   - Update SQLite with file hash, timestamp, and status.

### 2.2 Configuration (`corpus.yaml`)
Each corpus is defined by a YAML file allowing localized overrides:
```yaml
corpus_id: cyber_blue
source_path: "D:/Books/CyberSecurity"
models:
  answer:
    provider: "ollama"
    model: "llama3"
chunking:
  default:
    strategy: "pdf_sections"
    max_tokens: 700
```

---

## 3. Query & Agent System

### 3.1 RAG Workflow
1. **Input**: User query + target `corpus_id`.
2. **Retrieval**:
   - Embed query.
   - Search Qdrant collection for `top_k` matches.
3. **Agent Resolution**:
   - System inspects `corpus.yaml` to determine the assigned "Librarian Persona" (LLM model).
   - If ad-hoc (no corpus), user-selected model is used.
4. **Generation**:
   - Construct prompt: `Context: {chunks} \n Question: {query}`.
   - Stream response from LLM Provider.

### 3.2 Dynamic Model Discovery
- The system dynamically queries the Ollama `/api/tags` endpoint to populate available models in the UI, allowing drop-in usage of new models without code changes.

---

## 4. API Specification

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ingest/run` | Trigger ingestion for a corpus (sync). |
| `POST` | `/api/query` | JSON Search API (returns hits + answer). |
| `GET` | `/gui/dashboard` | System health and corpus cards. |
| `GET` | `/gui/search` | Interactive Chat/RAG interface. |

---

## 5. Folder Structure

```text
Ragnificent/
  app/
    api/                # FastAPI Enpoints
    ingest/             # Pipeline, Lanes, Chunkers
    engines/            # PDF & OCR functionality (pdf_engine.py)
    providers/          # LLM & Embedding Adapters (ollama.py)
    vector/             # Qdrant Client
    gui/                # Templates & Routes
  rag_library/          # Data Root
    corpora/            # Corpus Definitions
    state/              # SQLite DBs
  config.yaml           # Global System Config
```

---

## 6. Future Roadmap (Post-V1)
- **API Security**: Implement API Key middleware.
- **Docker**: Full containerization of the Python service.
- **Advanced OCR**: Table extraction and layout analysis (LayoutLM).
- **Reranking**: Cross-encoder step for higher precision retrieval.

---

---

# 7. Project Build List (Full History & Roadmap)

This checklist tracks the end-to-end development of Ragnificent.

## Phase 0: Repo + Standards (Completed)
### Tasks
- [x] Create repo structure
- [x] Add Python packaging (pyproject.toml) & formatting
- [x] Add config loader with schema validation (Pydantic)

## Phase 1: Persistent State (Completed)
### Tasks
- [x] Implement SQLite schema and migrations
- [x] Implement ingestion lock to prevent overlapping runs
- [x] Implement dead-letter handling (Status tracking)
- [x] Implement inventory queries (StatsService)

## Phase 2: Vector DB (Completed)
### Tasks
- [x] Implement Qdrant client
- [x] Define deterministic Chunk IDs
- [x] Add collection naming strategy

## Phase 3: Extraction Engines (Completed)
### Tasks
- [x] Implement native PDF extraction (PyMuPDF)
- [x] Implement heuristics (OCR trigger on low text density)
- [x] Extract PDF metadata (title/author/date)

## Phase 4: OCR & Advanced Extraction (Completed)
### Tasks
- [x] Configure Tesseract integration
- [x] Implement hybrid pipeline ( PdfEngine: Native -> Check -> OCR)

## Phase 5: Chunking Strategies (Completed)
### Tasks
- [x] Implement basic chunkers (PDF Sections, Code Symbols)
- [x] Add per-corpus + per-extension overrides from `corpus.yaml`
- [x] Store chunk lineage metadata

## Phase 6: Model Providers (Completed)
### Tasks
- [x] Implement provider adapter interface
- [x] Implement providers:
    - [x] Ollama embeddings provider
    - [x] Ollama LLM provider (OllamaLLM for Answering)
- [x] Add dynamic model discovery (list_models)

## Phase 7: Ingestion Pipeline (Completed)
### Tasks
- [x] Implement `ingest_once` (File scanning logic)
- [x] Hash-based deduplication (Idempotency)
- [x] Persist state (SQLite tracking)
- [x] Upsert to vector DB (Qdrant)
- [x] “Retain-on-missing” policy

## Phase 8: API Layer (Completed)
### Tasks
- [x] Implement API endpoints (ingest, query, health)
- [x] Implement RAG Query Engine (Embed -> Search -> Answer)
- [x] Add per-corpus Agent resolution (Assign specific models to libraries)

## Phase 9: GUI (Completed)
### Tasks
- [x] Dashboard (Health, Inventory, Sync triggers)
- [x] Corpora view (Manage Corpus, Create New, Sync)
- [x] Ingest view (Real-time status via alerts/logging)
- [x] Search view (Conversational RAG + Ad-hoc Chat)
    - [x] Dynamic model dropdown
    - [x] RAG Citation display

---

## Phase 9.5: Code Review & Quality Hardening (Completed)

A comprehensive code review identified and addressed 33 issues across security, architecture, and code quality.

### Security Fixes
- [x] Path traversal vulnerability - corpus IDs validated with regex + `relative_to()` path checks
- [x] Global environment mutation - removed `os.environ["OLLAMA_HOST"]`, use explicit `Client(host=...)`
- [x] YAML injection - user inputs sanitized, using `yaml.safe_dump()` instead of `yaml.dump()`

### Architecture Improvements
- [x] Thread-safe SQLite - implemented thread-local storage pattern with WAL mode
- [x] Dependency injection - replaced module-level globals with FastAPI `Depends()` pattern
- [x] Async non-blocking - blocking I/O wrapped with `asyncio.to_thread()`
- [x] Centralized corpus service - `CorpusService` eliminates duplicate code

### Resource Management
- [x] Database lifecycle - generators with `finally` cleanup ensure connections close
- [x] PDF file handles - `try/finally` with explicit `doc.close()` prevents leaks
- [x] Collection caching - O(1) existence checks via `get_collection()` instead of O(n) list scan

### Code Quality
- [x] Removed unused imports across multiple files
- [x] Added logging to silent `except` blocks
- [x] Fixed Jinja template falsy checks (`chunk_index=0` issue)
- [x] Config caching - avoid repeated `load_config()` calls
- [x] Proper type hints and docstrings

### Verification
- [x] All syntax checks pass (`py_compile`)
- [x] Documented in `20260129_Changelog.md`

---

## Phase 10: Dockerization + Multi-instance (Pending)
### Tasks
- [ ] Create `Dockerfile` for the FastAPI service.
- [ ] Create `docker-compose.yml` orchestrating:
  - `qdrant` (Vector DB)
  - `librarian` (The Application)
- [ ] Implement environment configuration support:
  - `PORT`, `COLLECTION_PREFIX`, `LIBRARY_ROOT` overrides.
- [ ] Persistence Configuration:
  - Mount `/data/library` (Host content)
  - Mount `/data/state` (SQLite)

### Verification
- [ ] `docker compose up` starts both services.
- [ ] Data persists across container restarts.
- [ ] Multiple instances run on different ports without collision.

## Phase 11: Security & Hardening (Partial - In Progress)
### Completed (via Phase 9.5 Code Review)
- [x] Input validation - corpus IDs validated against strict patterns
- [x] Path traversal protection - resolved paths verified within allowed directories
- [x] Safe serialization - using `yaml.safe_dump()` for YAML output
- [x] Environment isolation - no global `os.environ` mutations

### Remaining Tasks
- [ ] Implement API Key middleware in `app/api/dependencies.py`.
- [ ] Add `.env` support for `ADMIN_API_KEY`.
- [ ] Secure the GUI (Basic Auth or Token-based).
- [ ] Add rate limiting for API endpoints.
- [ ] Implement request logging/audit trail.

## Phase 12: Advanced OCR (Layout Analysis)
- [ ] Prototype `layoutlm` or `surya` for table extraction.
