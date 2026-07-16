# Voltron repository documentation corpus

`voltron-repository-docs` is the narrow retrieval corpus for approved Voltron
READMEs and maintained Markdown documentation. It is separate from task/AAR
memory and from the Wiki bootstrap corpus:

```text
Agent Harness documentation catalog
  -> selected Markdown snapshot
  -> authenticated RAGnificent source receipt
  -> exact-file ingest into voltron-repository-docs
  -> cited retrieval for Trombone/AoJ/FORGE
```

The checked-out repository remains canonical. The generated snapshot, vector
index, and Wiki page are derived views; none may replace the source Git file.

## Deploy the corpus

1. Copy [voltron-repository-docs.corpus.yaml](voltron-repository-docs.corpus.yaml)
   to the ignored runtime path
   `rag_library/corpora/voltron-repository-docs/corpus.yaml`.
2. Docker Compose mounts the host snapshot directory into the container
   read-only:

   ```text
   host: D:/Jazzy/Agent_Harness_Template/data/runtime/wiki/documentation-snapshots
     -> container: /app/voltron-documentation-snapshots:ro
   ```

   Configure the **container-visible** path in Ragnificent's runtime `.env`:

   ```text
   RAGNIFICENT_VOLTRON_REPOSITORY_DOCS_ROOT=/app/voltron-documentation-snapshots
   ```

   Do not configure the Windows host path as the service value. The receipt API
   rejects an unset value, `D:/Jazzy`, another broad workspace root, a
   mismatched `RAGNIFICENT_TRUSTED_SOURCE_ROOTS` mapping, traversal, or a file
   outside this narrow mounted directory.
3. Keep `RAGNIFICENT_INTERNAL_TOKEN` configured. The documentation catalog
   sends it only as `X-Ragnificent-Token`; do not put its value in a snapshot,
   corpus configuration, Wiki page, or source receipt.

The generic `RAGNIFICENT_TRUSTED_SOURCE_ROOTS` setting does not need a
`voltron_repository_docs` entry. If it has one, it must resolve to the exact
same directory as the dedicated environment variable.

## Receipt and ingest contract

For every approved snapshot, Agent Harness calls the existing routes:

```text
POST /api/source-receipts
POST /api/source-receipts/{receipt_id}/ingest
```

The receipt request uses fixed lane values plus repository provenance:

```json
{
  "workspace_id": "voltron",
  "corpus_id": "voltron-repository-docs",
  "source_kind": "repository_documentation",
  "source_system": "voltron_documentation_catalog",
  "source_record_id": "SweetingTech/Agent_Harness_Template:README.md",
  "source_locator": {
    "root_id": "voltron_repository_docs",
    "relative_path": "agent-harness/README.md"
  },
  "content_sha256": "<sha256-of-the-snapshot-file>",
  "documentation_provenance": {
    "repository": "SweetingTech/Agent_Harness_Template",
    "path": "README.md",
    "git_commit": "<full-40-or-64-character-git-commit>"
  },
  "privacy": "internal",
  "idempotency_key": "repository-docs:agent-harness:README.md:<content-sha256>"
}
```

The service recomputes the file hash before accepting the receipt and again
before ingesting it. The caller never supplies a server path, model route, Wiki
authority, or arbitrary metadata. The corpus policy requires this exact source
kind, source system, root ID, and provenance shape; other corpora cannot use
the documentation root.

The stored receipt returns a canonical locator such as
`ragnificent://source-receipts/<receipt_id>`. Persist that locator and receipt
ID in the documentation catalog beside the Git repository, source-relative
path, commit, and file hash.

## Retrieval citations

`POST /api/query` continues to return `hits`. For results that came from this
corpus, it also returns a safe `citations` array:

```json
{
  "citations": [
    {
      "repository": "SweetingTech/Agent_Harness_Template",
      "path": "README.md",
      "git_commit": "<pinned-commit>",
      "content_sha256": "<verified-sha256>",
      "source_receipt_id": "<receipt-id>",
      "canonical_locator": "ragnificent://source-receipts/<receipt-id>"
    }
  ]
}
```

No local snapshot path is returned in those citations or receipt-backed vector
payloads. Agents should use the citations to locate the canonical repository
file and verify freshness before changing code.
