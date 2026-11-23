"""
AI Client — provider-agnostic LLM access for ClipForge.

Supports:
  * Any OpenAI-compatible chat API (OpenAI, Groq, OpenRouter, DeepSeek,
    Ollama, LM Studio, ...) via configurable base_url.
  * The native Anthropic (Claude) Messages API.

Configuration is resolved from the settings table with environment-variable
fallbacks (CLIPFORGE_AI_PROVIDER / _API_KEY / _BASE_URL / _MODEL).
All calls go through plain HTTP (requests) — no vendor SDK required.
"""
import json
import os
import re

import requests

from config import (
    AI_DEFAULT_MODEL,
    AI_DEFAULT_PROVIDER,
    AI_ENV_KEYS,
    AI_PROVIDERS,
    AI_REQUEST_TIMEOUT,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_DEFAULT_MODEL,
    OPENAI_DEFAULT_BASE_URL,
)
from models import get_setting


class AIError(Exception):
    """Raised when an AI request cannot be completed."""


class AIConfigError(AIError):
    """Raised when the AI pipeline is not configured (e.g. missing API key)."""


def _setting(key, env_key, default=""):
    """Read a config value: settings table first, then env, then default."""
    value = get_setting(key, "")
    if value is None or str(value).strip() == "":
        value = os.environ.get(env_key, "")
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def get_ai_config():
    """
    Resolve the active AI configuration.

    Returns a dict with provider / api_key / base_url / model,
    or None when no API key is available (AI disabled).
    """
    provider = _setting("ai_provider", AI_ENV_KEYS["provider"], AI_DEFAULT_PROVIDER).lower()
    if provider not in AI_PROVIDERS:
        provider = AI_DEFAULT_PROVIDER

    api_key = _setting("ai_api_key", AI_ENV_KEYS["api_key"], "")
    if not api_key:
        return None

    default_base = (
        ANTHROPIC_BASE_URL if provider == "anthropic" else OPENAI_DEFAULT_BASE_URL
    )
    default_model = (
        ANTHROPIC_DEFAULT_MODEL if provider == "anthropic" else AI_DEFAULT_MODEL
    )
    base_url = _setting("ai_base_url", AI_ENV_KEYS["base_url"], default_base).rstrip("/")
    model = _setting("ai_model", AI_ENV_KEYS["model"], default_model)

    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def ai_enabled():
    """True when the AI pipeline is switched on AND an API key is available."""
    enabled = str(get_setting("ai_enabled", "true")).lower() in ("1", "true", "yes", "on")
    return enabled and get_ai_config() is not None


def _chat_openai(cfg, system, user, temperature, max_tokens, timeout):
    resp = requests.post(
        f"{cfg['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={
            "model": cfg["model"],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise AIError(_http_error(resp, "OpenAI-compatible"))
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        raise AIError(f"Unexpected chat response shape: {e}")


def _chat_anthropic(cfg, system, user, temperature, max_tokens, timeout):
    resp = requests.post(
        f"{cfg['base_url']}/v1/messages",
        headers={
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": cfg["model"],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise AIError(_http_error(resp, "Anthropic"))
    try:
        parts = [
            block.get("text", "")
            for block in resp.json()["content"]
            if block.get("type") == "text"
        ]
        return "".join(parts)
    except (KeyError, TypeError, ValueError) as e:
        raise AIError(f"Unexpected Anthropic response shape: {e}")


def _http_error(resp, label):
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except Exception:
        detail = ""
    if not detail:
        detail = (resp.text or "")[:300]
    return f"{label} API error (HTTP {resp.status_code}): {detail}"


def chat(system, user, temperature=0.4, max_tokens=1500, timeout=None):
    """Send a single system+user chat turn and return the model's text."""
    cfg = get_ai_config()
    if not cfg:
        raise AIConfigError("AI is not configured — set an API key in Settings.")

    timeout = timeout or AI_REQUEST_TIMEOUT
    if cfg["provider"] == "anthropic":
        return _chat_anthropic(cfg, system, user, temperature, max_tokens, timeout)
    return _chat_openai(cfg, system, user, temperature, max_tokens, timeout)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text):
    """
    Extract a JSON object or array from an LLM response.

    Handles responses wrapped in markdown fences or polluted with
    leading/trailing prose. Returns None when nothing parseable is found.
    """
    if not text:
        return None

    candidates = []
    fenced = _JSON_FENCE_RE.findall(text)
    candidates.extend(fx.strip() for fx in fenced if fx.strip())
    candidates.append(text.strip())

    # Substring fallback: first '{' to last '}' (or '[' to ']')
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            continue
    return None


def chat_json(system, user, temperature=0.4, max_tokens=1500, timeout=None):
    """
    Chat call that must return JSON.

    Parses the reply (tolerating fences/prose) and retries once with a
    corrective nudge if the first answer is not valid JSON.
    Raises AIError when no valid JSON can be obtained.
    """
    system = system.rstrip() + "\nRespond with valid JSON only — no prose, no markdown."

    first = chat(system, user, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    parsed = extract_json(first)
    if parsed is not None:
        return parsed

    retry_user = (
        "Your previous answer was not valid JSON. "
        "Return ONLY the JSON value, nothing else.\n\n" + user
    )
    second = chat(system, retry_user, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    parsed = extract_json(second)
    if parsed is None:
        raise AIError("Model did not return valid JSON after retry.")
    return parsed


def test_ai_connection():
    """
    Verify the AI configuration with a minimal live request.

    Returns (success: bool, message: str).
    """
    cfg = get_ai_config()
    if not cfg:
        return False, "No AI API key configured. Add one in Settings → AI Pipeline."

    try:
        reply = chat(
            "You are a connectivity check. Reply with exactly: OK",
            "Reply with exactly: OK",
            temperature=0.0,
            max_tokens=10,
            timeout=30,
        )
        reply = (reply or "").strip()
        if reply:
            return True, f"AI connection OK — provider '{cfg['provider']}', model '{cfg['model']}' (replied: {reply[:20]})"
        return False, "AI endpoint replied with an empty response."
    except AIConfigError as e:
        return False, str(e)
    except AIError as e:
        return False, str(e)
    except requests.RequestException as e:
        return False, f"Network error contacting AI endpoint: {e}"
