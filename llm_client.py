#!/usr/bin/env python3
"""
llm_client.py

Unified LLM client: OpenRouter (e.g. arcee-ai/trinity-large-preview:free) or Google Gemini.
Use OpenRouter when OPENROUTER_API_KEY is set; otherwise use GEMINI_API_KEY.

.env options:
  OpenRouter (no Gemini key needed):
    OPENROUTER_API_KEY=sk-or-v1-...
    OPENROUTER_MODEL=arcee-ai/trinity-large-preview:free   # optional, this is the default
  Gemini:
    GEMINI_API_KEY=...
    GEMINI_MODEL=models/gemini-2.5-flash   # optional
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load repo root .env first (so one .env works when running from script folder)
_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_root / ".env")
# Then cwd so local .env can override
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "arcee-ai/trinity-large-preview:free").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash").strip()

# Prefer OpenRouter if key is set
USE_OPENROUTER = bool(OPENROUTER_API_KEY)

if USE_OPENROUTER:
    # Lazy import so Gemini deps not required when using OpenRouter only
    _client_genai = None
else:
    from google import genai
    _client_genai = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def generate_content(prompt: str) -> Optional[str]:
    """
    Send a single prompt to the configured LLM (OpenRouter or Gemini) and return the reply text.
    Returns None on failure or empty response.
    """
    if USE_OPENROUTER:
        return _generate_openrouter(prompt)
    if _client_genai:
        return _generate_gemini(prompt)
    return None


def _generate_openrouter(prompt: str) -> Optional[str]:
    import requests
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL or "arcee-ai/trinity-large-preview:free",
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=120)
        if r.status_code != 200:
            body = r.text[:300]
            msg = f"OpenRouter API error (HTTP {r.status_code}): {body}"
            print(msg)
            raise RuntimeError(msg)
        data = r.json()
        err = data.get("error")
        if err:
            msg = f"OpenRouter error: {err.get('message', err)}"
            print(msg)
            raise RuntimeError(msg)
        choices = data.get("choices")
        if not choices:
            return None
        msg = choices[0].get("message")
        if not msg:
            return None
        return (msg.get("content") or "").strip() or None
    except RuntimeError:
        raise
    except Exception as e:
        print(f"OpenRouter API error: {e}")
        raise RuntimeError(f"OpenRouter API error: {e}")


def _generate_gemini(prompt: str) -> Optional[str]:
    try:
        resp = _client_genai.models.generate_content(
            model=GEMINI_MODEL or "models/gemini-2.5-flash",
            contents=prompt,
        )
        g_text = getattr(resp, "text", None) or (
            resp.output[0].content if getattr(resp, "output", None) else None
        )
        return (g_text or "").strip() or None
    except Exception as e:
        print(f"Gemini API error: {e}")
        raise RuntimeError(f"Gemini API error: {e}")


def require_llm_config():
    """Raise ValueError if neither OpenRouter nor Gemini is configured."""
    if USE_OPENROUTER and OPENROUTER_API_KEY:
        return
    if GEMINI_API_KEY:
        return
    raise ValueError(
        "Missing LLM config. Set either OPENROUTER_API_KEY or GEMINI_API_KEY in .env"
    )
