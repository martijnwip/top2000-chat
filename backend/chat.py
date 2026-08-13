"""De twee modelstappen uit spec §4, interface-onafhankelijk.

Stap 1 (vraag_naar_sql) vertaalt een vraag naar een gekeurde query en voert
die uit. Stap 2 (rijen_naar_antwoord) formuleert daar een antwoord omheen.
Tussen die twee stappen rekent alleen SQLite — het model ziet in stap 2 geen
schema en geen query, alleen de rijen die eruit kwamen.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from backend import llm
from backend.sql import schema_prompt
from backend.sql.uitvoeren import QueryFout, QueryTimeout, voer_uit
from backend.sql.veiligheid import OnveiligeQuery, keur

MAX_HERKANSINGEN = 2
MAX_RIJEN_IN_PROMPT = 50
SENTINEL_GEEN_QUERY = "GEEN_QUERY_MOGELIJK"

_CODEBLOK_PATROON = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

ANTWOORDREGELS = """\
Je formuleert een antwoord op een vraag over de NPO Radio 2 Top 2000, op
basis van de meegegeven rijen uit de database. Regels, zie spec §5:

Herkomst
- Elk cijfer in het antwoord komt uit de meegegeven rijen. Geen enkel getal
  uit eigen kennis, ook niet als het klopt.

Volledigheid
- Staat er "(totaal ... rijen, eerste 50 getoond)" bij de rijen, noem dat
  totaal en meld dat een selectie wordt getoond.
- Bij meerdere schrijfwijzen van een artiest in de rijen: noem welke zijn
  meegeteld.
- NULL in een verrijkt veld ('release_jaar', 'land', 'duur_ms') heet "nog
  niet opgehaald", niet "onbekend".

Vorm
- Antwoord in de taal van de vraag; standaard Nederlands.
- Eerst het directe antwoord, daarna pas de onderbouwing.
- Meer dan drie rijen: een uitgelijnde tekstkolom, geen Markdown-pipes (|).
- Geen song_id, geen SQL en geen ruwe JSON in de tekst.
- Derde persoon: geen "ik", "wij", "help je" of vergelijkbare aanspreekvorm.
- duur_ms staat in milliseconden; reken om naar mm:ss door naar beneden af
  te ronden op hele seconden (floor), zoals gebruikelijk bij nummerduren:
  296906 ms wordt 4:56, niet 4:57.

