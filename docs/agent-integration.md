# Agent Integration Guide

This guide is written for AI agents (LLM-based assistants, tool-calling agents, automated pipelines) that need to connect to RAGnificent and query its vector databases.

---

## Base URL

RAGnificent runs on your local network. The default address is:

```
http://<host-ip>:8008
```

Replace `<host-ip>` with the IP or hostname of the machine running RAGnificent (e.g. `192.168.1.50`, `ragserver.local`). CORS is open, so any origin on the network can call these endpoints.

---

## Step 1 — Discover Available Databases

Before querying, ask the server what RAG databases exist and whether they have indexed content.

```
GET /api/corpora
```

**Response** — array of corpus summaries:

```json
[
  {
    "corpus_id": "cyber_blue",
    "description": "Cybersecurity knowledge base",
    "vector_count": 4821,
    "query_endpoint": "/api/query"
  },
  {
    "corpus_id": "dm_green",
    "description": "Dungeon Master resources",
    "vector_count": 1103,
    "query_endpoint": "/api/query"
  }
]
```

**Fields returned:**

| Field | Description |
|---|---|
| `corpus_id` | Pass this as `corpus_id` in `POST /api/query` |
| `description` | Human-readable label for the corpus |
| `vector_count` | Chunks indexed (0 = not yet ingested, do not query) |
| `query_endpoint` | The path to POST queries to |

> Note: Filesystem paths (`source_path`, `inbox_path`) are not returned by the list or detail endpoints to avoid exposing local directory structure over the network.

**Decision logic for agents:**
- If `vector_count` is `0`, the corpus has no indexed content yet — do not query it.
- Pick the corpus whose `description` best matches the user's question.
- Store the `corpus_id` — you will need it in every query.

---

## Step 2 — Inspect a Specific Database (optional)

```
GET /api/corpora/{corpus_id}
```

Returns the same fields as the list, plus the full `config` block from `corpus.yaml` (chunking strategy, model overrides, etc.). Useful for debugging or when an agent needs to know which LLM will answer.

---

## Step 3 — Run a Query

```
POST /api/query
Content-Type: application/json
```

**Request body:**

```json
{
  "query": "What are the OWASP Top 10 vulnerabilities?",
  "corpus_id": "cyber_blue",
  "top_k": 5,
  "llm_model": "llama3"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | The natural-language question |
| `corpus_id` | string | recommended | Which RAG database to search. Omit to search all corpora. |
| `top_k` | int | no | Number of document chunks to retrieve (default: 5) |
| `llm_model` | string | no | Override the Ollama model used to generate the answer |

**Response:**

```json
{
  "query": "What are the OWASP Top 10 vulnerabilities?",
  "answer": "The OWASP Top 10 are: 1. Broken Access Control ...",
  "hits": [
    {
      "score": 0.91,
      "payload": {
        "text": "...relevant chunk text...",
        "file_name": "owasp_2023.pdf",
        "page": 3,
        "chunk_index": 7
      }
    }
  ],
  "time": 1.42
}
```

| Field | Description |
|---|---|
| `answer` | LLM-generated answer grounded in the retrieved chunks |
| `hits` | The raw vector search results with source citations |
| `hits[].payload.text` | The exact text chunk that was retrieved |
| `hits[].payload.file_name` | The source document filename |
| `hits[].payload.page` | Page number (for PDFs) |
| `hits[].score` | Cosine similarity score (0–1, higher is more relevant) |
| `time` | Query time in seconds |

---

## Step 4 — Trigger Ingestion (if needed)

If `vector_count` is 0 or you need to sync new documents, trigger ingestion:

```
POST /api/ingest/run?corpus_id=cyber_blue
```

Response:

```json
{
  "status": "success",
  "message": "Ingestion completed for cyber_blue",
  "summary": { ... }
}
```

Ingestion is synchronous — the response only arrives once it finishes. Large document sets can take several minutes.

---

## Step 5 — Create a New Database (if needed)

If no suitable corpus exists, an agent can create one:

```
POST /api/corpora
Content-Type: application/json
```

```json
{
  "corpus_id": "my_docs",
  "description": "Internal policy documents",
  "source_path": "D:/company/policies",
  "llm_model": "llama3",
  "llm_provider": "ollama"
}
```

| Field | Required | Description |
|---|---|---|
| `corpus_id` | yes | Alphanumeric + underscores/hyphens, max 64 chars |
| `description` | yes | Human-readable label |
| `source_path` | yes | Absolute path to the folder of documents to ingest |
| `llm_model` | no | Ollama model for answers (default: `llama3`) |
| `llm_provider` | no | Provider name (default: `ollama`) |

Response `201 Created`:

```json
{
  "status": "created",
  "corpus_id": "my_docs",
  "message": "Corpus 'my_docs' created. Trigger ingestion with POST /api/ingest/run?corpus_id=my_docs",
  "query_endpoint": "/api/query"
}
```

After creation, trigger ingestion (Step 4) before querying.

---

## Health Check

```
GET /health
```

Returns `200 OK` when the service is up. Use this to verify connectivity before running queries.

---

## Complete Agent Workflow (pseudocode)

```
1. GET /health
   → if not 200, abort — service is down

2. GET /api/corpora
   → filter where vector_count > 0
   → select corpus_id whose description matches user intent

3. if no matching corpus:
   → POST /api/corpora  (create it)
   → POST /api/ingest/run?corpus_id=<id>  (index documents)

4. POST /api/query
   body: { query, corpus_id, top_k: 5 }
   → return answer + hits to user

5. cite sources from hits[].payload.file_name + hits[].payload.page
```

---

## Available LLM Models

```
GET /api/query/models
```

Returns the list of Ollama models currently available on the host. Pass any of these as `llm_model` in a query request.

---

## Notes for Agent Implementors

- **No authentication** is required on a local network deployment. Do not expose the service to the public internet without adding auth.
- **CORS** is fully open (`*`) — any origin can call the API.
- Queries are synchronous and blocking. For long-running LLM responses, set a generous timeout (30–120 seconds).
- `corpus_id` validation: alphanumeric characters, underscores, and hyphens only. Max 64 characters. Reject anything else before sending to the API.
- If `answer` is `null` in the query response, no relevant content was found in the corpus. The `hits` array will also be empty.
- The service runs on Ollama locally — model availability depends on what has been pulled with `ollama pull`.
