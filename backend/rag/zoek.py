"""Zoeken in de RAG-index: BM25, cosine, gewogen fusie.

Zie docs/rag-chunkstrategie-en-meting.md §3 en §4. Dit draait per vraag —
bouwen (chunken/embedden/FTS vullen) staat in index.py en draait één keer.
Overgezet uit rag_index.py in top2000.ai, met twee wijzigingen uit §3:

  a. geen fusie meer wanneer de lexicale lijst leeg of te kort is
     (`min_lex_kandidaten`); dan telt de vectorranglijst kaal
  b. gewogen Reciprocal Rank Fusion (`w_vector`, `w_lexicaal`) in plaats van
     de vaste 1,0/1,0 van de oorspronkelijke rank_fusion()

Beide staan hier als parameters, niet als vaste instelling: meting 1 (§5)
moet ze juist kunnen variëren zonder dit bestand te wijzigen.
"""
from __future__ import annotations

import sys
from operator import mul

from backend.rag import index as rag_index

RRF_K = 60          # dempingsconstante voor rank fusion; 60 is de gangbare waarde
FTS_KANDIDATEN = 200
MIN_LEX_KANDIDATEN = 5   # "een handvol" (§3a)


class ModelMismatch(Exception):
    """De index is met een ander embedmodel gebouwd dan nu gevraagd wordt."""


def controleer_versie(con, model: str = rag_index.EMBED_MODEL) -> None:
    """§4: weiger te draaien bij een embedmodel-verschil met de index.

    Ontbreekt de versietabel-rij (index gebouwd vóór index.py bestond, en
    nog niet geregistreerd), dan is dat een waarschuwing, geen weigering —
    er valt dan niets te vergelijken.
    """
    rij = con.execute(
        "SELECT embed_model FROM index_versie ORDER BY gebouwd_op DESC, rowid DESC LIMIT 1"
    ).fetchone()
    if rij is None:
        print(
            "let op: geen index_versie gevonden; kan het embedmodel niet "
            "verifiëren (python -m backend.rag.index versie --schrijf)",
            file=sys.stderr,
        )
        return
    if rij["embed_model"] != model:
        raise ModelMismatch(
            f"De index is gebouwd met embedmodel '{rij['embed_model']}', maar er "
            f"wordt nu met '{model}' gezocht. Dat levert plausibel klinkende "
            f"onzin op, geen fout. Herbouw de index of pas het model aan."
        )


# ---------------------------------------------------------------------------
# DEELRANGLIJSTEN
# ---------------------------------------------------------------------------
def laad_corpus(con, corpus: str, model: str = rag_index.EMBED_MODEL):
    return con.execute(
        "SELECT c.chunk_id, v.vec FROM chunk c JOIN vector v "
        "  ON v.tekst_hash = c.tekst_hash AND v.model = ? "
        "WHERE c.corpus = ?", (model, corpus)).fetchall()


def zoek_vector(con, corpus, vraag, model: str = rag_index.EMBED_MODEL) -> list[tuple[int, float]]:
    """Cosine over het hele corpus. Alles staat genormaliseerd opgeslagen, dus
    dit is een kaal dotproduct — geen wortels, geen deling, per vraag."""
    rijen = laad_corpus(con, corpus, model)
    if not rijen:
        return []
    q = rag_index.normaliseer(rag_index.embed(vraag, model))
    gescoord = [(r["chunk_id"], sum(map(mul, q, rag_index.uit_blob(r["vec"])))) for r in rijen]
    gescoord.sort(key=lambda t: t[1], reverse=True)
    return gescoord


def fts_escape(vraag: str) -> str:
    """FTS5 heeft een eigen querytaal; we citeren elk woord los, zodat
    gebruikersinvoer nooit als syntax telt."""
    woorden = [w for w in "".join(
        ch if ch.isalnum() or ch.isspace() else " " for ch in vraag).split() if w]
    return " OR ".join(f'"{w}"' for w in woorden)


def zoek_lexicaal(con, corpus, vraag, limiet: int = FTS_KANDIDATEN) -> list[tuple[int, float]]:
    """BM25 via FTS5. bm25() geeft lagere = beter, dus we keren om."""
    q = fts_escape(vraag)
    if not q:
        return []
    rijen = con.execute(
        "SELECT f.rowid AS chunk_id, bm25(chunk_fts) AS score "
        "FROM chunk_fts f JOIN chunk c ON c.chunk_id = f.rowid "
        "WHERE chunk_fts MATCH ? AND c.corpus = ? "
        "ORDER BY score LIMIT ?", (q, corpus, limiet)).fetchall()
    return [(r["chunk_id"], -r["score"]) for r in rijen]


