"""Antwoordlaag over backend.rag.zoek.zoek(): opgehaalde blokjes -> een gegrond antwoord.

Overgezet uit antwoord_rag.py (top2000.ai). Werkt op de dicts die zoek()
teruggeeft (bron, kop, tekst, cosine) en is dus bruikbaar voor elk corpus in
de index — 'songs', 'artiesten', straks 'project' (docs/rag-chunkstrategie-
en-meting.md §7 stap 8).

DE DREMPEL IS HET BELANGRIJKSTE DEEL
-------------------------------------
Een corpus geeft ALTIJD een top-k terug. Ook op "moet ik me registreren" komen
er blokjes boven met scores die er redelijk uitzien, en een instruct-model
plakt daar zonder tegendruk een vloeiend antwoord van. De nooduitgang in de
prompt ("zeg het als het er niet staat") helpt, maar leunt op het oordeel van
een 7B-model over zijn eigen context — precies het oordeel dat je niet wilt
vertrouwen.

Daarom eerst een harde drempel, buiten het model om: is de beste cosine te
laag, dan wordt er niets gegenereerd. Op de COSINE, niet op de eindscore —
zoek.fuseer() legt uit waarom die laatste alleen een volgorde is.

DE FUSIE-INSTELLING IS NU GEMETEN, DE DREMPEL NOG NIET
---------------------------------------------------------
Meting 1 (rag-chunkstrategie-en-meting.md §5) liet zien dat w_lexicaal = 0,50
de omschrijvingsscore optilt van 8% naar 17% @5 zonder dat naam-vragen zakken
(100% blijft 100%). Dat gewicht is daarom hier de standaardinstelling voor
'hybride', niet meer de ongewogen 1,0/1,0 uit de oorspronkelijke
rank_fusion(). DREMPEL hieronder is dat niet: die is nog met de hand gekozen
en nergens aan getoetst. Om hem te onderbouwen (meting 3, §5, moet ná het
herchunken van stap 9): draai vragen waarvan je weet dat het antwoord in het
corpus staat en vragen waarvan je weet van niet, en kijk waar de cosines
uiteenvallen:

    python -m backend.rag.zoek songs "waar gaat Hotel California over" -k 5
    python -m backend.rag.zoek songs "moet ik me registreren" -k 5

De cosine staat per treffer in die uitvoer.
"""
from __future__ import annotations

import json
import urllib.request

from backend.rag import index as rag_index
from backend.rag import zoek as rag_zoek

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
# Algemeen instruct-model, niet het coder-model uit backend.chat: dit hoeft
# geen SQL te schrijven, alleen goed Nederlands en zich aan de context houden.
GEN_MODEL = "qwen2.5:7b-instruct"

# Gemeten in meting 1: min_lex_kandidaten had op de eval-vragen geen effect
# (BM25 leverde altijd genoeg kandidaten), w_lexicaal=0,50 wel. Zie hierboven.
W_VECTOR = 1.0
W_LEXICAAL = 0.50
MIN_LEX_KANDIDATEN = rag_zoek.MIN_LEX_KANDIDATEN

# Aanname, niet gemeten. Zie de kop van dit bestand.
DREMPEL = 0.50

# Onder deze tekst hoort geen model te draaien: er valt niets te antwoorden.
GEEN_BRON = ("Daar staat niets over in de opgehaalde documenten. "
             "Een antwoord zou hier verzonnen zijn.")


def beste_cosine(treffers: list[dict]) -> float | None:
    waarden = [t["cosine"] for t in treffers if t.get("cosine") is not None]
    return max(waarden) if waarden else None


def maak_context(treffers: list[dict]) -> str:
    return "\n\n".join(
        f"[bron: {t['bron']}" + (f" — {t['kop']}]" if t["kop"] else "]")
        + f"\n{t['tekst']}"
        for t in treffers
    )


