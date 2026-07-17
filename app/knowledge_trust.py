"""Server-derived knowledge trust and experiment-provenance policy.

This module deliberately treats a source receipt as evidence, not authority.
The public receipt API never accepts a trust class.  Low-risk classes can be
derived from administrator-owned corpus policy; privileged classes (``por``
and ``validated_lesson``) require a separately signed, redacted experiment
attestation plus an operator approval receipt through the service boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any


EXPERIMENT_EVALUATION_ATTESTATION_SCHEMA_VERSION = "voltron.experiment_evaluation_attestation.v1"
KNOWLEDGE_TRUST_POLICY_VERSION = "ragnificent.knowledge_trust.v1"

KNOWLEDGE_CLASSES = frozenset(
    {
        "por",
        "validated_lesson",
        "operational_evidence",
        "active_experiment",
        "promoted_experiment",
        "rejected_experiment",
        "historical_document",
        "unverified",
    }
)
PRIVILEGED_KNOWLEDGE_CLASSES = frozenset({"por", "validated_lesson"})
DEFAULT_EXCLUDED_KNOWLEDGE_CLASSES = frozenset({"active_experiment", "rejected_experiment"})
KNOWLEDGE_TRUST_RANK = {
    "por": 0,
    "validated_lesson": 1,
    "operational_evidence": 2,
    "promoted_experiment": 3,
    "historical_document": 4,
    "unverified": 5,
    "active_experiment": 6,
    "rejected_experiment": 7,
}

_REPOSITORY_DOCS_CORPUS_ID = "voltron-repository-docs"
_REPOSITORY_DOCS_ROOT_ID = "voltron_repository_docs"
_REPOSITORY_DOCS_SOURCE_KIND = "repository_documentation"
_REPOSITORY_DOCS_SOURCE_SYSTEM = "voltron_documentation_catalog"
_ATTESTATION_ALLOWED_KEYS = frozenset(
    {
        "schemaVersion",
        "attestationId",
        "experimentId",
        "candidateId",
        "candidateDigest",
        "correlationId",
        "lane",
        "status",
        "categories",
        "usage",
        "rewardHackingSignals",
        "evidenceHash",
        "issuedAt",
        "issuer",
        "signature",
        "keyId",
    }
)
_ATTESTATION_REQUIRED_KEYS = frozenset(
    {
        "schemaVersion",
        "attestationId",
        "experimentId",
        "candidateId",
        "candidateDigest",
        "correlationId",
        "lane",
        "status",
        "categories",
        "usage",
        "rewardHackingSignals",
        "evidenceHash",
        "issuedAt",
        "issuer",
        "signature",
        "keyId",
    }
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_HEX_DIGEST = re.compile(r"^[a-fA-F0-9]{32,128}$")
_SAFE_CATEGORY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_USAGE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
_FORBIDDEN_CATEGORY_TOKENS = ("case", "prompt", "answer", "log", "transcript", "input", "output")
_ALLOWED_CATEGORY_STATUSES = frozenset({"passed", "failed", "not_run", "inconclusive"})
_ALLOWED_ATTESTATION_STATUSES = frozenset({"passed", "failed", "unavailable", "inconclusive"})
_ALLOWED_REWARD_HACKING_SIGNALS = frozenset(
    {
        "fabricated_evidence",
        "missing_tool_receipt",
        "suppressed_error",
        "skipped_verification",
        "approval_bypass",
        "gate_removal",
        "cost_masking",
        "test_evasion",
        "context_poisoning",
        "public_private_mismatch",
    }
)


class KnowledgeTrustViolation(ValueError):
    """Raised when trust or private-evaluation evidence is not safe to use."""


def normalize_knowledge_class(value: object, *, default: str = "unverified") -> str:
    candidate = str(value or default).strip().lower()
    if candidate not in KNOWLEDGE_CLASSES:
        return default
    return candidate


def knowledge_trust_rank(value: object) -> int:
    return KNOWLEDGE_TRUST_RANK[normalize_knowledge_class(value)]


def derive_receipt_knowledge_class(
    *,
    corpus_id: str,
    corpus_config: Mapping[str, Any],
    root_id: str,
    source_kind: str,
    source_system: str,
) -> str:
    """Return a non-privileged, server-derived class for a new receipt.

    A request can name a source kind/system but cannot name its class.  The
    exact root/kind/system tuple must match administrator-owned corpus config.
    Privileged current-truth classes are intentionally unavailable here.
    """
    if (
        corpus_id == _REPOSITORY_DOCS_CORPUS_ID
        and root_id == _REPOSITORY_DOCS_ROOT_ID
        and source_kind == _REPOSITORY_DOCS_SOURCE_KIND
        and source_system == _REPOSITORY_DOCS_SOURCE_SYSTEM
    ):
        return "historical_document"

    policy = corpus_config.get("knowledge_trust_policy")
    if not isinstance(policy, Mapping) or policy.get("profile") != KNOWLEDGE_TRUST_POLICY_VERSION:
        return "unverified"
    sources = policy.get("sources")
    if not isinstance(sources, list):
        return "unverified"
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        if (
            source.get("root_id") != root_id
            or source.get("source_kind") != source_kind
            or source.get("source_system") != source_system
        ):
            continue
        derived = normalize_knowledge_class(source.get("knowledge_class"))
        # The generic receipt boundary must never mint a privileged class.
        if derived not in PRIVILEGED_KNOWLEDGE_CLASSES:
            return derived
    return "unverified"


def _canonical_attestation_payload(attestation: Mapping[str, Any]) -> bytes:
    payload = {key: attestation[key] for key in sorted(attestation) if key != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _safe_attestation_identifier(value: object, *, field: str) -> str:
    normalized = str(value or "")
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise KnowledgeTrustViolation(f"Canonical private attestation has an invalid {field}.")
    return normalized


def _safe_attestation_digest(value: object, *, field: str) -> str:
    normalized = str(value or "")
    if not _HEX_DIGEST.fullmatch(normalized):
        raise KnowledgeTrustViolation(f"Canonical private attestation has an invalid {field}.")
    return normalized


def _safe_attestation_usage(value: object) -> dict[str, int | float | bool]:
    if not isinstance(value, Mapping) or len(value) > 32:
        raise KnowledgeTrustViolation("Canonical private attestation usage must be a compact object.")
    normalized: dict[str, int | float | bool] = {}
    for key, usage in value.items():
        if not _SAFE_USAGE_KEY.fullmatch(str(key)):
            raise KnowledgeTrustViolation("Canonical private attestation usage has an invalid key.")
        if isinstance(usage, bool):
            normalized[str(key)] = usage
        elif isinstance(usage, (int, float)) and math.isfinite(usage):
            normalized[str(key)] = usage
        else:
            raise KnowledgeTrustViolation(
                "Canonical private attestation usage must contain numeric or boolean values."
            )
    return normalized


def _safe_attestation_categories(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 32:
        raise KnowledgeTrustViolation("Canonical private attestation categories must be a compact list.")
    normalized: list[dict[str, str]] = []
    for category in value:
        if not isinstance(category, Mapping) or not {"name", "status"}.issubset(category):
            raise KnowledgeTrustViolation("Canonical private attestation categories are incomplete.")
        if set(category) - {"name", "status", "summary"}:
            raise KnowledgeTrustViolation("Canonical private attestation categories contain unsupported detail.")
        # Root permits a summary for general evaluations.  The private trust
        # lane narrows that optional field away so a test body cannot be
        # smuggled through as apparently harmless prose.
        if "summary" in category:
            raise KnowledgeTrustViolation(
                "Canonical private attestation categories may not contain a summary."
            )
        name = str(category.get("name") or "")
        status = str(category.get("status") or "")
        if (
            not _SAFE_CATEGORY.fullmatch(name)
            or any(token in name for token in _FORBIDDEN_CATEGORY_TOKENS)
            or status not in _ALLOWED_CATEGORY_STATUSES
        ):
            raise KnowledgeTrustViolation(
                "Canonical private attestation categories must be aggregate results."
            )
        normalized.append({"name": name, "status": status})
    return normalized


def _safe_attestation_signals(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 32:
        raise KnowledgeTrustViolation("Canonical private attestation signals must be a compact list.")
    normalized = [str(signal) for signal in value]
    if any(signal not in _ALLOWED_REWARD_HACKING_SIGNALS for signal in normalized):
        raise KnowledgeTrustViolation("Canonical private attestation has an unknown reward-hacking signal.")
    return normalized


def validate_redacted_private_attestation(
    attestation: Mapping[str, Any],
    *,
    signing_key: str,
) -> dict[str, Any]:
    """Parse and verify only the canonical redacted Monitor attestation.

    Trust promotion accepts the root-schema-compatible
    ``voltron.experiment_evaluation_attestation.v1`` camel-case payload only.
    The older Monitor snake-case implementation record is deliberately not a
    wire dialect here.  This receiver is not a private-test runner and rejects
    all caller-supplied narrative/category detail before any trust state is
    changed.
    """
    if not signing_key:
        raise KnowledgeTrustViolation("Private-evaluation attestation verification is not configured.")
    if not isinstance(attestation, Mapping):
        raise KnowledgeTrustViolation("Private-evaluation attestation must be an object.")
    keys = set(attestation.keys())
    if not keys.issubset(_ATTESTATION_ALLOWED_KEYS):
        raise KnowledgeTrustViolation(
            "Private-evaluation attestation is not the canonical redacted wire format."
        )
    if not _ATTESTATION_REQUIRED_KEYS.issubset(keys):
        raise KnowledgeTrustViolation("Canonical private attestation is incomplete.")
    if attestation.get("schemaVersion") != EXPERIMENT_EVALUATION_ATTESTATION_SCHEMA_VERSION:
        raise KnowledgeTrustViolation("Private-evaluation attestation uses an unsupported schema version.")
    if attestation.get("lane") != "private":
        raise KnowledgeTrustViolation("Knowledge trust promotion requires a private evaluation attestation.")
    status = str(attestation.get("status") or "")
    if status not in _ALLOWED_ATTESTATION_STATUSES:
        raise KnowledgeTrustViolation("Canonical private attestation has an invalid status.")
    issued_at_raw = str(attestation.get("issuedAt") or "")
    try:
        issued_at = datetime.fromisoformat(issued_at_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeTrustViolation("Private-evaluation attestation has an invalid timestamp.") from exc
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise KnowledgeTrustViolation("Private-evaluation attestation timestamp must be timezone-aware.")

    normalized: dict[str, Any] = {
        "schemaVersion": EXPERIMENT_EVALUATION_ATTESTATION_SCHEMA_VERSION,
        "attestationId": _safe_attestation_identifier(attestation.get("attestationId"), field="attestationId"),
        "experimentId": _safe_attestation_identifier(attestation.get("experimentId"), field="experimentId"),
        "candidateId": _safe_attestation_identifier(attestation.get("candidateId"), field="candidateId"),
        "candidateDigest": _safe_attestation_digest(attestation.get("candidateDigest"), field="candidateDigest"),
        "correlationId": _safe_attestation_identifier(attestation.get("correlationId"), field="correlationId"),
        "lane": "private",
        "status": status,
        "categories": _safe_attestation_categories(attestation.get("categories")),
        "usage": _safe_attestation_usage(attestation.get("usage")),
        "rewardHackingSignals": _safe_attestation_signals(attestation.get("rewardHackingSignals")),
        "evidenceHash": _safe_attestation_digest(attestation.get("evidenceHash"), field="evidenceHash"),
        "issuedAt": issued_at_raw,
        "issuer": _safe_attestation_identifier(attestation.get("issuer"), field="issuer"),
        "keyId": _safe_attestation_identifier(attestation.get("keyId"), field="keyId"),
        "signature": _safe_attestation_digest(attestation.get("signature"), field="signature"),
    }
    expected = hmac.new(
        signing_key.encode("utf-8"), _canonical_attestation_payload(normalized), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, normalized["signature"]):
        raise KnowledgeTrustViolation("Private-evaluation attestation signature is invalid.")
    # Persist the normalized canonical form only; never return a legacy alias
    # that a later caller could mistake for a second supported wire format.
    return normalized
