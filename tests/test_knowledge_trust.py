from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from pydantic import ValidationError

from app.api.query_engine import QueryEngine
from app.api.routes.source_receipts import SourceReceiptCreateRequest
from app.knowledge_trust import (
    KnowledgeTrustViolation,
    derive_receipt_knowledge_class,
    validate_redacted_private_attestation,
)


class _Hit:
    def __init__(self, identifier: str, score: float, knowledge_class: str):
        self.id = identifier
        self.score = score
        self.payload = {
            "corpus_id": "operator-memory",
            "text": identifier,
            "knowledge_class": knowledge_class,
        }


class _VectorService:
    def search(self, corpus_id, vector, limit=5):
        assert corpus_id == "operator-memory"
        return [
            _Hit("active", 0.99, "active_experiment"),
            _Hit("rejected", 0.98, "rejected_experiment"),
            _Hit("unverified", 0.97, "unverified"),
            _Hit("validated", 0.50, "validated_lesson"),
            _Hit("por", 0.20, "por"),
        ]


class _Embedder:
    def embed(self, values):
        return [[0.1, 0.2]]


def test_query_defaults_to_server_derived_trust_order_and_excludes_experiments():
    engine = QueryEngine(vector_service=_VectorService(), embedder=_Embedder(), default_llm=None)

    result = engine.query("what is current truth", corpus_id="operator-memory", generate_answer=False)

    assert [hit["id"] for hit in result["hits"]] == ["por", "validated", "unverified"]
    assert result["trust"] == {
        "profile": "server_derived_trust_v1",
        "include_experimental": False,
        "excluded": {"active_experiment": 1, "rejected_experiment": 1},
    }


def test_query_can_explicitly_include_experiment_history_without_upgrading_it():
    engine = QueryEngine(vector_service=_VectorService(), embedder=_Embedder(), default_llm=None)

    result = engine.query(
        "show experiment history",
        corpus_id="operator-memory",
        generate_answer=False,
        include_experimental=True,
    )

    assert [hit["id"] for hit in result["hits"]] == [
        "por",
        "validated",
        "unverified",
        "active",
        "rejected",
    ]
    assert result["hits"][-1]["payload"]["knowledge_class"] == "rejected_experiment"


def test_generic_receipt_request_cannot_self_assign_knowledge_class():
    with pytest.raises(ValidationError):
        SourceReceiptCreateRequest.model_validate(
            {
                "workspace_id": "workspace",
                "corpus_id": "operator-memory",
                "source_kind": "aar",
                "source_system": "agent_harness",
                "source_locator": {"root_id": "managed_library", "relative_path": "lesson.md"},
                "content_sha256": "a" * 64,
                "privacy": "internal",
                "idempotency_key": "receipt-key",
                "knowledge_class": "por",
            }
        )


def test_policy_never_mints_privileged_class_from_source_tuple():
    policy = {
        "knowledge_trust_policy": {
            "profile": "ragnificent.knowledge_trust.v1",
            "sources": [
                {
                    "root_id": "managed_library",
                    "source_kind": "aar",
                    "source_system": "agent_harness",
                    "knowledge_class": "por",
                },
                {
                    "root_id": "managed_library",
                    "source_kind": "receipt",
                    "source_system": "agent_harness",
                    "knowledge_class": "operational_evidence",
                },
            ],
        }
    }

    assert derive_receipt_knowledge_class(
        corpus_id="operator-memory",
        corpus_config=policy,
        root_id="managed_library",
        source_kind="aar",
        source_system="agent_harness",
    ) == "unverified"
    assert derive_receipt_knowledge_class(
        corpus_id="operator-memory",
        corpus_config=policy,
        root_id="managed_library",
        source_kind="receipt",
        source_system="agent_harness",
    ) == "operational_evidence"


def _canonical_private_attestation(key: str, **overrides):
    attestation = {
        "schemaVersion": "voltron.experiment_evaluation_attestation.v1",
        "attestationId": "attestation:1",
        "experimentId": "experiment:1",
        "candidateId": "candidate:1",
        "candidateDigest": "a" * 64,
        "correlationId": "correlation:1",
        "lane": "private",
        "status": "passed",
        "categories": [
            {"name": "safety", "status": "passed"},
            {"name": "regression", "status": "passed"},
        ],
        "usage": {"toolCalls": 2, "budgetExceeded": False},
        "rewardHackingSignals": [],
        "evidenceHash": "b" * 64,
        "issuedAt": "2026-07-17T00:00:00Z",
        "issuer": "jazzymonitor.private-evaluator",
        "keyId": "private-eval-v1",
    }
    attestation.update(overrides)
    attestation["signature"] = hmac.new(
        key.encode("utf-8"),
        json.dumps(attestation, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return attestation


def test_private_attestation_rejects_nested_hidden_case_detail_before_use():
    with pytest.raises(KnowledgeTrustViolation, match="categories must be aggregate"):
        validate_redacted_private_attestation(
            _canonical_private_attestation(
                "test-key",
                categories=[{"name": "hidden_case", "status": "passed"}],
            ),
            signing_key="test-key",
        )


def test_redacted_private_attestation_is_hmac_verifiable_without_private_payloads():
    key = "monitor-test-key"
    attestation = _canonical_private_attestation(key)

    verified = validate_redacted_private_attestation(attestation, signing_key=key)

    assert verified["experimentId"] == "experiment:1"
    assert verified["status"] == "passed"
    assert "hidden_cases" not in verified
    assert {"schema_version", "policy_hash", "category_results", "attested_at"}.isdisjoint(verified)


def test_private_attestation_rejects_legacy_monitor_snake_case_dialect():
    with pytest.raises(KnowledgeTrustViolation, match="canonical redacted wire format"):
        validate_redacted_private_attestation(
            {
                "schema_version": "voltron.self_improvement_experiment.v1",
                "attestation_id": "attestation:1",
            },
            signing_key="test-key",
        )