Grenzen
- Geen speculatie over oorzaken van stijgingen of dalingen.
- Geen voorspellingen over toekomstige jaargangen.
"""


@dataclass
class SqlResultaat:
    vraag: str
    sql: str | None
    rijen: list[dict]
    looptijd_s: float
    pogingen: int
    gelukt: bool
    foutmelding: str | None


@dataclass
class AntwoordResultaat:
    vraag: str
    antwoord: str
    sql: str | None
    rijen: list[dict]
    pogingen: int
    gelukt: bool
    looptijd_s: float


def _strip_sql(ruw: str) -> str:
    return _CODEBLOK_PATROON.sub("", ruw).strip()


def vraag_naar_sql(
    vraag: str,
    model: str = llm.STANDAARD_MODEL,
    max_herkansingen: int = MAX_HERKANSINGEN,
) -> SqlResultaat:
    """Genereert en voert een query uit, met maximaal `max_herkansingen` retries.

    Een afgekeurde of vastlopende query gaat met de foutmelding terug naar
    het model. Nul rijen is een geldig antwoord en geeft geen herkansing.
    """

    start = time.monotonic()
    prompt = f"Vraag: {vraag}\nSQL:"
    laatste_kandidaat: str | None = None
    laatste_fout: str | None = None
    pogingen = 0

    while pogingen <= max_herkansingen:
        pogingen += 1
        ruwe_output = llm.genereer(prompt, systeem=schema_prompt.SYSTEEMPROMPT, model=model)
        kandidaat = _strip_sql(ruwe_output)
        laatste_kandidaat = kandidaat

        if kandidaat.strip().upper() == SENTINEL_GEEN_QUERY:
            return SqlResultaat(
                vraag=vraag,
                sql=None,
                rijen=[],
                looptijd_s=time.monotonic() - start,
                pogingen=pogingen,
                gelukt=False,
                foutmelding="Dit vraagt om een wijziging; de applicatie is alleen-lezen.",
            )

        try:
            gekeurd = keur(kandidaat)
        except OnveiligeQuery as fout:
            laatste_fout = str(fout)
            prompt += (
                f"\n{kandidaat}\n\nDeze query is afgekeurd: {laatste_fout}\n"
                "Geef een nieuwe query.\nSQL:"
            )
            continue

        try:
            resultaat = voer_uit(gekeurd)
        except (QueryTimeout, QueryFout) as fout:
            laatste_fout = str(fout)
            prompt += (
                f"\n{kandidaat}\n\nDeze query gaf een fout: {laatste_fout}\n"
                "Geef een nieuwe query.\nSQL:"
            )
            continue

        return SqlResultaat(
            vraag=vraag,
            sql=gekeurd,
            rijen=resultaat.rijen,
            looptijd_s=time.monotonic() - start,
            pogingen=pogingen,
            gelukt=True,
            foutmelding=None,
        )

    return SqlResultaat(
        vraag=vraag,
        sql=laatste_kandidaat,
        rijen=[],
        looptijd_s=time.monotonic() - start,
        pogingen=pogingen,
        gelukt=False,
        foutmelding=f"Kon de vraag niet in een geldige query omzetten. Laatste fout: {laatste_fout}",
    )


def _rijen_voor_prompt(rijen: list[dict]) -> str:
    if len(rijen) <= MAX_RIJEN_IN_PROMPT:
        return str(rijen)
    getoond = rijen[: MAX_RIJEN_IN_PROMPT]
    return f"(totaal {len(rijen)} rijen, eerste {MAX_RIJEN_IN_PROMPT} getoond)\n{getoond}"


def rijen_naar_antwoord(vraag: str, rijen: list[dict], model: str = llm.STANDAARD_MODEL) -> str:
    """Stap 2: formuleert een antwoord bij `rijen`. Geen schema, geen SQL in de prompt."""

    prompt = f"Vraag: {vraag}\nRijen: {_rijen_voor_prompt(rijen)}\nAntwoord:"
    return llm.genereer(prompt, systeem=ANTWOORDREGELS, model=model, temperature=0.2).strip()


def antwoord(
    vraag: str,
    model: str = llm.STANDAARD_MODEL,
    max_herkansingen: int = MAX_HERKANSINGEN,
) -> AntwoordResultaat:
    """De volledige route van vraag naar antwoordtekst — spec §4 en §5.

    Een afgekeurde/vastgelopen query en een lege uitkomst krijgen een vaste
    tekst zonder tweede modelaanroep: zo kan geen enkel getal uit
    modelkennis in het antwoord sluipen op het punt waar er geen rijen zijn
    om op te baseren.
    """

    start = time.monotonic()
    sql_resultaat = vraag_naar_sql(vraag, model=model, max_herkansingen=max_herkansingen)

    if not sql_resultaat.gelukt:
        antwoordtekst = (
            "Deze vraag laat zich niet vertalen naar een geldige, alleen-lezen "
            "SQL-query over de Top 2000-data."
        )
    elif not sql_resultaat.rijen:
        antwoordtekst = "Dat staat niet in de Top 2000-data (jaargangen 1999 t/m 2025)."
    else:
        antwoordtekst = rijen_naar_antwoord(vraag, sql_resultaat.rijen, model=model)

    return AntwoordResultaat(
        vraag=vraag,
        antwoord=antwoordtekst,
        sql=sql_resultaat.sql,
        rijen=sql_resultaat.rijen,
        pogingen=sql_resultaat.pogingen,
        gelukt=sql_resultaat.gelukt,
        looptijd_s=time.monotonic() - start,
    )
