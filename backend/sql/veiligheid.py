"""Keuring van door het model gegenereerde SQL, vóór die de database raakt.

Zie docs/spec-top2000-chat.md §3.3. Dit is geen algemene SQL-parser: de
toegestane vorm is smal (één SELECT/WITH over songs en notering), dus een
paar regexen volstaan om die vorm af te dwingen. Er is geen enkel slot dat
alleen op deze keuring vertrouwt — de verbinding in uitvoeren.py is
daarnaast alleen-lezen (3.3, laatste alinea).
"""

from __future__ import annotations

import re

TOEGESTANE_TABELLEN = {"songs", "notering"}

VERBODEN_TREFWOORDEN = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "REPLACE",
    "PRAGMA",
    "ATTACH",
    "DETACH",
    "VACUUM",
)

_START_PATROON = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_TREFWOORD_PATROON = re.compile(
    r"\b(" + "|".join(VERBODEN_TREFWOORDEN) + r")\b", re.IGNORECASE
)
_SQLITE_TABEL_PATROON = re.compile(r"\bsqlite_\w*", re.IGNORECASE)
_TABEL_REFERENTIE_PATROON = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
_GEDEFINIEERDE_NAAM_PATROON = re.compile(
    r"(?:\bWITH\s+|,\s*|\)\s+(?:AS\s+)?)([A-Za-z_][A-Za-z0-9_]*)\s*(?:AS\s*\(|,|\bJOIN\b|\bWHERE\b|$)",
    re.IGNORECASE,
)


class OnveiligeQuery(ValueError):
    """De query komt niet door de keuring; de reden staat in het bericht."""


def keur(query: str) -> str:
    """Keurt `query` en geeft de gekeurde tekst terug, of gooit OnveiligeQuery.

    Retourwaarde is de query zonder overbodige rand-whitespace, zodat de
    aanroeper dezelfde tekst kan uitvoeren die is gekeurd.
    """

    ruw = query.strip()
    if not ruw:
        raise OnveiligeQuery("Lege query.")

    if "--" in ruw or "/*" in ruw:
        raise OnveiligeQuery("Commentaartekens ('--' of '/* */') zijn niet toegestaan.")

    if not _START_PATROON.match(ruw):
        raise OnveiligeQuery("Query moet beginnen met SELECT of WITH.")

    trefwoord = _TREFWOORD_PATROON.search(ruw)
    if trefwoord:
        raise OnveiligeQuery(f"Trefwoord '{trefwoord.group(1).upper()}' is niet toegestaan.")

    if _SQLITE_TABEL_PATROON.search(ruw):
        raise OnveiligeQuery("Verwijzingen naar sqlite_-tabellen zijn niet toegestaan.")

    zonder_afsluiting = ruw[:-1] if ruw.endswith(";") else ruw
    if ";" in zonder_afsluiting:
        raise OnveiligeQuery("Meerdere statements zijn niet toegestaan.")

    gedefinieerd = {n.lower() for n in _GEDEFINIEERDE_NAAM_PATROON.findall(ruw)}
    for naam in _TABEL_REFERENTIE_PATROON.findall(ruw):
        naam_laag = naam.lower()
        if naam_laag not in TOEGESTANE_TABELLEN and naam_laag not in gedefinieerd:
            raise OnveiligeQuery(
                f"Tabel '{naam}' staat niet in het schema (toegestaan: "
                f"{', '.join(sorted(TOEGESTANE_TABELLEN))})."
            )

    return zonder_afsluiting.strip()
