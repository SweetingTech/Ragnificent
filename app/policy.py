"""Corpus privacy and model-route policy.

``local_only`` is deliberately narrow: it allows only Ollama-backed embedding
and answer routes.  It does not infer locality from an arbitrary OpenAI-
compatible URL, because that would make an external route look local based on
caller-provided text.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping


PRIVACY_LEVELS = {"internal", "restricted", "local_only"}
LOCAL_PROVIDER = "ollama"
WikiPublication = Literal["private_wiki_allowed", "local_only"]
WIKI_PUBLICATION_PRIVATE_WIKI_ALLOWED: WikiPublication = "private_wiki_allowed"
WIKI_PUBLICATION_LOCAL_ONLY: WikiPublication = "local_only"


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
