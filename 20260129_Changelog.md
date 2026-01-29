# Changelog - 2026-01-29

## Code Review Fixes

This changelog documents all fixes made as part of the comprehensive code review of the Ragnificent RAG application.

---

## Summary of Changes

| Category | Issues Fixed |
|----------|-------------|
| Security | 3 |
| Architecture | 4 |
| Error Handling | 3 |
| Code Quality | 8 |
| Performance | 2 |

---

## Files Modified

### 1. `app/services/__init__.py` (NEW)
- **Created**: New services module for shared business logic

### 2. `app/services/corpus_service.py` (NEW)
- **Created**: Centralized corpus management service
- **Features**:
  - `validate_corpus_id()` - Validates corpus IDs to prevent path traversal attacks
  - `sanitize_yaml_string()` - Sanitizes user input for safe YAML output
  - `CorpusService` class with methods:
    - `get_corpus_path()` - Returns validated path with path traversal protection
    - `corpus_exists()` - Checks if corpus exists
    - `get_corpus_metadata()` - Retrieves corpus configuration
    - `get_all_corpora()` - Lists all available corpora
    - `create_corpus()` - Creates new corpus with proper sanitization
- **Security**: Prevents path traversal vulnerabilities with regex validation and path resolution checks

### 3. `app/config/schema.py`
- **Added**: `AnswerModelConfig` - Configuration class for default LLM/answer model
- **Added**: `StateDbConfig` - Configuration class for state database path
- **Added**: `GlobalConfig.get_state_db_path()` - Method to resolve state DB path (env var > config > fallback)
- **Added**: `GlobalConfig.get_corpora_path()` - Method to get corpora directory path
- **Fixed**: Removed hacky string replacement for path resolution
- **Updated**: `ModelsConfig` now includes optional `answer` configuration

### 4. `app/providers/ollama.py`
- **Fixed**: Removed global environment variable mutation (`os.environ["OLLAMA_HOST"]`)
- **Changed**: Now uses `ollama.Client(host=base_url)` for explicit host configuration
- **Added**: Proper logging for embedding and generation failures
- **Added**: Comprehensive docstrings

### 5. `app/state/db.py`
- **Fixed**: Thread-safety issues with SQLite connections
- **Changed**: Implemented thread-local storage pattern for connections
- **Added**: `transaction()` context manager for automatic commit/rollback
- **Added**: `cursor()` context manager for cursor operations
- **Added**: WAL mode and busy timeout for better concurrency
- **Added**: `execute()` and `execute_commit()` convenience methods
- **Updated**: All methods now have proper docstrings

### 6. `app/vector/qdrant_client.py`
- **Added**: `collection_exists()` method with caching
- **Added**: Collection existence check before search operations
- **Added**: `CollectionNotFoundError` exception class
- **Added**: `invalidate_cache()` method for cache management
- **Added**: `DEFAULT_VECTOR_SIZE` constant
- **Fixed**: Silent failures now logged properly
- **Updated**: All methods have comprehensive docstrings

### 7. `app/engines/pdf_engine.py`
- **Fixed**: Type hint inconsistency (`-> str` changed to `-> PdfExtractionResult`)
- **Added**: `PdfExtractionResult` TypedDict for proper typing
- **Fixed**: Unreliable OCR detection (now uses boolean flag instead of string search)
- **Added**: `ocr_page_count` to metadata for tracking OCR usage
- **Added**: Constants `DEFAULT_MIN_CHARS_PER_PAGE` and `OCR_ZOOM_FACTOR`
- **Refactored**: Extracted `_extract_page_ocr()` method for cleaner code

### 8. `app/ingest/chunkers/pdf_sections.py`
- **Fixed**: `overlap_tokens` parameter now actually implemented
- **Added**: `_estimate_tokens()` method for token estimation
- **Added**: `_calculate_overlap_paragraphs()` for overlap calculation
- **Added**: Constants `DEFAULT_MAX_TOKENS`, `DEFAULT_OVERLAP_TOKENS`, `WORDS_TO_TOKENS_RATIO`
- **Added**: `chunk_index` to chunk metadata
- **Updated**: Comprehensive docstrings

### 9. `app/ingest/chunkers/code_symbols.py`
- **Added**: Constants `DEFAULT_MAX_TOKENS`, `MIN_CHUNK_SIZE_CHARS`, `SYMBOL_PREFIXES`
- **Added**: `_is_symbol_start()` method for cleaner logic
- **Added**: Support for `async def` in addition to `def` and `class`
- **Added**: `chunk_index` to chunk metadata
- **Updated**: Comprehensive docstrings

### 10. `app/ingest/pipeline.py`
- **Fixed**: Database connection handling with context managers
- **Added**: Integration with `CorpusService` for corpus validation
- **Added**: `_record_success()` and `_record_failure()` helper methods
- **Added**: Proper error recording with `failure_count` tracking
- **Added**: `SUPPORTED_EXTENSIONS` constant
- **Changed**: `run_once()` now returns summary dictionary
- **Removed**: Duplicate `_get_corpora()` logic (now uses CorpusService)

### 11. `app/cli.py`
- **Fixed**: Replaced `print()` statements with proper logger
- **Added**: `cmd_ingest()` function - now fully implemented
- **Added**: `--corpus` argument for ingest command
- **Added**: Constants `DEFAULT_HOST` and `DEFAULT_PORT`
- **Updated**: Uses `config.get_state_db_path()` instead of hacky string replacement