# ---------------------------------------------------------------------------
# FUSIE (§3)
# ---------------------------------------------------------------------------
def fuseer(
    vec: list[tuple[int, float]],
    lex: list[tuple[int, float]],
    w_vector: float = 1.0,
    w_lexicaal: float = 1.0,
    min_lex_kandidaten: int = 0,
) -> list[tuple[int, float]]:
    """Gewogen Reciprocal Rank Fusion: telt `gewicht / (K + rang)` op per lijst.

    `min_lex_kandidaten` > 0 activeert §3a: levert BM25 minder dan dat aantal
    kandidaten op, dan komt de vectorranglijst kaal terug — fuseren met een
    lege of te dunne lexicale lijst voegt dan alleen ruis toe.

    Met w_vector = w_lexicaal = 1,0 en min_lex_kandidaten = 0 is dit exact de
    oorspronkelijke, ongewogen rank_fusion() uit rag_index.py — de nulmeting
    in §5 moet hiermee reproduceerbaar zijn.
    """
    if min_lex_kandidaten and len(lex) < min_lex_kandidaten:
        return vec

    totaal: dict[int, float] = {}
    for lijst, gewicht in ((vec, w_vector), (lex, w_lexicaal)):
        for rang, (chunk_id, _) in enumerate(lijst, start=1):
            totaal[chunk_id] = totaal.get(chunk_id, 0.0) + gewicht / (RRF_K + rang)
    return sorted(totaal.items(), key=lambda t: t[1], reverse=True)


# ---------------------------------------------------------------------------
# ZOEKEN — het volledige pad, met chunkgegevens erbij
# ---------------------------------------------------------------------------
def zoek(
    con, corpus, vraag, modus: str = "hybride", k: int = 5,
    model: str = rag_index.EMBED_MODEL,
    w_vector: float = 1.0, w_lexicaal: float = 1.0, min_lex_kandidaten: int = 0,
) -> list[dict]:
    """Geeft de top-k mét de deelscores, niet alleen de eindscore.

    De cosine heeft een absolute betekenis, de RRF-score alleen een volgorde
    (zie fuseer()) — bij het beoordelen van een treffer wil je weten welke
    helft 'm leverde: BM25 of de vector.
    """
    vec: list[tuple[int, float]] = []
    lex: list[tuple[int, float]] = []
    if modus in ("hybride", "vector"):
        vec = zoek_vector(con, corpus, vraag, model)
    if modus in ("hybride", "lexicaal"):
        lex = zoek_lexicaal(con, corpus, vraag)

    if modus == "lexicaal":
        ranglijst = lex
    elif modus == "vector":
        ranglijst = vec
    else:
        ranglijst = fuseer(vec, lex, w_vector, w_lexicaal, min_lex_kandidaten)

    cos = dict(vec)
    lex_rang = {c: r for r, (c, _) in enumerate(lex, start=1)}
    top = ranglijst[:k]
    if not top:
        return []
    plaatshouders = ",".join("?" * len(top))
    rijen = {r["chunk_id"]: r for r in con.execute(
        f"SELECT chunk_id, bron, kop, tekst, meta FROM chunk "
        f"WHERE chunk_id IN ({plaatshouders})", [c for c, _ in top])}
    return [{"score": s, "cosine": cos.get(c), "bm25_rang": lex_rang.get(c),
             **dict(rijen[c])} for c, s in top if c in rijen]


def corpora(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT DISTINCT corpus FROM chunk")}


# ---------------------------------------------------------------------------
# CLI — handmatig een vraag proberen
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse
    import time

    p = argparse.ArgumentParser(description="Zoek in een RAG-corpus")
    p.add_argument("--db", default=rag_index.INDEX_DB)
    p.add_argument("corpus")
    p.add_argument("vraag")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--modus", choices=["hybride", "vector", "lexicaal"], default="hybride")
    p.add_argument("--w-vector", type=float, default=1.0)
    p.add_argument("--w-lexicaal", type=float, default=1.0)
    p.add_argument("--min-lex-kandidaten", type=int, default=0)
    a = p.parse_args()

    con = rag_index.open_index(a.db)
    try:
        controleer_versie(con)
    except ModelMismatch as fout:
        raise SystemExit(str(fout))

    t = time.perf_counter()
    treffers = zoek(con, a.corpus, a.vraag, a.modus, a.k,
                     w_vector=a.w_vector, w_lexicaal=a.w_lexicaal,
                     min_lex_kandidaten=a.min_lex_kandidaten)
    dt = time.perf_counter() - t
    print(f"Vraag: {a.vraag}   [modus: {a.modus}, {dt * 1000:.0f} ms]")
    print("=" * 64)
    if not treffers:
        print("Geen treffers. Is dit corpus geïndexeerd? (python -m backend.rag.index status)")
    for h in treffers:
        kop = f" [{h['kop']}]" if h["kop"] else ""
        deel = []
        if h.get("cosine") is not None:
            deel.append(f"cos {h['cosine']:.3f}")
        if h.get("bm25_rang") is not None:
            deel.append(f"bm25 #{h['bm25_rang']}")
        achter = f"   ({' · '.join(deel)})" if deel else ""
        print(f"\n> {h['score']:.4f}  {h['bron']}{kop}{achter}")
        print("  " + h["tekst"].replace("\n", "\n  "))


if __name__ == "__main__":
    main()
