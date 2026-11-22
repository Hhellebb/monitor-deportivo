"""Capa opcional de resúmenes explicativos en español (activada solo con AI_API_KEY)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
import urllib.request

logger = logging.getLogger("ai_summary")

SYSTEM_PROMPT = (
    "Genera una justificación sintética de máximo 2 oraciones en español que explique "
    "por qué este pronóstico destaca estadísticamente. Usa un tono objetivo, sin modismos "
    "y sin inventar datos que no estén en el JSON recibido."
)


def generate_short_reason(payload: dict[str, Any]) -> str | None:
    """Genera una explicación breve (<=2 oraciones) si `AI_API_KEY` está configurada.

    Soporta Gemini (`AI_PROVIDER=gemini`, por defecto) y Claude (`AI_PROVIDER=claude`).
    Si `AI_API_KEY` no existe o la API falla, devuelve None sin interrumpir el pipeline.
    """
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        return None

    provider = os.environ.get("AI_PROVIDER", "gemini").strip().lower()
    user_content = json.dumps(payload, ensure_ascii=False)

    try:
        if provider == "claude":
            return _call_claude(api_key, user_content)
        return _call_gemini(api_key, user_content)
    except Exception as exc:
        logger.warning("Resumen con IA omitido por error (%s): %s", provider, exc)
        return None


def _call_gemini(api_key: str, user_content: str) -> str | None:
    model = os.environ.get("AI_MODEL", "gemini-2.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 120},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(str(p.get("text", "")) for p in parts).strip()
    return text or None


def _call_claude(api_key: str, user_content: str) -> str | None:
    model = os.environ.get("AI_MODEL", "claude-3-5-haiku-latest").strip()
    url = "https://api.anthropic.com/v1/messages"
    body = {
        "model": model,
        "max_tokens": 120,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    blocks = data.get("content", [])
    text = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text").strip()
    return text or None