### 12. `app/api/routes/query.py`
- **Fixed**: API response now uses actual LLM answer from engine (was being overwritten)
- **Fixed**: Synchronous blocking calls now use `asyncio.to_thread()`
- **Added**: FastAPI dependency injection with `Depends()`
- **Added**: `get_config()`, `get_vector_service()`, `get_embedder()`, `get_default_llm()`, `get_query_engine()` factory functions
- **Added**: `llm_model` parameter to `QueryRequest`
- **Added**: `time` field to `QueryResponse`
- **Updated**: Uses config for LLM settings instead of hardcoded values

### 13. `app/api/routes/ingest.py`
- **Fixed**: Synchronous blocking calls now use `asyncio.to_thread()`
- **Added**: FastAPI dependency injection pattern
- **Added**: `IngestResponse` Pydantic model
- **Added**: Corpus ID validation using `validate_corpus_id()`
- **Added**: `/status` endpoint placeholder
- **Removed**: Global state initialization at module level

### 14. `app/api/query_engine.py`
- **Fixed**: Hardcoded URLs replaced with config-based resolution
- **Added**: Corpus ID validation using `validate_corpus_id()`
- **Added**: `_get_corpus_config_path()` method for safe path resolution
- **Added**: `DEFAULT_OLLAMA_URL` constant
- **Added**: Support for `base_url` in corpus answer config
- **Updated**: Better context formatting with chunk_index fallback

### 15. `app/gui/routes.py`
- **Fixed**: Path traversal vulnerability in `manage_corpus()` endpoint
- **Fixed**: Global state replaced with dependency injection functions
- **Fixed**: Hacky config path resolution
- **Added**: Integration with `CorpusService`
- **Added**: Form validation for `source_path`
- **Added**: Check for existing corpus before creation
- **Added**: `get_corpora_with_vectors()` helper function
- **Removed**: Duplicate `get_corpora()` function

### 16. `app/providers/factory.py`
- **Fixed**: Removed dead code (OpenAI stub that fell through to exception)
- **Added**: `SUPPORTED_EMBEDDING_PROVIDERS` and `SUPPORTED_LLM_PROVIDERS` constants
- **Added**: `list_supported_providers()` function
- **Updated**: Better error messages showing supported providers

### 17. `app/state/stats.py`
- **Added**: Proper logging for database errors
- **Added**: `get_corpus_stats()` method for per-corpus statistics
- **Added**: Connection timeout configuration
- **Updated**: Comprehensive docstrings

### 18. `app/gui/templates/search_results.html`
- **Fixed**: Template now uses `answer` instead of `answer_html`
- **Added**: Display of query time
- **Added**: Fallback for missing metadata fields
- **Added**: Empty state message when no hits
- **Fixed**: Proper text escaping with `| e` filter

---

## Security Fixes

1. **Path Traversal Vulnerability** (Critical)
   - Files: `app/gui/routes.py`, `app/services/corpus_service.py`
   - All corpus IDs are now validated against a strict regex pattern
   - Path resolution is verified to stay within the corpora directory

2. **Global Environment Variable Mutation** (Critical)
   - File: `app/providers/ollama.py`
   - Removed `os.environ["OLLAMA_HOST"]` mutations
   - Now uses explicit `Client(host=...)` constructor

3. **Input Sanitization for YAML** (Medium)
   - File: `app/services/corpus_service.py`
   - User inputs are sanitized before writing to YAML files
   - Control characters are stripped (except newlines and tabs)

---

## Architecture Improvements

1. **Thread-Safe Database Connections**
   - File: `app/state/db.py`
   - Implemented thread-local storage pattern
   - Added WAL mode for better concurrent read performance

2. **Dependency Injection**
   - Files: `app/api/routes/query.py`, `app/api/routes/ingest.py`, `app/gui/routes.py`
   - Replaced module-level global state with factory functions
   - Uses FastAPI's `Depends()` for proper dependency injection

3. **Async Non-Blocking Operations**
   - Files: `app/api/routes/query.py`, `app/api/routes/ingest.py`
   - Blocking I/O operations now run in thread pool via `asyncio.to_thread()`

4. **Centralized Services**
   - File: `app/services/corpus_service.py`
   - Consolidated duplicate `get_corpora()` logic
   - Single source of truth for corpus operations

---

## Breaking Changes

None. All existing APIs and workflows remain compatible.

---

## Testing Notes

The following workflows should be verified:

1. **CLI Commands**:
   - `python -m app.cli serve` - Start API server
   - `python -m app.cli init-db` - Initialize database
   - `python -m app.cli ingest --corpus <id>` - Run ingestion

2. **API Endpoints**:
   - `POST /api/query` - RAG query
   - `POST /api/ingest/run` - Trigger ingestion
   - `GET /health` - Health check

3. **GUI Pages**:
   - `/gui/dashboard` - Dashboard
   - `/gui/search` - Search interface
   - `/gui/corpora` - Corpus list
   - `/gui/corpora/new` - Create corpus
   - `/gui/corpora/{id}` - Manage corpus

---

## Dependencies

No new dependencies added. All fixes use existing packages.
