"""HTTP-laag (v2). Zie docs/spec-top2000-chat.md §2 en ARCHITECTUUR-EN-WAARDEN.md §4.

Hergebruikt dezelfde interface-onafhankelijke code als de CLI: geen nieuwe
antwoordlogica hier, alleen een dunne schil om backend.beantwoorder.beantwoord().
De React-frontend praat hiermee via /api/*.

Draaien:
    .venv/bin/uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import beantwoorder, llm
from backend.rag import antwoord as rag_antwoord
from backend.rag import index as rag_index
from backend.rag import zoek as rag_zoek
from backend.cli import DB_PAD, OLLAMA_URL, STANDAARD_MODEL

app = FastAPI(title="Top2000 Chat")

# Dev-only: de Vite-dev-server draait op een andere origin. In productie komt
# de frontend als statische build achter dezelfde host te staan en is dit niet
# nodig — zie ARCHITECTUUR-EN-WAARDEN.md §7 (hostingkeuze, nog open).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class VraagBody(BaseModel):
    vraag: str


@app.get("/")
def root() -> dict:
    """Geen kale 404: deze backend heeft geen eigen pagina. De UI draait op
    de Vite-dev-server (npm run dev, poort 5173), die /api hierheen proxyt."""
    return {
        "dit is": "de FastAPI-laag van Top2000 Chat, geen webpagina",
        "frontend": "http://localhost:5173 (npm run dev in frontend/)",
        "endpoints": ["/api/ask", "/api/check"],
        "docs": "/docs",
    }


@app.post("/api/ask")
def ask(body: VraagBody) -> dict:
    vraag = body.vraag.strip()
    if not vraag:
        raise HTTPException(400, "vraag is leeg")
    try:
        resultaat = beantwoorder.beantwoord(vraag)
    except (llm.OllamaFout, rag_zoek.ModelMismatch) as fout:
        raise HTTPException(503, str(fout))
    return asdict(resultaat)


@app.get("/api/check")
def check() -> dict:
    """JSON-variant van `python -m backend.cli check` — voor een statusindicator
    in de frontend, niet voor de mens op de commandoregel."""
    status: dict = {
        "database": Path(DB_PAD).exists(),
        "rag_index": Path(beantwoorder.RAG_DB_PAD).exists(),
        "ollama": False,
        "modellen": {},
    }
    try:
        respons = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        respons.raise_for_status()
        geladen = {m["name"] for m in respons.json().get("models", [])}
        status["ollama"] = True
        for naam, model_naam in (
            ("sql", STANDAARD_MODEL),
            ("rag_generatie", rag_antwoord.GEN_MODEL),
            ("embedden", rag_index.EMBED_MODEL),
        ):
            status["modellen"][naam] = (
                model_naam in geladen or f"{model_naam}:latest" in geladen
            )
    except requests.exceptions.RequestException:
        pass
    return status
