"""Meetlopers voor de RAG-laag — spec §5.

Meet ALLEEN retrieval, niet het antwoord: als de verkeerde blokjes bovenkomen
kan geen enkel model daar een goed antwoord van maken, dus retrieval is de
plek om te meten. Er draait wel een model — bge-m3 via Ollama, om de vraag te
embedden — en dat is hetzelfde model als in productie; de uitvoer noemt het
altijd. Een getal zonder modelnaam is geen meting (CLAUDE.md).

Overgezet uit eval_rag.py in top2000.ai, met twee toevoegingen:
  - meting1(): de vijf varianten uit §5 in één tabel, met vec/lex per vraag
    maar één keer berekend (§3: "zonder opnieuw te embedden te meten" — met
    vijf varianten zou dat anders alsnog 5x zoveel Ollama-calls kosten).
  - de gewogen-fusieparameters uit zoek.py komen door tot op de CLI.

Gebruik:
    python -m backend.rag.eval                    # hybride/vector/lexicaal, spec §5 meting 0
    python -m backend.rag.eval --modus vector
    python -m backend.rag.eval --meting1           # de 5 varianten uit §5 meting 1
    python -m backend.rag.eval --toon-missers
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

from backend.rag import index as rag_index
from backend.rag import zoek as rag_zoek

VRAGEN = "data/rag_vragen.csv"
MODI = ("lexicaal", "vector", "hybride")

VARIANTEN_METING1: list[tuple[str, dict]] = [
    ("hybride, ongewogen (nul)", dict(w_vector=1.0, w_lexicaal=1.0, min_lex_kandidaten=0)),
    ("geen fusie bij lege BM25", dict(w_vector=1.0, w_lexicaal=1.0,
                                       min_lex_kandidaten=rag_zoek.MIN_LEX_KANDIDATEN)),
    ("w_lexicaal = 0,75", dict(w_vector=1.0, w_lexicaal=0.75,
                                min_lex_kandidaten=rag_zoek.MIN_LEX_KANDIDATEN)),
    ("w_lexicaal = 0,50", dict(w_vector=1.0, w_lexicaal=0.50,
                                min_lex_kandidaten=rag_zoek.MIN_LEX_KANDIDATEN)),
    ("w_lexicaal = 0,25", dict(w_vector=1.0, w_lexicaal=0.25,
                                min_lex_kandidaten=rag_zoek.MIN_LEX_KANDIDATEN)),
]


def lees_vragen(pad: str) -> list[dict]:
    with open(pad, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def namen(brondb: str) -> dict[int, str]:
    """song_id -> 'Titel — Artiest', voor leesbare misserregels."""
    try:
        con = sqlite3.connect(f"file:{brondb}?mode=ro", uri=True)
        return {r[0]: f"{r[1]} — {r[2]}"
                for r in con.execute("SELECT song_id, titel, artiest FROM songs")}
    except sqlite3.Error:
        return {}


def song_treffers(treffers: list[dict]) -> list[tuple[int, str]]:
    """(song_id, kop) uit de opgehaalde blokjes, op volgorde, ontdubbeld.

    NL- en EN-tekst van hetzelfde nummer zijn aparte blokjes; voor deze
    meting tellen ze als één treffer.
    """
    uit: list[tuple[int, str]] = []
    gezien = set()
    for h in treffers:
        meta = json.loads(h["meta"] or "{}")
        sid = meta.get("song_id")
        if sid is None or sid in gezien:
            continue
        gezien.add(sid)
        uit.append((sid, h["kop"] or f"song {sid}"))
    return uit


# ---------------------------------------------------------------------------
# Losse rapportage per modus (meting 0, en losse checks)
# ---------------------------------------------------------------------------
def meet(con, vragen: list[dict], corpus: str, k: int, toon_missers: bool,
         titels: dict[int, str] | None = None, modus_lijst=MODI,
         model: str = rag_index.EMBED_MODEL,
         w_vector: float = 1.0, w_lexicaal: float = 1.0,
         min_lex_kandidaten: int = 0) -> None:
    titels = titels or {}
    beantwoordbaar = [v for v in vragen if v["verwacht_song_id"].strip()]
    overig = [v for v in vragen if not v["verwacht_song_id"].strip()]
    print(f"{len(beantwoordbaar)} vragen met een verwacht nummer, "
          f"{len(overig)} zonder (afwezig/sql -- die meten we hier niet)")
    print(f"embedmodel: {model} via Ollama | corpus: {corpus} | k={k}\n")

    per_cat: dict[tuple[str, str], list[int]] = {}
    missers: list[tuple] = []
    for v in beantwoordbaar:
        verwacht = int(v["verwacht_song_id"])
        cat = v["categorie"]
        for modus in modus_lijst:
            treffers = rag_zoek.zoek(con, corpus, v["vraag"], modus, k, model,
                                      w_vector, w_lexicaal, min_lex_kandidaten)
            paren = song_treffers(treffers)
            ids = [s for s, _ in paren]
            rang = ids.index(verwacht) + 1 if verwacht in ids else 0
            per_cat.setdefault((cat, modus), []).append(rang)
            if rang == 0 and toon_missers:
                missers.append((modus, v["vraag"], verwacht, paren))

    print(f"{'categorie':<14}{'modus':<11}{'top-1':>7}{'top-3':>7}{'top-' + str(k):>7}"
          f"{'gem. rang':>11}")
    print("-" * 57)
    for cat in dict.fromkeys(v["categorie"] for v in beantwoordbaar):
        for modus in modus_lijst:
            rangen = per_cat.get((cat, modus), [])
            if not rangen:
                continue
            n = len(rangen)
            raak = [r for r in rangen if r]
            print(f"{cat:<14}{modus:<11}"
                  f"{sum(1 for r in rangen if r == 1) / n * 100:>6.0f}%"
                  f"{sum(1 for r in raak if r <= 3) / n * 100:>6.0f}%"
                  f"{len(raak) / n * 100:>6.0f}%"
                  f"{(sum(raak) / len(raak) if raak else 0):>11.1f}")
        print()

    if missers:
        print("MISSERS (verwacht nummer niet in de top-k)")
        vorige = None
        for modus, vraag, verwacht, gevonden in missers:
            if vraag != vorige:
                print(f"\n  \"{vraag}\"")
                print(f"    verwacht: {verwacht:>5}  {titels.get(verwacht, '?')}")
                vorige = vraag
            print(f"    [{modus}]")
            for i, (sid, kop) in enumerate(gevonden, 1):
                print(f"      {i}. {sid:>5}  {kop}")

    if overig:
        print("\nNiet automatisch te meten -- hier moet je zelf naar kijken:")
        for v in overig:
            print(f"  [{v['categorie']}] {v['vraag']}")
        print("  Bij 'afwezig' hoort het model te zeggen dat het antwoord er niet is.")
        print("  Bij 'sql' hoort de router de vraag niet naar RAG te sturen.")


# ---------------------------------------------------------------------------
# Meting 1: fusievarianten op de bestaande index, één embed-pas per vraag
# ---------------------------------------------------------------------------
def _chunk_song_ids(con, corpus: str) -> dict[int, int]:
    """chunk_id -> song_id, één keer per corpus opgehaald."""
    uit: dict[int, int] = {}
    for r in con.execute("SELECT chunk_id, meta FROM chunk WHERE corpus = ?", (corpus,)):
        meta = json.loads(r["meta"] or "{}")
        sid = meta.get("song_id")
        if sid is not None:
            uit[r["chunk_id"]] = sid
    return uit


def _song_ids_op_volgorde(ranglijst: list[tuple[int, float]],
                           chunk_song: dict[int, int]) -> list[int]:
    uit: list[int] = []
    gezien: set[int] = set()
    for chunk_id, _ in ranglijst:
        sid = chunk_song.get(chunk_id)
        if sid is None or sid in gezien:
            continue
        gezien.add(sid)
        uit.append(sid)
    return uit


def _vec_lex_per_vraag(con, vragen: list[dict], corpus: str,
                        model: str) -> dict[str, tuple[list, list]]:
    """(vec, lex) per unieke vraagtekst — bge-m3 draait hier exact eenmaal per
    vraag, ongeacht hoeveel fusievarianten er daarna overheen lopen."""
    uit: dict[str, tuple[list, list]] = {}
    for v in vragen:
        vraag = v["vraag"]
        if vraag in uit:
            continue
        vec = rag_zoek.zoek_vector(con, corpus, vraag, model)
        lex = rag_zoek.zoek_lexicaal(con, corpus, vraag)
        uit[vraag] = (vec, lex)
    return uit


def _rang(ranglijst: list[tuple[int, float]], chunk_song: dict[int, int],
          verwacht: int, k: int) -> int:
    ids = _song_ids_op_volgorde(ranglijst[:k], chunk_song)
    return ids.index(verwacht) + 1 if verwacht in ids else 0


def _recall_pct(rangen: list[int]) -> float:
    if not rangen:
        return 0.0
    return sum(1 for r in rangen if r) / len(rangen) * 100


def meting1(con, vragen_beantwoordbaar: list[dict], corpus: str, k: int,
            model: str = rag_index.EMBED_MODEL) -> None:
    """De tabel uit §5 meting 1: vijf fusievarianten, geen herbouw.

    Elke variant hergebruikt dezelfde vec/lex-ranglijsten; alleen fuseer()
    verschilt. Zo test dit precies wat §3 beweert te veranderen, en niets
    anders — de embeddings zijn voor alle vijf varianten identiek.
    """
    chunk_song = _chunk_song_ids(con, corpus)
    vl = _vec_lex_per_vraag(con, vragen_beantwoordbaar, corpus, model)

    print(f"embedmodel: {model} via Ollama | corpus: {corpus} | k={k} | "
          f"{len(vragen_beantwoordbaar)} vragen")
    print(f"RRF_K={rag_zoek.RRF_K}, min_lex_kandidaten waar actief="
          f"{rag_zoek.MIN_LEX_KANDIDATEN}\n")

    breedte_variant = max(len(n) for n, _ in VARIANTEN_METING1) + 2
    kop = f"{'variant':<{breedte_variant}}{'naam @' + str(k):>10}{'omschrijving @' + str(k):>18}"
    print(kop)
    print("-" * len(kop))

    for naam_variant, params in VARIANTEN_METING1:
        per_cat: dict[str, list[int]] = {}
        for v in vragen_beantwoordbaar:
            vec, lex = vl[v["vraag"]]
            ranglijst = rag_zoek.fuseer(vec, lex, **params)
            rang = _rang(ranglijst, chunk_song, int(v["verwacht_song_id"]), k)
            per_cat.setdefault(v["categorie"], []).append(rang)

        naam_pct = _recall_pct(per_cat.get("naam", []))
        omschrijving_pct = _recall_pct(per_cat.get("omschrijving", []))
        print(f"{naam_variant:<{breedte_variant}}{naam_pct:>9.0f}%{omschrijving_pct:>17.0f}%")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="RAG-retrievalmeting (spec §5)")
    p.add_argument("--db", default=rag_index.INDEX_DB)
    p.add_argument("--vragen", default=VRAGEN)
    p.add_argument("--corpus", default="songs")
    p.add_argument("--brondb", default="top2000.db",
                    help="voor de titels bij de song_id's in de misserlijst")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--toon-missers", action="store_true")
    p.add_argument("--modus", choices=MODI, default=None,
                    help="alleen deze modus meten (default: alle drie)")
    p.add_argument("--w-vector", type=float, default=1.0)
    p.add_argument("--w-lexicaal", type=float, default=1.0)
    p.add_argument("--min-lex-kandidaten", type=int, default=0,
                    help="§3a: onder dit aantal BM25-kandidaten geen fusie, kaal vector")
    p.add_argument("--meting1", action="store_true",
                    help="draait de vijf varianten uit §5 meting 1 in één tabel")
    a = p.parse_args()

    if not Path(a.vragen).exists():
        raise SystemExit(f"{a.vragen} bestaat niet.")
    vragen = lees_vragen(a.vragen)
    ongecontroleerd = sum(1 for v in vragen if v["gecontroleerd"].strip() != "ja")
    if ongecontroleerd:
        print(f"LET OP: {ongecontroleerd} van de {len(vragen)} vragen zijn nog niet "
              f"door een mens gecontroleerd.\n"
              f"De uitkomst hieronder is een indicatie, geen vastgestelde meting.\n",
              file=sys.stderr)

    con = rag_index.open_index(a.db)
    try:
        rag_zoek.controleer_versie(con)
    except rag_zoek.ModelMismatch as fout:
        raise SystemExit(str(fout))

    start = time.perf_counter()
    if a.meting1:
        beantwoordbaar = [v for v in vragen if v["verwacht_song_id"].strip()]
        meting1(con, beantwoordbaar, a.corpus, a.k)
    else:
        modus_lijst = (a.modus,) if a.modus else MODI
        meet(con, vragen, a.corpus, a.k, a.toon_missers, namen(a.brondb),
             modus_lijst, w_vector=a.w_vector, w_lexicaal=a.w_lexicaal,
             min_lex_kandidaten=a.min_lex_kandidaten)
    print(f"\n{time.perf_counter() - start:.1f} s totaal")


if __name__ == "__main__":
    main()
