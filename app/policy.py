"""Corpus privacy and model-route policy.

``local_only`` is deliberately narrow: it allows only Ollama-backed embedding
and answer routes.  It does not infer locality from an arbitrary OpenAI-
compatible URL, because that would make an external route look local based on
caller-provided text.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal, Mapping


PRIVACY_LEVELS = {"internal", "restricted", "local_only"}
LOCAL_PROVIDER = "ollama"
WikiPublication = Literal["private_wiki_allowed", "local_only"]
WIKI_PUBLICATION_PRIVATE_WIKI_ALLOWED: WikiPublication = "private_wiki_allowed"
WIKI_PUBLICATION_LOCAL_ONLY: WikiPublication = "local_only"

# Repository documentation is intentionally a separate corpus from historical
# AAR/task memory.  These values are a narrow contract shared with the Voltron
# documentation catalog; callers cannot select a broad source root or turn an
# arbitrary corpus into a repository-docs corpus by request payload alone.
REPOSITORY_DOCS_CORPUS_ID = "voltron-repository-docs"
REPOSITORY_DOCS_ROOT_ID = "voltron_repository_docs"
REPOSITORY_DOCS_SOURCE_KIND = "repository_documentation"
REPOSITORY_DOCS_SOURCE_SYSTEM = "voltron_documentation_catalog"
REPOSITORY_DOCS_POLICY_PROFILE = "voltron_repository_docs_v1"

# A repository can be a legacy registered ID (``Agent_Harness_Template``) or
# a canonical GitHub-style owner/repository pair (``SweetingTech/voltron``).
# Do not accept arbitrary nested paths, dots by themselves, or traversal.
_REPOSITORY_SEGMENT = r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}"
_REPOSITORY_ID_PATTERN = re.compile(
    rf"^{_REPOSITORY_SEGMENT}(?:/{_REPOSITORY_SEGMENT})?$"
)
_GIT_COMMIT_PATTERN = re.compile(r"^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$")


class PolicyViolation(ValueError):
    """Raised before a prohibited provider receives protected content."""


def normalize_privacy(value: object, *, default: str = "internal") -> str:
    privacy = str(value or default).strip().lower()
    if privacy not in PRIVACY_LEVELS:
        raise PolicyViolation(
            "privacy must be one of: internal, restricted, local_only"
        )
    return privacy


def assert_provider_allowed(privacy: str, provider: object, role: str) -> None:
    if normalize_privacy(privacy) != "local_only":
        return
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider != LOCAL_PROVIDER:
        raise PolicyViolation(
            f"local_only corpus policy forbids cloud {role} provider "
            f"'{normalized_provider or 'unset'}'; configure Ollama instead."
        )


def corpus_privacy(corpus_config: Mapping[str, Any]) -> str:
    return normalize_privacy(corpus_config.get("privacy"), default="internal")


def corpus_wiki_publication(corpus_config: Mapping[str, Any]) -> WikiPublication:
    """Return the immutable Wiki.js publication authority for a new receipt.

    This is deliberately independent of provider/model locality.  A corpus
    must opt in with the exact typed ``wiki_publication`` value and cannot be
    ``local_only``.  Everything else, including a missing or malformed value,
    fails closed to local-only publication.
    """
    if (
        corpus_privacy(corpus_config) != "local_only"
        and corpus_config.get("wiki_publication")
        == WIKI_PUBLICATION_PRIVATE_WIKI_ALLOWED
    ):
        return WIKI_PUBLICATION_PRIVATE_WIKI_ALLOWED
    return WIKI_PUBLICATION_LOCAL_ONLY


def assert_repository_documentation_receipt_policy(
    *,
    corpus_id: str,
    corpus_config: Mapping[str, Any],
    root_id: str,
    source_kind: str,
    source_system: str,
) -> bool:
    """Validate the dedicated Voltron repository-documentation receipt lane.

    The standard source-receipt API is intentionally generic.  The repository
    documentation corpus is not: it can only receive the documentation catalog
    source kind/system from its one configured snapshot root.  A corpus YAML
    opt-in is required so a caller cannot grant itself this lane merely by
    naming its corpus ID.

    Returns ``True`` only for the dedicated repository-docs corpus.  A caller
    attempting to use the docs root/kind with any other corpus is rejected to
    prevent the generated snapshot root becoming a general file-ingest mount.
    """
    is_docs_source = (
        root_id == REPOSITORY_DOCS_ROOT_ID
        or source_kind == REPOSITORY_DOCS_SOURCE_KIND
        or source_system == REPOSITORY_DOCS_SOURCE_SYSTEM
    )
    if corpus_id != REPOSITORY_DOCS_CORPUS_ID:
        if is_docs_source:
            raise PolicyViolation(
                "Repository documentation sources may only target the approved "
                "voltron-repository-docs corpus."
            )
        return False

    policy = corpus_config.get("source_receipt_policy")
    if not isinstance(policy, Mapping):
        raise PolicyViolation(
            "The voltron-repository-docs corpus requires an explicit source receipt policy."
        )
    expected = {
        "profile": REPOSITORY_DOCS_POLICY_PROFILE,
        "trusted_root_id": REPOSITORY_DOCS_ROOT_ID,
        "source_kind": REPOSITORY_DOCS_SOURCE_KIND,
        "source_system": REPOSITORY_DOCS_SOURCE_SYSTEM,
    }
    if any(policy.get(key) != value for key, value in expected.items()):
        raise PolicyViolation(
            "The voltron-repository-docs corpus source receipt policy is not the approved profile."
        )
    if (
        root_id != REPOSITORY_DOCS_ROOT_ID
        or source_kind != REPOSITORY_DOCS_SOURCE_KIND
        or source_system != REPOSITORY_DOCS_SOURCE_SYSTEM
    ):
        raise PolicyViolation(
            "Repository documentation receipts must use the approved root, kind, and source system."
        )
    return True


def normalize_repository_documentation_provenance(
    value: object,
    *,
    content_sha256: str,
) -> dict[str, str]:
    """Validate the immutable citation fields for a repository-docs receipt.

    The documentation catalog has already selected an allowlisted README/docs
    file and written a generated snapshot.  RAGnificent records enough safe
    identity to cite the canonical source without exposing that snapshot's
    local filesystem path.
    """
    if not isinstance(value, Mapping):
        raise PolicyViolation(
            "Repository documentation receipts require documentation_provenance."
        )
    expected_keys = {"repository", "path", "git_commit"}
    if set(value.keys()) != expected_keys:
        raise PolicyViolation(
            "documentation_provenance must contain only repository, path, and git_commit."
        )

    repository = str(value.get("repository") or "").strip()
    if not _REPOSITORY_ID_PATTERN.fullmatch(repository):
        raise PolicyViolation(
            "documentation_provenance.repository must be a registered ID or a safe owner/repository pair."
        )

    raw_path = str(value.get("path") or "").strip().replace("\\", "/")
    path = PurePosixPath(raw_path)
    windows_path = PureWindowsPath(raw_path)
    if (
        not raw_path
        or len(raw_path) > 512
        or path.is_absolute()
        or windows_path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or path.suffix.lower() != ".md"
    ):
        raise PolicyViolation(
            "documentation_provenance.path must be a relative Markdown path inside its repository."
        )

    git_commit = str(value.get("git_commit") or "").strip().lower()
    if not _GIT_COMMIT_PATTERN.fullmatch(git_commit):
        raise PolicyViolation(
            "documentation_provenance.git_commit must be a full 40- or 64-character Git commit hash."
        )

    return {
        "repository": repository,
        "path": path.as_posix(),
        "git_commit": git_commit,
        # The receipt-level hash is the authoritative file identity.  Repeating
        # it in the provenance bundle keeps citations self-contained.
        "content_sha256": content_sha256.lower(),
    }


def assert_corpus_model_policy(
    corpus_config: Mapping[str, Any],
    *,
    default_embedding_provider: object,
    default_answer_provider: object,
) -> str:
    """Validate the routes that can receive corpus content and return privacy."""
    privacy = corpus_privacy(corpus_config)
    models = corpus_config.get("models") if isinstance(corpus_config.get("models"), Mapping) else {}
    embeddings = models.get("embeddings") if isinstance(models.get("embeddings"), Mapping) else {}
    answer = models.get("answer") if isinstance(models.get("answer"), Mapping) else {}
    assert_provider_allowed(
        privacy,
        embeddings.get("provider", default_embedding_provider),
        "embedding",
    )
    assert_provider_allowed(
        privacy,
        answer.get("provider", default_answer_provider),
        "answer",
    )
    return privacy
