"""Padkeuze + uitvoering: één vraag herkennen, naar het juiste pad sturen en
een genormaliseerd antwoord teruggeven.

Interface-onafhankelijk, zoals chat.py (spec-top2000-chat.md §2): bruikbaar
door cli.py nu, en door app.py (v2) straks zonder wijziging. Dit is stap 7
uit docs/rag-chunkstrategie-en-meting.md §7 — het scharnier dat ontbrak nu
het sql-pad (chat.py) en het rag-pad (rag/antwoord.py) allebei al bestaan.

backend.router.kies() bepaalt het pad met regels, zonder model en zonder
I/O. Dit bestand voert dat pad pas uit: het opent verbindingen, roept Ollama
aan en normaliseert de twee heel verschillende resultaatvormen (SQL-rijen
versus opgehaalde RAG-blokjes) naar één vorm die een aanroeper kan tonen
zonder per pad andere code te hoeven schrijven.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend import chat, llm, router, verbruik
from backend.rag import antwoord as rag_antwoord
from backend.rag import index as rag_index
from backend.rag import zoek as rag_zoek

RAG_DB_PAD = rag_index.INDEX_DB


@dataclass
class GerouteerdResultaat:
    vraag: str
    pad: str                 # 'sql' | 'rag_songs' | 'rag_project'
    regel: str                # welke routerregel besliste (of 'terugval')
    signaal: str               # de tekst die de regel deed aanslaan
    antwoord: str
    heeft_inhoud: bool         # sql: rijen niet leeg; rag: cosine haalde de drempel
    looptijd_s: float
    # sql-specifiek
    sql: str | None = None
    rijen: list = field(default_factory=list)
    pogingen: int = 0
    # rag-specifiek
    bronnen: list = field(default_factory=list)   # [{bron, kop, cosine}]
    cosine: float | None = None
    # verbruik — zie backend/verbruik.py; bron+dekking horen erbij, geen kaal getal
    energie_wh: float = 0.0
    co2_g: float = 0.0
    verbruik_bron: str = ""
    verbruik_dekking: str = ""


def beantwoord(
    vraag: str,
    model: str = llm.STANDAARD_MODEL,
    rag_model: str = rag_antwoord.GEN_MODEL,
    rag_db: str = RAG_DB_PAD,
    k: int = 5,
) -> GerouteerdResultaat:
    """Bepaalt het pad en voert het uit.

    Dezelfde vraag geeft altijd hetzelfde pad (router.kies doet nul
    inferentie); wat er daarna gebeurt hangt van dat pad af, maar het
    resultaat komt er in dezelfde vorm uit — inclusief het verbruik van
    precies dit werk, niet meer en niet minder (verbruik.meet_verbruik
    omsluit alleen het stuk hieronder, niet de padkeuze zelf, die toch
    verwaarloosbaar is qua vermogen).
    """
    start = time.monotonic()
    keuze = router.kies(vraag)

    # v (het verbruik) mag pas ná __exit__ gelezen worden: pas dan staan
    # duur en samples vast (zie backend/verbruik.py). Dus geen return
    # binnen de with, en geen aparte tak per pad die het blok vroeg verlaat.
    with verbruik.meet_verbruik() as meter:
        if keuze.pad == "sql":
            r = chat.antwoord(vraag, model=model)
        else:
            corpus = "songs" if keuze.pad == "rag_songs" else "project"
            con = rag_index.open_index(rag_db)
            try:
                rag_zoek.controleer_versie(con)
                resultaat = rag_antwoord.beantwoord(con, corpus, vraag, k=k, model=rag_model)
            finally:
                con.close()
    v = meter.resultaat()

    if keuze.pad == "sql":
        return GerouteerdResultaat(
            vraag=vraag, pad=keuze.pad, regel=keuze.regel, signaal=keuze.signaal,
            antwoord=r.antwoord, heeft_inhoud=bool(r.rijen), looptijd_s=r.looptijd_s,
            sql=r.sql, rijen=r.rijen, pogingen=r.pogingen,
            energie_wh=v.energie_wh, co2_g=v.co2_g,
            verbruik_bron=v.bron, verbruik_dekking=v.dekking,
        )

    bronnen = [
        {"bron": h["bron"], "kop": h["kop"], "cosine": h.get("cosine")}
        for h in resultaat["treffers"]
    ]
    return GerouteerdResultaat(
        vraag=vraag, pad=keuze.pad, regel=keuze.regel, signaal=keuze.signaal,
        antwoord=resultaat["antwoord"], heeft_inhoud=bool(resultaat["gegrond"]),
        looptijd_s=time.monotonic() - start, bronnen=bronnen, cosine=resultaat["cosine"],
        energie_wh=v.energie_wh, co2_g=v.co2_g,
        verbruik_bron=v.bron, verbruik_dekking=v.dekking,
    )
