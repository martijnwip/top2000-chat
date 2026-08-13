"""RAG-index bouwen: chunken (uit JSONL), embedden, FTS vullen, versietabel.

Zie docs/rag-chunkstrategie-en-meting.md §2, §2.1, §4 en §7 stap 1.

Bouwen en zoeken zijn met opzet gescheiden bestanden (§7): dit hier draait
één keer per corpuswijziging en kost minuten tot uren; zoek.py draait per
vraag en moet dat niet meeslepen. Overgezet uit het eerdere, ongesplitste
rag_index.py in top2000.ai — de indexeer-, embed- en schemalogica is
inhoudelijk hetzelfde, plus de versietabel (§4) en opruiming (§2.1) die daar
nog niet bestonden.

Gebruik:
    python -m backend.rag.index indexeer songs data/corpus_songs.jsonl
    python -m backend.rag.index status
    python -m backend.rag.index versie --schrijf --strategie sectie
    python -m backend.rag.index opruimen

Vooraf, eenmalig: ollama pull bge-m3
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

INDEX_DB = "data/rag_index.db"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
# Meertalig: legt NL en EN in dezelfde vectorruimte. Eén verandering per
# meting (§2) — dit blijft ongewijzigd totdat een meting het tegendeel bewijst.
EMBED_MODEL = "bge-m3"

# ---------------------------------------------------------------------------
# SCHEMA
# ---------------------------------------------------------------------------
SCHEMA = """
-- Een chunk = een blokje tekst dat als geheel opgehaald kan worden.
CREATE TABLE IF NOT EXISTS chunk (
    chunk_id   INTEGER PRIMARY KEY,
    corpus     TEXT NOT NULL,          -- 'songs', 'artiesten', ...
    bron       TEXT NOT NULL,          -- waar komt dit vandaan (bestand/URL/song_id)
    kop        TEXT,                   -- sectietitel, weegt mee bij het embedden
    tekst      TEXT NOT NULL,
    meta       TEXT,                   -- JSON: song_id, artiest, jaren, ...
    tekst_hash TEXT NOT NULL           -- sleutel naar de vector
);
CREATE INDEX IF NOT EXISTS idx_chunk_corpus ON chunk(corpus);
CREATE INDEX IF NOT EXISTS idx_chunk_hash   ON chunk(tekst_hash);

-- Vectoren staan APART van chunks, op tekst-hash (§2, "wat niet verandert").
-- Een herbouw van het corpus met ongewijzigde tekst hoeft dan niet opnieuw
-- te embedden.
CREATE TABLE IF NOT EXISTS vector (
    tekst_hash TEXT NOT NULL,
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vec        BLOB NOT NULL,          -- float32, L2-genormaliseerd
    PRIMARY KEY (tekst_hash, model)
);

-- Lexicale index. unicode61 + remove_diacritics: 'Beyonce' vindt ook 'Beyoncé'.
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    tekst,
    content='chunk',
    content_rowid='chunk_id',
    tokenize="unicode61 remove_diacritics 2"
);

