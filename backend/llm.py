"""Ollama-client. Geen enkele aanroep verlaat de machine — zie CLAUDE.md."""

from __future__ import annotations

import requests

OLLAMA_URL = "http://localhost:11434"
STANDAARD_MODEL = "qwen2.5-coder:32b"


class OllamaFout(Exception):
    """Ollama is niet bereikbaar of gaf een fout terug."""


def genereer(
    prompt: str,
    systeem: str | None = None,
    model: str = STANDAARD_MODEL,
    temperature: float = 0.0,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "system": systeem,
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        respons = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
        respons.raise_for_status()
    except requests.exceptions.RequestException as fout:
        raise OllamaFout(f"Ollama niet bereikbaar op {OLLAMA_URL}: {fout}") from fout

    return respons.json()["response"]
