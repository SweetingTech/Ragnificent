"""Small, explicit security policy helpers for the Ragnificent HTTP boundary.

The service is commonly reached through an authenticated AgentsOfJazzy proxy,
but it also has a direct local API.  Browser CORS is not an authorization
mechanism, so mutating endpoints use these helpers to distinguish the
temporary loopback-only legacy path from the new authenticated source-receipt
contract.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
from typing import Iterable

from fastapi import HTTPException, Request, status


INTERNAL_TOKEN_HEADER = "X-Ragnificent-Token"

# These origins cover the documented same-machine Ragnificent and
# AgentsOfJazzy surfaces. Server-to-server calls do not rely on CORS.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:8018",
    "http://127.0.0.1:8018",
    "http://localhost:8008",
    "http://127.0.0.1:8008",
    "http://localhost:9002",
    "http://127.0.0.1:9002",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
)


def configured_cors_origins() -> list[str]:
    """Return an explicit CORS allowlist; never permit a wildcard by default."""
    raw = os.getenv("RAGNIFICENT_CORS_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)

    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    if "*" in origins:
        # A wildcard would turn an accidental environment setting into a broad
        # browser-access regression. Falling back to the safe defaults is less
        # surprising than silently accepting it.
        return list(DEFAULT_CORS_ORIGINS)
    return list(dict.fromkeys(origins))


def internal_token_configured() -> bool:
    return bool(os.getenv("RAGNIFICENT_INTERNAL_TOKEN", "").strip())


def _expected_internal_token() -> str:
    return os.getenv("RAGNIFICENT_INTERNAL_TOKEN", "").strip()


def _provided_token(request: Request) -> str:
    return request.headers.get(INTERNAL_TOKEN_HEADER, "").strip()


def _valid_internal_token(request: Request) -> bool:
    expected = _expected_internal_token()
    provided = _provided_token(request)
    return bool(expected and provided and hmac.compare_digest(provided, expected))


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _request_is_loopback(request: Request) -> bool:
    client = request.client
    return _is_loopback(client.host if client else None)


async def require_source_receipt_token(request: Request) -> None:
    """Fail closed for the new source-receipt API, including localhost."""
    if not internal_token_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Source receipt intake is disabled until RAGNIFICENT_INTERNAL_TOKEN is configured.",
        )
    if not _valid_internal_token(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Ragnificent internal token.",
        )


async def require_legacy_mutation_access(request: Request) -> None:
    """Protect legacy mutation routes while preserving the documented local path.

    In compatibility mode, unauthenticated mutations are accepted only from
    loopback.  Setting ``RAGNIFICENT_REQUIRE_INTERNAL_AUTH=true`` upgrades the
    same routes to token-only access, including loopback callers.  A valid
    token is always accepted so a trusted reverse proxy or container caller
    can migrate before strict mode is enabled.
    """
    strict = os.getenv("RAGNIFICENT_REQUIRE_INTERNAL_AUTH", "false").strip().lower() == "true"
    if _valid_internal_token(request):
        return
    if strict:
        if not internal_token_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Legacy mutation strict mode requires RAGNIFICENT_INTERNAL_TOKEN.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Ragnificent internal token.",
        )
    if _request_is_loopback(request):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Legacy mutation endpoints are loopback-only until an internal token is supplied.",
    )


def allowed_query_model_overrides() -> set[str]:
    """Return the explicit HTTP model-override allowlist.

    An empty list intentionally disables overrides.  The configured corpus or
    global profile remains the normal route; callers cannot turn the query API
    into an arbitrary model selector.
    """
    raw = os.getenv("RAGNIFICENT_ALLOWED_QUERY_MODEL_OVERRIDES", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def validate_query_model_override(model: str | None) -> None:
    if not model or not model.strip():
        return
    if model.strip() not in allowed_query_model_overrides():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="llm_model overrides are disabled unless explicitly allowlisted by RAGNIFICENT_ALLOWED_QUERY_MODEL_OVERRIDES.",
        )


def redact_configured_origins(origins: Iterable[str]) -> list[str]:
    """A tiny named helper used by status/docs code without exposing env text."""
    return list(origins)