-- Spec §4: maakt de index zelfbeschrijvend. zoek.py leest dit en weigert te
-- draaien wanneer het huidige embedmodel niet bij deze index hoort — de
-- enige faalmodus die zich niet als fout meldt maar als plausibele onzin.
CREATE TABLE IF NOT EXISTS index_versie (
    gebouwd_op      TEXT NOT NULL,     -- ISO-datum
    embed_model     TEXT NOT NULL,
    dim             INTEGER NOT NULL,
    chunk_strategie TEXT NOT NULL,     -- 'sectie' | 'zinsvenster-500-25'
    corpus_hash     TEXT NOT NULL,     -- sha256 over de jsonl-bestanden
    aantal_chunks   INTEGER NOT NULL,
    toelichting     TEXT
);
"""


def open_index(pad: str = INDEX_DB) -> sqlite3.Connection:
    Path(pad).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(pad)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def tekst_hash(kop: str, tekst: str) -> str:
    """Hash over precies wat we embedden — kop inbegrepen, want die weegt mee."""
    return hashlib.sha256(f"{kop}\n{tekst}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# VECTOREN: opslaan als float32-BLOB, altijd genormaliseerd
# ---------------------------------------------------------------------------
def normaliseer(v: list[float]) -> array.array:
    nrm = math.sqrt(sum(x * x for x in v))
    if not nrm:
        return array.array("f", v)
    return array.array("f", [x / nrm for x in v])


def naar_blob(v: array.array) -> bytes:
    return v.tobytes()


def uit_blob(b: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(b)
    return a


def embed(tekst: str, model: str = EMBED_MODEL) -> list[float]:
    """Een enkele Ollama-embedding. Bewust zonder retry-magie: als Ollama niet
    draait wil je dat meteen weten, niet na tien minuten stille retries."""
    payload = {"model": model, "prompt": tekst}
    req = urllib.request.Request(
        OLLAMA_EMBED_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["embedding"]
    except urllib.error.URLError as e:
        raise SystemExit(
            f"Ollama niet bereikbaar op {OLLAMA_EMBED_URL} ({e}).\n"
            f"Draait 'ollama serve' en heb je 'ollama pull {model}' gedaan?"
        )


# ---------------------------------------------------------------------------
# INDEXEREN
# ---------------------------------------------------------------------------
def lees_jsonl(pad: str) -> list[dict]:
    docs = []
    with open(pad, encoding="utf-8") as f:
        for regelnr, regel in enumerate(f, 1):
            regel = regel.strip()
            if not regel:
                continue
            try:
                docs.append(json.loads(regel))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{pad}:{regelnr} is geen geldige JSON — {e}")
    return docs


def indexeer(con: sqlite3.Connection, corpus: str, jsonl_pad: str,
             model: str = EMBED_MODEL, alleen_chunks: bool = False) -> None:
    """Vervang het corpus door de inhoud van het JSONL-bestand.

    Chunks worden vervangen, vectoren NIET: die staan op tekst-hash en
    blijven staan. Herbouw je het corpus met een kleine wijziging, dan
    embed je alleen wat daadwerkelijk veranderde.
    """
    docs = lees_jsonl(jsonl_pad)
    print(f"{len(docs)} documenten uit {jsonl_pad}")

    con.execute("DELETE FROM chunk_fts WHERE rowid IN "
                "(SELECT chunk_id FROM chunk WHERE corpus = ?)", (corpus,))
    con.execute("DELETE FROM chunk WHERE corpus = ?", (corpus,))

    rijen = []
    for d in docs:
        kop = (d.get("kop") or "").strip()
        tekst = (d.get("tekst") or "").strip()
        if not tekst:
            continue
        rijen.append((corpus, d.get("bron", "?"), kop, tekst,
                      json.dumps(d.get("meta", {}), ensure_ascii=False),
                      tekst_hash(kop, tekst)))
    con.executemany(
        "INSERT INTO chunk (corpus, bron, kop, tekst, meta, tekst_hash) "
        "VALUES (?,?,?,?,?,?)", rijen)
    con.execute("INSERT INTO chunk_fts (rowid, tekst) "
                "SELECT chunk_id, kop || ' ' || tekst FROM chunk WHERE corpus = ?",
                (corpus,))
    con.commit()
    print(f"{len(rijen)} chunks opgeslagen in corpus '{corpus}'")

    if alleen_chunks:
        print("--alleen-chunks: embedden overgeslagen (Ollama niet nodig).")
        return

    ontbreekt = [r[0] for r in con.execute(
        "SELECT DISTINCT c.tekst_hash FROM chunk c "
        "LEFT JOIN vector v ON v.tekst_hash = c.tekst_hash AND v.model = ? "
        "WHERE c.corpus = ? AND v.tekst_hash IS NULL", (model, corpus))]

    hergebruikt = len({r[5] for r in rijen}) - len(ontbreekt)
    print(f"{hergebruikt} vectoren hergebruikt, {len(ontbreekt)} nog te embedden")
    if not ontbreekt:
        return

    start = time.perf_counter()
    for i, h in enumerate(ontbreekt, 1):
        rij = con.execute(
            "SELECT kop, tekst FROM chunk WHERE tekst_hash = ? LIMIT 1", (h,)).fetchone()
        vec = normaliseer(embed(f"{rij['kop']}\n{rij['tekst']}".strip(), model))
        con.execute("INSERT OR REPLACE INTO vector (tekst_hash, model, dim, vec) "
                    "VALUES (?,?,?,?)", (h, model, len(vec), naar_blob(vec)))
        if i % 100 == 0 or i == len(ontbreekt):
            verstreken = time.perf_counter() - start
            resterend = verstreken / i * (len(ontbreekt) - i)
            print(f"  {i}/{len(ontbreekt)}  ({verstreken:.0f}s verstreken, "
                  f"~{resterend:.0f}s resterend)", flush=True)
            con.commit()
    con.commit()


# ---------------------------------------------------------------------------
# VERSIETABEL (§4)
# ---------------------------------------------------------------------------
def _corpus_hash(jsonl_paden: list[str]) -> str:
    h = hashlib.sha256()
    for pad in sorted(jsonl_paden):
        h.update(Path(pad).read_bytes())
    return h.hexdigest()


def registreer_versie(con: sqlite3.Connection, chunk_strategie: str,
                       jsonl_paden: list[str], model: str = EMBED_MODEL,
                       toelichting: str = "") -> None:
    """Schrijft een index_versie-rij voor de HUIDIGE inhoud van de index.

    Los van indexeer(): een index die vóór dit bestand bestond (zoals de
    huidige data/rag_index.db) kan zo alsnog een versie krijgen zonder
    opnieuw te embedden.
    """
    aantal = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
    dim_rij = con.execute(
        "SELECT dim FROM vector WHERE model = ? LIMIT 1", (model,)).fetchone()
    if dim_rij is None:
        raise SystemExit(f"geen vectoren voor model '{model}' — eerst indexeren")
    con.execute(
        "INSERT INTO index_versie "
        "(gebouwd_op, embed_model, dim, chunk_strategie, corpus_hash, "
        " aantal_chunks, toelichting) VALUES (?,?,?,?,?,?,?)",
        (time.strftime("%Y-%m-%d"), model, dim_rij[0], chunk_strategie,
         _corpus_hash(jsonl_paden), aantal, toelichting),
    )
    con.commit()
    print(f"index_versie geschreven: {chunk_strategie}, {aantal} chunks, model {model}")


def toon_versie(con: sqlite3.Connection) -> None:
    rijen = con.execute(
        "SELECT * FROM index_versie ORDER BY gebouwd_op DESC, rowid DESC").fetchall()
    if not rijen:
        print("geen index_versie-rij; nog niet geregistreerd "
              "(python -m backend.rag.index versie --schrijf)")
        return
    for r in rijen:
        print(f"{r['gebouwd_op']}  {r['chunk_strategie']:<20} {r['embed_model']} "
              f"dim={r['dim']}  {r['aantal_chunks']} chunks  {r['toelichting'] or ''}")


# ---------------------------------------------------------------------------
# OPRUIMEN (§2.1) — nooit automatisch, alleen als los commando
# ---------------------------------------------------------------------------
def opruimen(con: sqlite3.Connection, db_pad: str) -> None:
    """Verwijdert vectoren zonder chunk en VACUUMt.

    Draai dit pas nadat een nieuwe chunkstrategie zich bewezen heeft (§2.1):
    zolang oude vectoren blijven staan, is teruggaan naar de vorige strategie
    gratis — de hashes bestaan nog, er hoeft niets opnieuw geëmbed te worden.
    """
    voor_bestand = Path(db_pad).stat().st_size
    voor_aantal = con.execute("SELECT COUNT(*) FROM vector").fetchone()[0]

    cursor = con.execute(
        "DELETE FROM vector WHERE tekst_hash NOT IN (SELECT tekst_hash FROM chunk)")
    verwijderd = cursor.rowcount
    con.commit()
    con.execute("VACUUM")

    na_bestand = Path(db_pad).stat().st_size
    print(f"{verwijderd} vectoren verwijderd ({voor_aantal} -> {voor_aantal - verwijderd})")
    print(f"bestand: {voor_bestand / 1e6:.0f} MB -> {na_bestand / 1e6:.0f} MB")


# ---------------------------------------------------------------------------
# STATUS
# ---------------------------------------------------------------------------
def cmd_status(con: sqlite3.Connection) -> None:
    print(f"{'corpus':<14} {'chunks':>8} {'geembed':>8}  bronnen")
    print("-" * 56)
    for r in con.execute(
            "SELECT c.corpus, COUNT(*) n, "
            "  SUM(CASE WHEN v.tekst_hash IS NULL THEN 0 ELSE 1 END) g, "
            "  COUNT(DISTINCT c.bron) b "
            "FROM chunk c LEFT JOIN vector v "
            "  ON v.tekst_hash = c.tekst_hash AND v.model = ? "
            "GROUP BY c.corpus ORDER BY 1", (EMBED_MODEL,)):
        print(f"{r['corpus']:<14} {r['n']:>8} {r['g'] or 0:>8}  {r['b']}")
    tot = con.execute("SELECT COUNT(*) n, SUM(LENGTH(vec)) b FROM vector").fetchone()
    print(f"\n{tot['n'] or 0} vectoren, {(tot['b'] or 0) / 1e6:.1f} MB")
    toon_versie(con)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="RAG-index bouwen (chunken, embedden, FTS, versie)")
    p.add_argument("--db", default=INDEX_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("indexeer", help="JSONL inlezen en embedden")
    pi.add_argument("corpus")
    pi.add_argument("jsonl")
    pi.add_argument("--alleen-chunks", action="store_true",
                     help="alleen chunken, niet embedden (werkt zonder Ollama)")

    sub.add_parser("status", help="wat staat er in de index")

    pv = sub.add_parser("versie", help="index_versie schrijven of tonen")
    pv.add_argument("--schrijf", action="store_true")
    pv.add_argument("--strategie", default="sectie")
    pv.add_argument("--jsonl", nargs="+",
                     default=["data/corpus_songs.jsonl", "data/corpus_artiesten.jsonl"])
    pv.add_argument("--toelichting", default="")

    sub.add_parser("opruimen", help="vectoren zonder chunk verwijderen + VACUUM (§2.1)")

    a = p.parse_args()
    con = open_index(a.db)

    if a.cmd == "indexeer":
        indexeer(con, a.corpus, a.jsonl, alleen_chunks=a.alleen_chunks)
    elif a.cmd == "versie":
        if a.schrijf:
            registreer_versie(con, a.strategie, a.jsonl, toelichting=a.toelichting)
        else:
            toon_versie(con)
    elif a.cmd == "opruimen":
        opruimen(con, a.db)
    else:
        cmd_status(con)


if __name__ == "__main__":
    main()
