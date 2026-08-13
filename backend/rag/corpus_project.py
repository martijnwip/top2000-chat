"""Bouwt het JSONL-corpus voor 'project': de documentatie in docs/, gechunkt
tot blokjes die backend.rag.index kan indexeren.

Chunkstrategie overgezet uit rag.py (top2000.ai, het didactische voorbeeld):
splits op alinea, onthoud de dichtstbijzijnde markdown-kop, knip tabellen per
rij, plak te kleine restjes aan het vorige blokje. Alleen chunken hier — geen
Ollama nodig. Embedden gebeurt met:

    python -m backend.rag.corpus_project > data/corpus_project.jsonl
    python -m backend.rag.index indexeer project data/corpus_project.jsonl

BEWUSTE UITSLUITING: docs/reclaim-intelligence.md staat niet in BRONNEN. Het
is het externe manifest van empathy.ai waar docs/ARCHITECTUUR-EN-WAARDEN.md
§5 zich tegen afzet — geschreven in de eerste persoon alsof het over déze
toepassing gaat ("We handle everything. You own it."), zonder enige framing
in de tekst zelf die een antwoordmodel kan laten zien dat het over een andere
partij gaat. Opnemen zou een vraag als "hoe duurzaam is dit project" een
antwoord over andermans GPU-infrastructuur kunnen opleveren, toegeschreven
aan top2000-chat. Eerlijkheid boven volledigheid (CLAUDE.md).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DOCS_DIR = "docs"
MIN_CHARS = 200   # blokjes kleiner dan dit plakken we aan het vorige

BRONNEN = [
    "ARCHITECTUUR-EN-WAARDEN.md",
    "spec-top2000-chat.md",
    "rag-chunkstrategie-en-meting.md",
    "rag-waar-gebleven.md",
]


def is_tabel(blok: str) -> bool:
    """Een markdown-tabel herken je aan regels die met '|' beginnen."""
    regels = blok.splitlines()
    return len(regels) >= 2 and sum(r.lstrip().startswith("|") for r in regels) >= 2


def chunk_tabel(bron: str, kop: str, blok: str) -> list[dict]:
    """Splits een markdown-tabel in één blokje per rij, met de kolomnamen
    erbij ('Status: Ja') zodat elk blokje op zichzelf leesbaar is."""
    rijen = [r.strip().strip("|").split("|") for r in blok.splitlines()
             if r.lstrip().startswith("|")]
    rijen = [[cel.strip() for cel in r] for r in rijen]
    kolommen = rijen[0]
    chunks = []
    for rij in rijen[1:]:
        if all(set(cel) <= {"-", ":", " "} for cel in rij):
            continue  # scheidingsrij |---|---| overslaan
        delen = [f"{k}: {c}" if k else c for k, c in zip(kolommen, rij) if c]
        chunks.append({"bron": bron, "kop": kop, "tekst": ". ".join(delen)})
    return chunks


def chunk_document(bron: str, tekst: str) -> list[dict]:
    chunks: list[dict] = []
    huidige_kop = ""
    for blok in re.split(r"\n\s*\n", tekst):
        blok = blok.strip()
        if not blok:
            continue

        if blok.startswith("#"):
            huidige_kop = blok.lstrip("# ").strip()
            continue

        if is_tabel(blok):
            chunks.extend(chunk_tabel(bron, huidige_kop, blok))
            continue

        if chunks and len(blok) < MIN_CHARS and chunks[-1]["bron"] == bron:
            chunks[-1]["tekst"] += "\n" + blok
            continue

        chunks.append({"bron": bron, "kop": huidige_kop, "tekst": blok})
    return chunks


def maak_chunks(docs_dir: str = DOCS_DIR, bronnen: list[str] = BRONNEN) -> list[dict]:
    alle: list[dict] = []
    for naam in bronnen:
        pad = Path(docs_dir) / naam
        if not pad.exists():
            print(f"let op: {pad} bestaat niet, overgeslagen", file=sys.stderr)
            continue
        tekst = pad.read_text(encoding="utf-8")
        alle.extend(chunk_document(naam, tekst))
    return alle


def main() -> None:
    chunks = maak_chunks()
    for c in chunks:
        c["meta"] = {}
        print(json.dumps(c, ensure_ascii=False))
    print(f"{len(chunks)} chunks uit {len(BRONNEN)} bestanden", file=sys.stderr)


if __name__ == "__main__":
    main()
