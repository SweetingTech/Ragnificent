"""Durable, root-anchored source receipts for governed ingestion.

The receipt is intentionally separate from a corpus definition.  A caller
names a configured logical root and a relative locator; it never supplies an
arbitrary path, provider, model, base URL, or API key.  That gives Agent
Harness a stable provenance record to attach to a claim/evidence relationship.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from ..config.schema import GlobalConfig
from ..policy import (
    PolicyViolation,
    WIKI_PUBLICATION_LOCAL_ONLY,
    WIKI_PUBLICATION_PRIVATE_WIKI_ALLOWED,
    assert_corpus_model_policy,
    corpus_privacy,
    corpus_wiki_publication,
    normalize_privacy,
)
from ..services.corpus_service import CorpusService
from ..state.db import Database
from ..utils.hashing import hash_file


ROOT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class SourceReceiptError(ValueError):
    """A safe validation error suitable for an authenticated caller."""


class SourceReceiptNotFound(SourceReceiptError):
    pass


@dataclass(frozen=True)
class ResolvedSourceLocator:
    root_id: str
    relative_path: str
    path: Path


def _safe_root_mapping(config: GlobalConfig) -> dict[str, Path]:
    """Resolve configured roots, with a small safe default under library_root."""
    raw = os.getenv("RAGNIFICENT_TRUSTED_SOURCE_ROOTS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SourceReceiptError("RAGNIFICENT_TRUSTED_SOURCE_ROOTS must be a JSON object.") from exc
        if not isinstance(data, dict) or not data:
            raise SourceReceiptError("RAGNIFICENT_TRUSTED_SOURCE_ROOTS must be a non-empty JSON object.")
        raw_roots = data
    else:
        library_root = Path(config.library_root)
        raw_roots = {
            "managed_library": str(library_root),
            "agent_harness_aar_sources": str(library_root / "agent_harness_aar_sources"),
        }

    roots: dict[str, Path] = {}
    for root_id, value in raw_roots.items():
        if not isinstance(root_id, str) or not ROOT_ID_PATTERN.fullmatch(root_id):
            raise SourceReceiptError("Configured source root IDs must be simple alphanumeric, dash, or underscore names.")
        if not isinstance(value, str) or not value.strip():
            raise SourceReceiptError(f"Configured source root '{root_id}' is empty.")
        roots[root_id] = Path(value).expanduser().resolve()
    return roots


def resolve_source_locator(
    config: GlobalConfig,
    *,
    root_id: str,
    relative_path: str,
) -> ResolvedSourceLocator:
    roots = _safe_root_mapping(config)
    if root_id not in roots:
        raise SourceReceiptError("Unknown trusted source root.")

    raw_relative = relative_path.strip().replace("\\", "/")
    if not raw_relative:
        raise SourceReceiptError("source_locator.relative_path is required.")
    posix = PurePosixPath(raw_relative)
    windows = PureWindowsPath(raw_relative)
    if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or "." in posix.parts:
        raise SourceReceiptError("source_locator.relative_path must be a relative path inside its configured root.")

    root = roots[root_id]
    candidate = (root / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SourceReceiptError("source locator escapes its configured root.") from exc
    if not candidate.exists() or not candidate.is_file():
        raise SourceReceiptError("The resolved source locator does not identify a file.")
    return ResolvedSourceLocator(
        root_id=root_id,
        relative_path=posix.as_posix(),
        path=candidate,
    )


def _model_policy_for_corpus(config: GlobalConfig, corpus_config: Mapping[str, Any]) -> dict[str, str]:
    default_answer = config.models.answer
    privacy = assert_corpus_model_policy(
        corpus_config,
        default_embedding_provider=config.models.embeddings.provider,
        default_answer_provider=default_answer.provider if default_answer else "ollama",
    )
    models = corpus_config.get("models") if isinstance(corpus_config.get("models"), Mapping) else {}
    embeddings = models.get("embeddings") if isinstance(models.get("embeddings"), Mapping) else {}
    answer = models.get("answer") if isinstance(models.get("answer"), Mapping) else {}
    return {
        "privacy": privacy,
        "embedding_provider": str(embeddings.get("provider", config.models.embeddings.provider)),
        "embedding_model": str(embeddings.get("model", config.models.embeddings.model)),
        "answer_provider": str(answer.get("provider", default_answer.provider if default_answer else "ollama")),
        "answer_model": str(answer.get("model", default_answer.model if default_answer else "llama3")),
    }


def _canonical_locator(receipt_id: str) -> str:
    return f"ragnificent://source-receipts/{receipt_id}"


def ensure_source_receipts_schema(db: Database) -> None:
    """Backfill the immutable Wiki publication field on existing SQLite DBs.

    ``CREATE TABLE IF NOT EXISTS`` cannot add fields to an already-created
    table.  Legacy receipts therefore receive the most restrictive value when
    this compatibility migration first runs.  New rows use the schema-level
    default/check as a second line of defense.
    """
    with db.transaction() as conn:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(source_receipts)").fetchall()
        }
        if not columns:
            # The normal schema initialization owns table creation.  Avoid
            # creating a partial database if this service is used too early.
            return
        if "wiki_publication" not in columns:
            conn.execute(
                """
                ALTER TABLE source_receipts
                ADD COLUMN wiki_publication TEXT NOT NULL DEFAULT 'local_only'
                CHECK (wiki_publication IN ('private_wiki_allowed', 'local_only'))
                """
            )
        conn.execute(
            """
            UPDATE source_receipts
            SET wiki_publication = ?
            WHERE wiki_publication IS NULL
               OR wiki_publication NOT IN (?, ?)
            """,
            (
                WIKI_PUBLICATION_LOCAL_ONLY,
                WIKI_PUBLICATION_PRIVATE_WIKI_ALLOWED,
                WIKI_PUBLICATION_LOCAL_ONLY,
            ),
        )


def _row_to_record(row: Any) -> dict[str, Any]:
    if row is None:
        raise SourceReceiptNotFound("Source receipt was not found.")
    summary = None
    if row["ingest_summary_json"]:
        try:
            summary = json.loads(row["ingest_summary_json"])
        except (TypeError, json.JSONDecodeError):
            summary = {"status": "unavailable"}
    try:
        wiki_publication = row["wiki_publication"]
    except (IndexError, KeyError):
        # Compatibility safety for callers that inspect a DB before the
        # startup migration has run.  Do not infer authority from corpus YAML.
        wiki_publication = WIKI_PUBLICATION_LOCAL_ONLY
    if wiki_publication not in {
        WIKI_PUBLICATION_PRIVATE_WIKI_ALLOWED,
        WIKI_PUBLICATION_LOCAL_ONLY,
    }:
        wiki_publication = WIKI_PUBLICATION_LOCAL_ONLY
    return {
        "receipt_id": row["receipt_id"],
        "canonical_locator": _canonical_locator(row["receipt_id"]),
        "workspace_id": row["workspace_id"],
        "corpus_id": row["corpus_id"],
        "source_kind": row["source_kind"],
        "source_system": row["source_system"],
        "source_record_id": row["source_record_id"],
        "source_locator": {
            "root_id": row["locator_root_id"],
            "relative_path": row["locator_relative_path"],
        },
        "content_sha256": row["content_sha256"],
        "title": row["title"],
        "privacy": row["privacy"],
        "wiki_publication": wiki_publication,
        "correlation_id": row["correlation_id"],
        "idempotency_key": row["idempotency_key"],
        "status": row["status"],
        "received_at": row["received_at"],
        "ingested_at": row["ingested_at"],
        "indexed_file_hash": row["indexed_file_hash"],
        "ingest_summary": summary,
    }


class SourceReceiptService:
    def __init__(self, config: GlobalConfig, db: Database):
        self.config = config
        self.db = db
        ensure_source_receipts_schema(db)
        self.corpora = CorpusService(config.library_root)

    def _corpus_config(self, corpus_id: str) -> dict[str, Any]:
        metadata = self.corpora.get_corpus_metadata(corpus_id)
        if not metadata:
            raise SourceReceiptError("The requested corpus does not exist.")
        config = metadata.get("config")
        if not isinstance(config, dict):
            raise SourceReceiptError("The requested corpus has no valid configuration.")
        return config

    def _validate_privacy(self, requested_privacy: str, corpus_config: Mapping[str, Any]) -> dict[str, str]:
        requested = normalize_privacy(requested_privacy)
        configured = corpus_privacy(corpus_config)
        if requested != configured:
            raise SourceReceiptError(
                "Source receipt privacy must match the target corpus privacy policy."
            )
        try:
            return _model_policy_for_corpus(self.config, corpus_config)
        except PolicyViolation as exc:
            raise SourceReceiptError(str(exc)) from exc

    def create_receipt(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        """Validate a source and create an idempotent immutable receipt."""
        corpus_id = str(payload["corpus_id"])
        locator_payload = payload["source_locator"]
        if not isinstance(locator_payload, Mapping):
            raise SourceReceiptError("source_locator is required.")
        locator = resolve_source_locator(
            self.config,
            root_id=str(locator_payload["root_id"]),
            relative_path=str(locator_payload["relative_path"]),
        )
        observed_hash = hash_file(str(locator.path))
        supplied_hash = str(payload["content_sha256"]).lower()
        if observed_hash != supplied_hash:
            raise SourceReceiptError("The source content hash does not match the submitted receipt.")

        corpus_config = self._corpus_config(corpus_id)
        model_policy = self._validate_privacy(str(payload.get("privacy") or "internal"), corpus_config)
        wiki_publication = corpus_wiki_publication(corpus_config)
        workspace_id = str(payload["workspace_id"])
        idempotency_key = str(payload["idempotency_key"])

        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM source_receipts WHERE workspace_id = ? AND idempotency_key = ?",
                (workspace_id, idempotency_key),
            ).fetchone()
            if existing:
                existing_record = _row_to_record(existing)
                existing_values = (
                    existing_record["corpus_id"],
                    existing_record["source_locator"]["root_id"],
                    existing_record["source_locator"]["relative_path"],
                    existing_record["content_sha256"],
                    existing_record["privacy"],
                )
                requested_values = (
                    corpus_id,
                    locator.root_id,
                    locator.relative_path,
                    supplied_hash,
                    model_policy["privacy"],
                )
                if existing_values != requested_values:
                    raise SourceReceiptError(
                        "The idempotency key is already bound to a different source receipt."
                    )
                existing_record["model_policy"] = model_policy
                return existing_record, False

            receipt_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO source_receipts (
                    receipt_id, workspace_id, corpus_id, source_kind, source_system,
                    source_record_id, locator_root_id, locator_relative_path,
                    content_sha256, title, privacy, wiki_publication, correlation_id, idempotency_key,
                    status, indexed_file_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'received', ?)
                """,
                (
                    receipt_id,
                    workspace_id,
                    corpus_id,
                    str(payload["source_kind"]),
                    str(payload["source_system"]),
                    str(payload.get("source_record_id") or "") or None,
                    locator.root_id,
                    locator.relative_path,
                    supplied_hash,
                    str(payload.get("title") or "") or None,
                    model_policy["privacy"],
                    wiki_publication,
                    str(payload.get("correlation_id") or "") or None,
                    idempotency_key,
                    observed_hash,
                ),
            )
            row = conn.execute(
                "SELECT * FROM source_receipts WHERE receipt_id = ?", (receipt_id,)
            ).fetchone()
        record = _row_to_record(row)
        record["model_policy"] = model_policy
        return record, True

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        with self.db.cursor() as cursor:
            row = cursor.execute(
                "SELECT * FROM source_receipts WHERE receipt_id = ?", (receipt_id,)
            ).fetchone()
        record = _row_to_record(row)
        corpus_config = self._corpus_config(record["corpus_id"])
        record["model_policy"] = self._validate_privacy(record["privacy"], corpus_config)
        return record

    def resolve_receipt_file(self, receipt: Mapping[str, Any]) -> ResolvedSourceLocator:
        locator = receipt.get("source_locator")
        if not isinstance(locator, Mapping):
            raise SourceReceiptError("Source receipt locator is invalid.")
        resolved = resolve_source_locator(
            self.config,
            root_id=str(locator["root_id"]),
            relative_path=str(locator["relative_path"]),
        )
        actual_hash = hash_file(str(resolved.path))
        if actual_hash != receipt.get("content_sha256"):
            raise SourceReceiptError("Source content changed after its receipt was accepted.")
        return resolved

    def mark_ingested(self, receipt_id: str, summary: Mapping[str, Any]) -> dict[str, Any]:
        indexed_hash = str(summary.get("file_hash") or "") or None
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE source_receipts
                SET status = 'ingested', indexed_file_hash = COALESCE(?, indexed_file_hash),
                    ingest_summary_json = ?, ingested_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE receipt_id = ?
                """,
                (indexed_hash, json.dumps(dict(summary), sort_keys=True), receipt_id),
            )
            row = conn.execute(
                "SELECT * FROM source_receipts WHERE receipt_id = ?", (receipt_id,)
            ).fetchone()
        return _row_to_record(row)

    def mark_failed(self, receipt_id: str, error_code: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE source_receipts
                SET status = 'failed', ingest_summary_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE receipt_id = ?
                """,
                (json.dumps({"status": "failed", "error_code": error_code}), receipt_id),
            )
            row = conn.execute(
                "SELECT * FROM source_receipts WHERE receipt_id = ?", (receipt_id,)
            ).fetchone()
        return _row_to_record(row)
