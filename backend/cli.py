"""Commandoregel-interface. Zie docs/spec-top2000-chat.md §2a.

Aanroep: python -m backend.cli <subcommando>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml

from backend import beantwoorder, chat, llm, verbruik
from backend.rag import antwoord as rag_antwoord
from backend.rag import index as rag_index
from backend.rag import zoek as rag_zoek
from backend.sql.uitvoeren import QueryFout, QueryTimeout, voer_uit
from backend.sql.veiligheid import OnveiligeQuery, keur

DB_PAD = "top2000.db"
OLLAMA_URL = "http://localhost:11434"
STANDAARD_MODEL = llm.STANDAARD_MODEL
TESTSET_PAD = "tests/testset-top2000-chat.yaml"


def formatteer_rijen(rijen: list[dict]) -> str:
    """Lijnt rijen uit in tekstkolommen. Geen Markdown-pipes, zie spec §5 'Vorm'."""

    if not rijen:
        return "(geen rijen)"

    kolommen = list(rijen[0].keys())
    breedtes = {
        kolom: max(len(kolom), max(len(str(rij.get(kolom, ""))) for rij in rijen))
        for kolom in kolommen
    }
    kop = "  ".join(kolom.ljust(breedtes[kolom]) for kolom in kolommen)
    lijn = "  ".join("-" * breedtes[kolom] for kolom in kolommen)
    inhoud = [
        "  ".join(str(rij.get(kolom, "")).ljust(breedtes[kolom]) for kolom in kolommen)
        for rij in rijen
    ]
    return "\n".join([kop, lijn, *inhoud])


def cmd_check(args: argparse.Namespace) -> int:
    ok = True

    if not Path(DB_PAD).exists():
        print(f"database:  NIET GEVONDEN ({DB_PAD})", file=sys.stderr)
        ok = False
    else:
        try:
            verbinding = sqlite3.connect(f"file:{DB_PAD}?mode=ro", uri=True)
            (aantal_songs,) = verbinding.execute("SELECT COUNT(*) FROM songs").fetchone()
            (aantal_noteringen,) = verbinding.execute("SELECT COUNT(*) FROM notering").fetchone()
            verbinding.close()
            print(f"database:  ok — {aantal_songs} nummers, {aantal_noteringen} noteringen ({DB_PAD})")
        except sqlite3.Error as fout:
            print(f"database:  FOUT — {fout}", file=sys.stderr)
            ok = False

    if not Path(beantwoorder.RAG_DB_PAD).exists():
        print(f"rag-index: NIET GEVONDEN ({beantwoorder.RAG_DB_PAD})", file=sys.stderr)
        ok = False
    else:
        try:
            rverbinding = rag_index.open_index(beantwoorder.RAG_DB_PAD)
            versie = rverbinding.execute(
                "SELECT embed_model, aantal_chunks, chunk_strategie "
                "FROM index_versie ORDER BY gebouwd_op DESC, rowid DESC LIMIT 1").fetchone()
            rverbinding.close()
            if versie:
                print(f"rag-index: ok — {versie['aantal_chunks']} chunks, "
                      f"{versie['chunk_strategie']}, model {versie['embed_model']} "
                      f"({beantwoorder.RAG_DB_PAD})")
            else:
                print(f"rag-index: ok, maar geen index_versie geregistreerd "
                      f"({beantwoorder.RAG_DB_PAD})", file=sys.stderr)
        except sqlite3.Error as fout:
            print(f"rag-index: FOUT — {fout}", file=sys.stderr)
            ok = False

    try:
        respons = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        respons.raise_for_status()
        modellen = {model["name"] for model in respons.json().get("models", [])}
        print(f"ollama:    ok — bereikbaar op {OLLAMA_URL}")
        for label, model_naam in (
            ("model (sql)", STANDAARD_MODEL),
            ("model (rag-generatie)", rag_antwoord.GEN_MODEL),
            ("model (embedden)", rag_index.EMBED_MODEL),
        ):
            # Ollama registreert een naam zonder tag altijd als ':latest'
            # ('bge-m3' staat in 'ollama list' als 'bge-m3:latest'), maar
            # lost 'bge-m3' bij een aanroep gewoon op. Beide vormen tellen.
            if model_naam in modellen or f"{model_naam}:latest" in modellen:
                print(f"{label}: ok — {model_naam} is geladen")
            else:
                print(
                    f"{label}: NIET GEVONDEN — {model_naam} staat niet in 'ollama list'",
                    file=sys.stderr,
                )
                ok = False
    except requests.exceptions.RequestException as fout:
        print(f"ollama:    NIET BEREIKBAAR op {OLLAMA_URL} — {fout}", file=sys.stderr)
        ok = False

    if verbruik.MACMON_BESCHIKBAAR:
        print("verbruik:  ok — macmon (echte cpu+gpu-meting, geen sudo)")
    else:
        print(
            "verbruik:  codecarbon-schatting — macmon niet beschikbaar "
            "(alleen Apple Silicon; 'brew install macmon'). Dit cijfer sluit de gpu uit.",
            file=sys.stderr,
        )

    return 0 if ok else 2


def cmd_run(args: argparse.Namespace) -> int:
    try:
        gekeurd = keur(args.query)
    except OnveiligeQuery as fout:
        print(f"query afgekeurd: {fout}", file=sys.stderr)
        return 1

    try:
        resultaat = voer_uit(gekeurd, db_pad=DB_PAD)
    except (QueryTimeout, QueryFout) as fout:
        print(str(fout), file=sys.stderr)
        return 1

    print(formatteer_rijen(resultaat.rijen))
    print(
        f"\n{len(resultaat.rijen)} rij(en) — {resultaat.looptijd_s * 1000:.1f} ms",
        file=sys.stderr,
    )
    return 0


def cmd_sql(args: argparse.Namespace) -> int:
    try:
        resultaat = chat.vraag_naar_sql(args.vraag, model=args.model)
    except llm.OllamaFout as fout:
        print(str(fout), file=sys.stderr)
        return 2

    if not resultaat.gelukt:
        print(resultaat.foutmelding, file=sys.stderr)
        return 1

    print(resultaat.sql)
    print()
    print(formatteer_rijen(resultaat.rijen))
    print(
        f"\n{len(resultaat.rijen)} rij(en) — {resultaat.pogingen} poging(en) — "
        f"{resultaat.looptijd_s * 1000:.1f} ms",
        file=sys.stderr,
    )
    return 0


def _formatteer_bronnen(bronnen: list[dict]) -> str:
    if not bronnen:
        return "(geen bronnen)"
    rijen = [
        {"bron": b["bron"], "kop": b["kop"] or "", "cosine": f"{b['cosine']:.3f}" if b.get("cosine") is not None else "—"}
        for b in bronnen
    ]
    return formatteer_rijen(rijen)


def _druk_resultaat_af(resultaat: beantwoorder.GerouteerdResultaat, args: argparse.Namespace) -> int:
    if args.geen_tekst:
        if resultaat.pad == "sql":
            if resultaat.sql is None:
                print(resultaat.antwoord, file=sys.stderr)
                return 1
            print(resultaat.sql)
            print()
            print(formatteer_rijen(resultaat.rijen))
        else:
            if not resultaat.bronnen:
                print(resultaat.antwoord, file=sys.stderr)
                return 1
            print(_formatteer_bronnen(resultaat.bronnen))
        return 0 if resultaat.heeft_inhoud else 1

    if args.json:
        print(
            json.dumps(
                {
                    "vraag": resultaat.vraag,
                    "pad": resultaat.pad,
                    "regel": resultaat.regel,
                    "antwoord": resultaat.antwoord,
                    "sql": resultaat.sql,
                    "rijen": resultaat.rijen,
                    "pogingen": resultaat.pogingen,
                    "bronnen": resultaat.bronnen,
                    "cosine": resultaat.cosine,
                    "energie_wh": resultaat.energie_wh,
                    "co2_g": resultaat.co2_g,
                    "verbruik_bron": resultaat.verbruik_bron,
                    "verbruik_dekking": resultaat.verbruik_dekking,
                },
                ensure_ascii=False,
            )
        )
        return 0 if resultaat.heeft_inhoud else 1

    print(resultaat.antwoord)
    if args.show_sql:
        verbruik_regel = (
            f"verbruik: {resultaat.energie_wh:.3f} Wh, {resultaat.co2_g:.3f} g CO2 "
            f"({resultaat.verbruik_bron}: {resultaat.verbruik_dekking})"
            if resultaat.verbruik_bron
            else "verbruik: niet gemeten"
        )
        if resultaat.pad == "sql":
            print(
                f"\npad: sql  (regel: {resultaat.regel})\n"
                f"SQL: {resultaat.sql}\n"
                f"{len(resultaat.rijen)} rij(en) — {resultaat.pogingen} poging(en) — "
                f"{resultaat.looptijd_s * 1000:.1f} ms\n"
                f"{verbruik_regel}",
                file=sys.stderr,
            )
        else:
            cosine_tekst = f"{resultaat.cosine:.3f}" if resultaat.cosine is not None else "—"
            print(
                f"\npad: {resultaat.pad}  (regel: {resultaat.regel})\n"
                f"bronnen:\n{_formatteer_bronnen(resultaat.bronnen)}\n"
                f"beste cosine: {cosine_tekst}  —  {resultaat.looptijd_s:.1f}s\n"
                f"{verbruik_regel}",
                file=sys.stderr,
            )
    return 0 if resultaat.heeft_inhoud else 1


def cmd_ask(args: argparse.Namespace) -> int:
    try:
        resultaat = beantwoorder.beantwoord(args.vraag, model=args.model)
    except (llm.OllamaFout, rag_zoek.ModelMismatch) as fout:
        print(str(fout), file=sys.stderr)
        return 2
    return _druk_resultaat_af(resultaat, args)


def cmd_chat(args: argparse.Namespace) -> int:
    print(
        "Top2000 Chat — /exit om te stoppen, /pad voor het laatst gekozen pad, "
        "/sql voor de laatste query.",
        file=sys.stderr,
    )
    laatste: beantwoorder.GerouteerdResultaat | None = None
    while True:
        try:
            regel = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            break
        if not regel:
            continue
        if regel == "/exit":
            break
        if regel == "/pad":
            print(f"{laatste.pad}  (regel: {laatste.regel})" if laatste else "(nog geen vraag)")
            continue
        if regel == "/sql":
            if laatste and laatste.pad == "sql" and laatste.sql:
                print(laatste.sql)
            elif laatste:
                print(f"(geen SQL — de laatste vraag ging naar pad '{laatste.pad}')")
            else:
                print("(nog geen vraag)")
            continue
        try:
            laatste = beantwoorder.beantwoord(regel, model=args.model)
        except (llm.OllamaFout, rag_zoek.ModelMismatch) as fout:
            print(str(fout), file=sys.stderr)
            continue
        _druk_resultaat_af(laatste, args)
    return 0


def _voeg_antwoordvlaggen_toe(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--show-sql", action="store_true", dest="show_sql",
        help="toont het gekozen pad plus de query (sql) of de opgehaalde bronnen (rag)",
    )
    parser.add_argument("--json", action="store_true", dest="json", help="machineleesbare uitvoer")
    parser.add_argument("--model", default=STANDAARD_MODEL, dest="model",
                         help="overschrijft het sql-model uit de config")
    parser.add_argument(
        "--geen-tekst", action="store_true", dest="geen_tekst",
        help="stopt vóór de antwoordtekst; toont de query+rijen (sql) of de bronnen (rag)",
    )


@dataclass
class CaseResultaat:
    case_id: str
    geslaagd: bool
    ontbrekend: list[str]
    onterecht_aanwezig: list[str]
    antwoord: str
    sql: str | None
    looptijd_s: float
    zelfcontrole_fout: str | None


def _laad_testset(pad: str = TESTSET_PAD) -> list[dict]:
    with open(pad, encoding="utf-8") as bestand:
        inhoud = yaml.safe_load(bestand)
    return inhoud["cases"]


def _voer_case_uit(case: dict, model: str) -> CaseResultaat:
    """Draait één testcase: zelfcontrole van controle_sql, dan de echte vraag.

    Zelfcontrole toetst alleen of controle_sql nog probleemloos draait tegen
    de huidige database (drift-detectie); geslaagd/gefaald van de case zelf
    hangt uitsluitend af van moet_bevatten/mag_niet op het modelantwoord —
    de beoordeling gaat op het resultaat, niet op de gegenereerde query.
    """

    zelfcontrole_fout: str | None = None
    controle_sql = case.get("controle_sql")
    if controle_sql:
        try:
            voer_uit(keur(controle_sql))
        except (OnveiligeQuery, QueryFout, QueryTimeout) as fout:
            zelfcontrole_fout = str(fout)

    resultaat = chat.antwoord(case["vraag"], model=model)
    antwoord_laag = resultaat.antwoord.lower()

    ontbrekend = [s for s in case.get("moet_bevatten") or [] if s.lower() not in antwoord_laag]
    onterecht_aanwezig = [s for s in case.get("mag_niet") or [] if s.lower() in antwoord_laag]

    return CaseResultaat(
        case_id=case["id"],
        geslaagd=not ontbrekend and not onterecht_aanwezig,
        ontbrekend=ontbrekend,
        onterecht_aanwezig=onterecht_aanwezig,
        antwoord=resultaat.antwoord,
        sql=resultaat.sql,
        looptijd_s=resultaat.looptijd_s,
        zelfcontrole_fout=zelfcontrole_fout,
    )


def cmd_test(args: argparse.Namespace) -> int:
    try:
        cases = _laad_testset()
    except (OSError, yaml.YAMLError) as fout:
        print(f"testset niet te laden: {fout}", file=sys.stderr)
        return 2

    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"geen case met id '{args.case}'", file=sys.stderr)
            return 2

    resultaten: list[CaseResultaat] = []
    for case in cases:
        try:
            resultaten.append(_voer_case_uit(case, model=args.model))
        except llm.OllamaFout as fout:
            print(str(fout), file=sys.stderr)
            return 2

    for resultaat in resultaten:
        status = "OK  " if resultaat.geslaagd else "FOUT"
        print(f"{status}  {resultaat.case_id}  ({resultaat.looptijd_s:.1f}s)")
        if resultaat.zelfcontrole_fout:
            print(
                f"      let op: controle_sql faalt tegen de huidige database — {resultaat.zelfcontrole_fout}",
                file=sys.stderr,
            )
        if not resultaat.geslaagd:
            if resultaat.ontbrekend:
                print(f"      ontbreekt in antwoord: {resultaat.ontbrekend}", file=sys.stderr)
            if resultaat.onterecht_aanwezig:
                print(f"      mag niet voorkomen: {resultaat.onterecht_aanwezig}", file=sys.stderr)
            print(f"      antwoord: {resultaat.antwoord!r}", file=sys.stderr)
            if resultaat.sql:
                print(f"      sql: {resultaat.sql}", file=sys.stderr)

    aantal_geslaagd = sum(1 for r in resultaten if r.geslaagd)
    gemiddelde_looptijd = (
        sum(r.looptijd_s for r in resultaten) / len(resultaten) if resultaten else 0.0
    )
    print(
        f"\nmodel: {args.model} — {aantal_geslaagd}/{len(resultaten)} geslaagd — "
        f"gemiddelde looptijd {gemiddelde_looptijd:.1f}s"
    )

    return 0 if aantal_geslaagd == len(resultaten) else 1


def bouw_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.cli")
    subparsers = parser.add_subparsers(dest="subcommando", required=True)

    p_check = subparsers.add_parser("check", help="status van database, Ollama en modelnaam")
    p_check.set_defaults(func=cmd_check)

    p_run = subparsers.add_parser("run", help="voert een handgeschreven query uit, geen model nodig")
    p_run.add_argument("query")
    p_run.set_defaults(func=cmd_run)

    p_sql = subparsers.add_parser("sql", help="alleen stap 1: toont de gegenereerde query en de rijen")
    p_sql.add_argument("vraag")
    p_sql.add_argument("--model", default=STANDAARD_MODEL, help="overschrijft het model uit de config")
    p_sql.set_defaults(func=cmd_sql)

    p_ask = subparsers.add_parser("ask", help="één vraag, antwoord naar stdout")
    p_ask.add_argument("vraag")
    _voeg_antwoordvlaggen_toe(p_ask)
    p_ask.set_defaults(func=cmd_ask)

    p_chat = subparsers.add_parser("chat", help="interactieve sessie")
    _voeg_antwoordvlaggen_toe(p_chat)
    p_chat.set_defaults(func=cmd_chat)

    p_test = subparsers.add_parser("test", help="draait tests/testset-top2000-chat.yaml")
    p_test.add_argument("--case", default=None, help="draait alleen de case met dit id")
    p_test.add_argument("--model", default=STANDAARD_MODEL, help="overschrijft het model uit de config")
    p_test.set_defaults(func=cmd_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = bouw_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
