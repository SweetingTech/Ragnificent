"""
Connection test endpoint — lets the UI verify that a provider/model combo
actually works before saving it to config.
"""
import os
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["test"])


class TestRequest(BaseModel):
    role: str          # "embedding" or "llm"
    provider: str      # ollama | openai | anthropic | openrouter
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None   # inline override; falls back to env var


def _key(provider: str, override: Optional[str]) -> str:
    if override and override.strip():
        return override.strip()
    env_map = {
        "openai":      "OPENAI_API_KEY",
        "anthropic":   "ANTHROPIC_API_KEY",
        "openrouter":  "OPENROUTER_API_KEY",
    }
    return os.getenv(env_map.get(provider, ""), "")


def _default_url(provider: str) -> str:
    return {
        "ollama":     "http://localhost:11434",
        "openai":     "https://api.openai.com/v1",
        "anthropic":  "https://api.anthropic.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }.get(provider, "")


# ---------------------------------------------------------------------------
# Per-provider test functions — each returns (ok: bool, detail: str)
# ---------------------------------------------------------------------------

def _test_ollama_embed(base_url: str, model: str):
    try:
        from ollama import Client
        Client(host=base_url).embed(model=model, input=["ping"])
        return True, f"Connected to Ollama at {base_url}. Model '{model}' responded."
    except Exception as e:
        return False, str(e)


def _test_ollama_llm(base_url: str, model: str):
    try:
        from ollama import Client
        resp = Client(host=base_url).chat(
            model=model,
            messages=[{"role": "user", "content": "Reply with one word: ready"}]
        )
        reply = resp["message"]["content"].strip()[:80]
        return True, f"Connected to Ollama at {base_url}. Model '{model}' replied: \"{reply}\""
    except Exception as e:
        return False, str(e)


def _test_openai_embed(base_url: str, model: str, api_key: str):
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": ["ping"]},
            )
        if resp.status_code == 200:
            dims = len(resp.json()["data"][0]["embedding"])
            return True, f"Connected. Model '{model}' returned {dims}-dim embeddings."
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def _test_openai_llm(base_url: str, model: str, api_key: str, provider: str = "openai"):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:8008"
    try:
        with httpx.Client(timeout=30) as client:
            base_payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with one word: ready"}],
            }
            payloads = [
                {**base_payload, "max_completion_tokens": 16},
                {**base_payload, "max_tokens": 16},
            ]
            resp = None
            for payload in payloads:
                resp = client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 200:
                    break
                body = resp.text.lower()
                unsupported_token_param = (
                    resp.status_code == 400 and
                    ("unsupported parameter" in body or "not supported" in body) and
                    ("max_tokens" in body or "max_completion_tokens" in body)
                )
                if not unsupported_token_param:
                    break
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()[:80]
            return True, f"Connected. Model '{model}' replied: \"{reply}\""
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def _test_anthropic_llm(base_url: str, model: str, api_key: str):
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{base_url.rstrip('/')}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={"model": model, "max_tokens": 10,
                      "messages": [{"role": "user", "content": "Reply with one word: ready"}]},
            )
        if resp.status_code == 200:
            reply = resp.json()["content"][0]["text"].strip()[:80]
            return True, f"Connected. Model '{model}' replied: \"{reply}\""
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/test-connection")
def test_connection(body: TestRequest):
    provider = body.provider.lower()
    role = body.role.lower()
    model = body.model.strip()
    base_url = (body.base_url or "").strip() or _default_url(provider)
    api_key = _key(provider, body.api_key)

    if not model:
        return JSONResponse({"ok": False, "detail": "No model specified."}, status_code=400)

    ok, detail = False, "Unknown provider/role combination."

    if provider == "ollama":
        if role == "embedding":
            ok, detail = _test_ollama_embed(base_url, model)
        else:
            ok, detail = _test_ollama_llm(base_url, model)

    elif provider in ("openai", "openrouter"):
        if not api_key:
            env = "OPENAI_API_KEY" if provider == "openai" else "OPENROUTER_API_KEY"
            return JSONResponse({"ok": False, "detail": f"No API key found. Set {env} in your .env file."}, status_code=200)
        if role == "embedding":
            ok, detail = _test_openai_embed(base_url, model, api_key)
        else:
            ok, detail = _test_openai_llm(base_url, model, api_key, provider)

    elif provider == "anthropic":
        if not api_key:
            return JSONResponse({"ok": False, "detail": "No API key found. Set ANTHROPIC_API_KEY in your .env file."}, status_code=200)
        if role == "embedding":
            return JSONResponse({"ok": False, "detail": "Anthropic does not offer an embeddings API. Use Ollama or OpenAI for embeddings."}, status_code=200)
        ok, detail = _test_anthropic_llm(base_url, model, api_key)

    return JSONResponse({"ok": ok, "detail": detail})