PROMPT = """Je beantwoordt vragen uitsluitend op basis van de onderstaande context.

Regels:
- Gebruik ALLEEN informatie uit de context. Geen eigen kennis, niets erbij verzinnen.
- Staat het antwoord niet in de context, zeg dan precies dat: "Dat staat niet in de documenten."
- Noem geen feit dat niet letterlijk uit de context volgt, ook niet als het waarschijnlijk lijkt.
- Neem de status uit de context letterlijk over: iets wat "plan", "voorgenomen"
  of "doel" is, presenteer je als plan — NOOIT als iets dat al bestaat of werkt.
- Antwoord in het Nederlands, kort en concreet.
- Noem aan het eind tussen haakjes de bron(nen) die je gebruikte.

Context:
{context}

Vraag: {vraag}
Antwoord:"""


def genereer(vraag: str, treffers: list[dict], model: str = GEN_MODEL) -> str:
    """Bouw de prompt en laat Ollama antwoorden. temperature 0, zodat dezelfde
    vraag hetzelfde antwoord geeft — anders is geen enkele promptwijziging
    meetbaar en weet je niet of je de wijziging zag of de sampling."""
    payload = {"model": model, "stream": False, "options": {"temperature": 0},
               "prompt": PROMPT.format(context=maak_context(treffers), vraag=vraag)}
    req = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["response"].strip()


def beantwoord(con, corpus: str, vraag: str, k: int = 5,
               drempel: float = DREMPEL, model: str = GEN_MODEL) -> dict:
    """Haal op, controleer de drempel, genereer alleen als er grond voor is.

    Geeft alles terug wat nodig is om het antwoord te wantrouwen: de
    treffers, de beste cosine en of de drempel gehaald werd — zodat een
    aanroeper kan tonen waar een antwoord vandaan komt.
    """
    treffers = rag_zoek.zoek(con, corpus, vraag, "hybride", k,
                              w_vector=W_VECTOR, w_lexicaal=W_LEXICAAL,
                              min_lex_kandidaten=MIN_LEX_KANDIDATEN)
    cos = beste_cosine(treffers)

    if not treffers:
        return {"antwoord": f"Corpus '{corpus}' levert niets op. Is het geïndexeerd? "
                             f"(python -m backend.rag.index status)",
                "treffers": [], "cosine": None, "gegrond": False}

    if cos is None or cos < drempel:
        return {"antwoord": GEEN_BRON, "treffers": treffers,
                "cosine": cos, "gegrond": False}

    return {"antwoord": genereer(vraag, treffers, model), "treffers": treffers,
            "cosine": cos, "gegrond": True}


# ---------------------------------------------------------------------------
# CLI — handmatig een vraag proberen
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse
    import time

    p = argparse.ArgumentParser(description="RAG-antwoord voor één vraag")
    p.add_argument("--db", default=rag_index.INDEX_DB)
    p.add_argument("corpus")
    p.add_argument("vraag")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--drempel", type=float, default=DREMPEL)
    p.add_argument("--model", default=GEN_MODEL)
    a = p.parse_args()

    con = rag_index.open_index(a.db)
    try:
        rag_zoek.controleer_versie(con)
    except rag_zoek.ModelMismatch as fout:
        raise SystemExit(str(fout))

    t = time.perf_counter()
    resultaat = beantwoord(con, a.corpus, a.vraag, a.k, a.drempel, a.model)
    dt = time.perf_counter() - t

    cos = resultaat["cosine"]
    cos_tekst = f"{cos:.3f}" if cos is not None else "—"
    print(f"Vraag: {a.vraag}   [{dt:.1f}s, cosine {cos_tekst}, "
          f"gegrond: {resultaat['gegrond']}]")
    print("=" * 64)
    print(resultaat["antwoord"])
    if resultaat["treffers"]:
        print("\n[opgehaald]")
        for h in resultaat["treffers"]:
            kop = f" [{h['kop']}]" if h["kop"] else ""
            c = h.get("cosine")
            print(f"  cos {c:.3f}  {h['bron']}{kop}" if c is not None
                  else f"  {h['bron']}{kop}")


if __name__ == "__main__":
    main()
