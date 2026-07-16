import hashlib
import asyncio
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.routes import corpora, ingest, source_receipts
from app.config.schema import GlobalConfig
from app.ingest.pipeline import IngestionPipeline
from app.security import (
    configured_cors_origins,
    require_legacy_mutation_access,
)
from app.services.source_receipt_service import ensure_source_receipts_schema
from app.state.db import Database


def _config(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(
        library_root=str(tmp_path / "library"),
        ingest={
            "lock_file": str(tmp_path / "ingest.lock"),
            "ocr_trigger": {"min_chars_per_page": 10},
        },
        extraction={"pdf_backend": "pymupdf", "normalize": {"whitespace": True}},
        ocr={
            "backend": "tesseract",
            "ocrmypdf": {
                "language": "eng",
                "deskew": True,
                "rotate_pages": True,
                "clean": False,
                "cache_dir": str(tmp_path / "ocr-cache"),
            },
        },
        models={
            "embeddings": {
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model": "nomic-embed-text",
            },
            "answer": {
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model": "llama3",
            },
        },
        vector_db={
            "backend": "qdrant",
            "url": "http://localhost:6333",
            "collection_prefix": "test",
        },
        state_db={"path": str(tmp_path / "state" / "ingest.sqlite")},
    )


def _write_corpus(
    config: GlobalConfig,
    *,
    privacy="internal",
    embedding_provider="ollama",
    answer_provider="ollama",
    wiki_publication=None,
):
    corpus_path = Path(config.library_root) / "corpora" / "demo"
    corpus_path.mkdir(parents=True, exist_ok=True)
    corpus_config = {
        "corpus_id": "demo",
        "description": "test corpus",
        "source_path": str(Path(config.library_root) / "agent_harness_aar_sources"),
        "privacy": privacy,
        "models": {
            "embeddings": {"provider": embedding_provider, "model": "nomic-embed-text"},
            "answer": {"provider": answer_provider, "model": "llama3"},
        },
    }
    if wiki_publication is not None:
        corpus_config["wiki_publication"] = wiki_publication
    (corpus_path / "corpus.yaml").write_text(
        yaml.safe_dump(corpus_config),
        encoding="utf-8",
    )


def _source_file(config: GlobalConfig) -> tuple[Path, str]:
    root = Path(config.library_root) / "agent_harness_aar_sources"
    root.mkdir(parents=True)
    path = root / "operator" / "lesson.md"
    path.parent.mkdir()
    path.write_text("# Safe source\n\nEvidence content.", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _write_repository_docs_corpus(config: GlobalConfig):
    corpus_path = Path(config.library_root) / "corpora" / "voltron-repository-docs"
    corpus_path.mkdir(parents=True, exist_ok=True)
    (corpus_path / "corpus.yaml").write_text(
        yaml.safe_dump(
            {
                "corpus_id": "voltron-repository-docs",
                "description": "approved repository docs",
                "privacy": "internal",
                "wiki_publication": "private_wiki_allowed",
                "source_receipt_policy": {
                    "profile": "voltron_repository_docs_v1",
                    "trusted_root_id": "voltron_repository_docs",
                    "source_kind": "repository_documentation",
                    "source_system": "voltron_documentation_catalog",
                },
                "models": {
                    "embeddings": {"provider": "ollama", "model": "nomic-embed-text"},
                    "answer": {"provider": "ollama", "model": "llama3"},
                },
            }
        ),
        encoding="utf-8",
    )


def _documentation_snapshot(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "documentation-snapshots"
    path = root / "agent-harness" / "README.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Agent Harness\n\nCanonical internal documentation.", encoding="utf-8")
    return root, path, hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_docs_payload(content_hash: str, **overrides):
    payload = {
        "workspace_id": "voltron",
        "corpus_id": "voltron-repository-docs",
        "source_kind": "repository_documentation",
        "source_system": "voltron_documentation_catalog",
        "source_record_id": "SweetingTech/Agent_Harness_Template:README.md",
        "source_locator": {
            "root_id": "voltron_repository_docs",
            "relative_path": "agent-harness/README.md",
        },
        "content_sha256": content_hash,
        "title": "Agent Harness README",
        "documentation_provenance": {
            "repository": "SweetingTech/Agent_Harness_Template",
            "path": "README.md",
            "git_commit": "a" * 40,
        },
        "privacy": "internal",
        "idempotency_key": f"repository-docs:agent-harness:{content_hash}",
    }
    payload.update(overrides)
    return payload


def _app(config: GlobalConfig, db: Database) -> FastAPI:
    app = FastAPI()
    app.include_router(source_receipts.router, prefix="/api")
    app.dependency_overrides[source_receipts.get_config] = lambda: config
    app.dependency_overrides[source_receipts.get_database] = lambda: db
    return app


def _payload(content_hash: str, **overrides):
    payload = {
        "workspace_id": "voltron",
        "corpus_id": "demo",
        "source_kind": "agent_artifact",
        "source_system": "agent_harness",
        "source_record_id": "task_123",
        "source_locator": {
            "root_id": "agent_harness_aar_sources",
            "relative_path": "operator/lesson.md",
        },
        "content_sha256": content_hash,
        "title": "Lesson",
        "privacy": "internal",
        "correlation_id": "corr_123",
        "idempotency_key": "receipt-key-123",
    }
    payload.update(overrides)
    return payload


def _database(config: GlobalConfig) -> Database:
    # Tests must not inherit a workstation STATE_DB_PATH loaded from .env.
    db = Database(config.state_db.path)
    schema = Path(__file__).parents[1] / "app" / "state" / "schema.sql"
    db.init_db(str(schema))
    return db


def test_source_receipt_requires_configured_valid_token_and_is_idempotent(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_corpus(config)
    _, content_hash = _source_file(config)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")

    with TestClient(_app(config, db)) as client:
        missing = client.post("/api/source-receipts", json=_payload(content_hash))
        invalid = client.post(
            "/api/source-receipts",
            json=_payload(content_hash),
            headers={"X-Ragnificent-Token": "wrong"},
        )
        created = client.post(
            "/api/source-receipts",
            json=_payload(content_hash),
            headers={"X-Ragnificent-Token": "receipt-test-token"},
        )
        duplicate = client.post(
            "/api/source-receipts",
            json=_payload(content_hash),
            headers={"X-Ragnificent-Token": "receipt-test-token"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert created.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["receipt_id"] == created.json()["receipt_id"]
    assert created.json()["canonical_locator"].startswith("ragnificent://source-receipts/")
    assert created.json()["source_locator"] == {
        "root_id": "agent_harness_aar_sources",
        "relative_path": "operator/lesson.md",
    }


def test_source_receipt_wiki_publication_is_server_computed_and_immutable(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_corpus(config, wiki_publication="private_wiki_allowed")
    _, content_hash = _source_file(config)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")
    headers = {"X-Ragnificent-Token": "receipt-test-token"}

    with TestClient(_app(config, db)) as client:
        caller_override = client.post(
            "/api/source-receipts",
            json=_payload(content_hash, wiki_publication="private_wiki_allowed"),
            headers=headers,
        )
        created = client.post("/api/source-receipts", json=_payload(content_hash), headers=headers)
        receipt_id = created.json()["receipt_id"]

        # Later corpus config changes must not rewrite receipt authority.
        _write_corpus(config)
        fetched = client.get(f"/api/source-receipts/{receipt_id}", headers=headers)

    assert caller_override.status_code == 422
    assert created.status_code == 201
    assert created.json()["wiki_publication"] == "private_wiki_allowed"
    assert fetched.status_code == 200
    assert fetched.json()["wiki_publication"] == "private_wiki_allowed"

    with db.cursor() as cursor:
        row = cursor.execute(
            "SELECT wiki_publication FROM source_receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
    assert row["wiki_publication"] == "private_wiki_allowed"


def test_source_receipt_wiki_publication_fails_closed_for_local_only_corpus(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_corpus(
        config,
        privacy="local_only",
        wiki_publication="private_wiki_allowed",
    )
    _, content_hash = _source_file(config)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")

    with TestClient(_app(config, db)) as client:
        created = client.post(
            "/api/source-receipts",
            json=_payload(content_hash, privacy="local_only"),
            headers={"X-Ragnificent-Token": "receipt-test-token"},
        )

    assert created.status_code == 201
    assert created.json()["wiki_publication"] == "local_only"


def test_source_receipt_wiki_publication_requires_exact_corpus_opt_in(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_corpus(config, wiki_publication="private-wiki-allowed")
    _, content_hash = _source_file(config)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")

    with TestClient(_app(config, db)) as client:
        created = client.post(
            "/api/source-receipts",
            json=_payload(content_hash),
            headers={"X-Ragnificent-Token": "receipt-test-token"},
        )

    assert created.status_code == 201
    assert created.json()["wiki_publication"] == "local_only"


def test_source_receipts_schema_migrates_legacy_rows_to_local_only(tmp_path):
    db = Database(str(tmp_path / "state" / "legacy.sqlite"))
    with db.transaction() as conn:
        conn.execute("CREATE TABLE source_receipts (receipt_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO source_receipts (receipt_id) VALUES ('legacy-receipt')")

    ensure_source_receipts_schema(db)

    with db.cursor() as cursor:
        row = cursor.execute(
            "SELECT wiki_publication FROM source_receipts WHERE receipt_id = 'legacy-receipt'"
        ).fetchone()
        columns = {
            item["name"]
            for item in cursor.execute("PRAGMA table_info(source_receipts)").fetchall()
        }

    assert "wiki_publication" in columns
    assert row["wiki_publication"] == "local_only"


def test_source_receipt_rejects_untrusted_or_escaping_locator(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_corpus(config)
    _, content_hash = _source_file(config)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")

    with TestClient(_app(config, db)) as client:
        unknown_root = client.post(
            "/api/source-receipts",
            json=_payload(content_hash, source_locator={"root_id": "outside", "relative_path": "secret.md"}),
            headers={"X-Ragnificent-Token": "receipt-test-token"},
        )
        traversal = client.post(
            "/api/source-receipts",
            json=_payload(
                content_hash,
                source_locator={"root_id": "agent_harness_aar_sources", "relative_path": "../secret.md"},
                idempotency_key="receipt-key-456",
            ),
            headers={"X-Ragnificent-Token": "receipt-test-token"},
        )

    assert unknown_root.status_code == 409
    assert traversal.status_code == 409
    assert "server" not in unknown_root.text.lower()


def test_source_receipt_local_only_rejects_cloud_profiles(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_corpus(config, privacy="local_only", embedding_provider="openai", answer_provider="openai")
    _, content_hash = _source_file(config)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")

    with TestClient(_app(config, db)) as client:
        response = client.post(
            "/api/source-receipts",
            json=_payload(content_hash, privacy="local_only"),
            headers={"X-Ragnificent-Token": "receipt-test-token"},
        )

    assert response.status_code == 409
    assert "forbids cloud embedding provider" in response.json()["detail"]


def test_source_receipt_ingests_only_the_receipted_file(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_corpus(config)
    _, content_hash = _source_file(config)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")

    class Pipeline:
        calls = []

        def ingest_receipted_file(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "status": "processed",
                "file_hash": kwargs["expected_hash"],
                "source_receipt_id": kwargs["receipt_id"],
            }

    pipeline = Pipeline()
    app = _app(config, db)
    app.dependency_overrides[source_receipts.get_pipeline] = lambda: pipeline
    headers = {"X-Ragnificent-Token": "receipt-test-token"}
    with TestClient(app) as client:
        created = client.post("/api/source-receipts", json=_payload(content_hash), headers=headers)
        receipt_id = created.json()["receipt_id"]
        ingested = client.post(f"/api/source-receipts/{receipt_id}/ingest", headers=headers)

    assert ingested.status_code == 200
    assert ingested.json()["status"] == "ingested"
    assert len(pipeline.calls) == 1
    assert pipeline.calls[0]["receipt_id"] == receipt_id
    assert pipeline.calls[0]["canonical_locator"].endswith(receipt_id)


def test_repository_docs_receipts_require_the_narrow_snapshot_root_and_preserve_provenance(
    tmp_path,
    monkeypatch,
):
    config = _config(tmp_path)
    _write_repository_docs_corpus(config)
    snapshot_root, _, content_hash = _documentation_snapshot(tmp_path)
    db = _database(config)
    headers = {"X-Ragnificent-Token": "receipt-test-token"}
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")

    # A docs corpus fails closed before any source path is resolved when the
    # dedicated generated-snapshot root has not been configured.
    with TestClient(_app(config, db)) as client:
        unset = client.post(
            "/api/source-receipts",
            json=_repository_docs_payload(content_hash),
            headers=headers,
        )
    assert unset.status_code == 409
    assert "RAGNIFICENT_VOLTRON_REPOSITORY_DOCS_ROOT" in unset.json()["detail"]

    monkeypatch.setenv("RAGNIFICENT_VOLTRON_REPOSITORY_DOCS_ROOT", str(snapshot_root))
    app = _app(config, db)

    class Pipeline:
        calls = []

        def ingest_receipted_file(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "status": "processed",
                "file_hash": kwargs["expected_hash"],
                "source_receipt_id": kwargs["receipt_id"],
            }

    pipeline = Pipeline()
    app.dependency_overrides[source_receipts.get_pipeline] = lambda: pipeline
    with TestClient(app) as client:
        created = client.post(
            "/api/source-receipts",
            json=_repository_docs_payload(content_hash),
            headers=headers,
        )
        receipt_id = created.json()["receipt_id"]
        ingested = client.post(f"/api/source-receipts/{receipt_id}/ingest", headers=headers)

    assert created.status_code == 201
    assert created.json()["documentation_provenance"] == {
        "repository": "SweetingTech/Agent_Harness_Template",
        "path": "README.md",
        "git_commit": "a" * 40,
        "content_sha256": content_hash,
    }
    assert ingested.status_code == 200
    assert pipeline.calls[0]["documentation_provenance"] == created.json()["documentation_provenance"]

    # A generic trusted-root setting cannot remap the docs root to a broader
    # workspace path; it must resolve to the exact dedicated snapshot root.
    monkeypatch.setenv(
        "RAGNIFICENT_TRUSTED_SOURCE_ROOTS",
        '{"voltron_repository_docs": "' + str(tmp_path).replace("\\", "\\\\") + '"}',
    )
    with TestClient(_app(config, db)) as client:
        mismatched = client.post(
            "/api/source-receipts",
            json=_repository_docs_payload(content_hash, idempotency_key="repository-docs:mismatch"),
            headers=headers,
        )
    assert mismatched.status_code == 409
    assert "does not match" in mismatched.json()["detail"]


def test_repository_docs_receipt_rejects_non_markdown_or_unpinned_provenance(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_repository_docs_corpus(config)
    snapshot_root, _, content_hash = _documentation_snapshot(tmp_path)
    db = _database(config)
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "receipt-test-token")
    monkeypatch.setenv("RAGNIFICENT_VOLTRON_REPOSITORY_DOCS_ROOT", str(snapshot_root))
    headers = {"X-Ragnificent-Token": "receipt-test-token"}

    with TestClient(_app(config, db)) as client:
        non_markdown = client.post(
            "/api/source-receipts",
            json=_repository_docs_payload(
                content_hash,
                documentation_provenance={
                    "repository": "SweetingTech/Agent_Harness_Template",
                    "path": "scripts/bootstrap.ps1",
                    "git_commit": "a" * 40,
                },
            ),
            headers=headers,
        )
        short_commit = client.post(
            "/api/source-receipts",
            json=_repository_docs_payload(
                content_hash,
                documentation_provenance={
                    "repository": "SweetingTech/Agent_Harness_Template",
                    "path": "README.md",
                    "git_commit": "abc1234",
                },
                idempotency_key="repository-docs:short-commit",
            ),
            headers=headers,
        )

    assert non_markdown.status_code == 409
    assert "relative Markdown path" in non_markdown.json()["detail"]
    # Pydantic rejects a non-full commit at the route boundary before it can
    # become provenance, while the service remains defensive for direct calls.
    assert short_commit.status_code == 422


def test_receipted_pipeline_maps_repository_provenance_to_safe_vector_metadata(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Documentation", encoding="utf-8")
    content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    observed = {}

    # The receipt method is deliberately isolated from constructor-heavy OCR
    # setup. Stub only its collaborators to assert the metadata forwarded into
    # _process_file, where vectors are built.
    pipeline = object.__new__(IngestionPipeline)
    pipeline._get_corpora = lambda corpus_id: [{"config": {}}]
    pipeline._assert_corpus_model_policy = lambda corpus_config: None
    pipeline._get_embedder_for_corpus = lambda corpus_config: object()

    def process(file_path, corpus_id, corpus_config, embedder, run_logger=None, receipt_context=None):
        observed["receipt_context"] = receipt_context
        return "processed"

    pipeline._process_file = process
    result = pipeline.ingest_receipted_file(
        corpus_id="voltron-repository-docs",
        file_path=str(source),
        receipt_id="receipt-123",
        canonical_locator="ragnificent://source-receipts/receipt-123",
        expected_hash=content_hash,
        documentation_provenance={
            "repository": "SweetingTech/Agent_Harness_Template",
            "path": "README.md",
            "git_commit": "a" * 40,
            "content_sha256": content_hash,
        },
    )

    assert result["status"] == "processed"
    assert observed["receipt_context"] == {
        "source_receipt_id": "receipt-123",
        "source_receipt_locator": "ragnificent://source-receipts/receipt-123",
        "source": "ragnificent://source-receipts/receipt-123",
        "citation_repository": "SweetingTech/Agent_Harness_Template",
        "citation_path": "README.md",
        "citation_git_commit": "a" * 40,
        "citation_content_sha256": content_hash,
    }


def test_strict_legacy_mode_requires_token_but_staged_loopback_still_works(tmp_path, monkeypatch):
    config = _config(tmp_path)
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")

    class Pipeline:
        def __init__(self):
            self.config = config

        def run_once(self, *args, **kwargs):
            return {
                "corpora_processed": 1,
                "total_files": 0,
                "files_completed": 0,
                "files_processed": 0,
                "files_skipped": 0,
                "files_failed": 0,
            }

    app.dependency_overrides[ingest.get_pipeline] = Pipeline
    monkeypatch.setenv("RAGNIFICENT_INTERNAL_TOKEN", "legacy-test-token")
    monkeypatch.setenv("RAGNIFICENT_REQUIRE_INTERNAL_AUTH", "true")
    with TestClient(app) as client:
        denied = client.post("/api/ingest/run?corpus_id=demo")
        allowed = client.post(
            "/api/ingest/run?corpus_id=demo",
            headers={"X-Ragnificent-Token": "legacy-test-token"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200

    monkeypatch.setenv("RAGNIFICENT_REQUIRE_INTERNAL_AUTH", "false")
    loopback_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ingest/run",
            "headers": [],
            "client": ("127.0.0.1", 51000),
            "scheme": "http",
            "server": ("127.0.0.1", 8008),
        }
    )
    asyncio.run(require_legacy_mutation_access(loopback_request))


def test_cors_uses_explicit_origins_and_never_a_wildcard(monkeypatch):
    monkeypatch.delenv("RAGNIFICENT_CORS_ORIGINS", raising=False)
    assert "*" not in configured_cors_origins()
    monkeypatch.setenv("RAGNIFICENT_CORS_ORIGINS", "https://trusted.example,*")
    assert "*" not in configured_cors_origins()

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured_cors_origins(),
        allow_methods=["POST"],
        allow_headers=["Content-Type"],
    )

    @app.post("/query")
    def query():
        return {"ok": True}

    with TestClient(app) as client:
        denied = client.options(
            "/query",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        allowed = client.options(
            "/query",
            headers={
                "Origin": "http://localhost:8018",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert denied.status_code == 400
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8018"


def test_public_corpus_detail_does_not_disclose_server_paths_or_keys():
    class CorpusService:
        def get_corpus_metadata(self, corpus_id):
            return {
                "corpus_id": corpus_id,
                "description": "demo",
                "config": {
                    "source_path": "D:/private/library",
                    "models": {
                        "embeddings": {"provider": "openai", "api_key": "not-for-clients"},
                    },
                },
            }

    class VectorService:
        def get_count(self, corpus_id):
            return 7

    app = FastAPI()
    app.include_router(corpora.router, prefix="/api")
    app.dependency_overrides[corpora.get_corpus_service] = CorpusService
    app.dependency_overrides[corpora.get_vector_service] = VectorService
    with TestClient(app) as client:
        response = client.get("/api/corpora/demo")

    assert response.status_code == 200
    config = response.json()["config"]
    assert "source_path" not in config
    assert "api_key" not in config["models"]["embeddings"]
