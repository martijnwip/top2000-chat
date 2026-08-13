"""Voert een gekeurde query uit tegen top2000.db. Zie spec §3.4.

Verwacht een query die al langs sql/veiligheid.py is gekeurd. Deze module
voegt de tweede slotlaag toe: de verbinding is alleen-lezen, dus zelfs een
query die de keuring omzeilt kan de database niet wijzigen.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

TIMEOUT_S = 5.0
STANDAARD_LIMIT = 200

_LIMIT_PATROON_AANWEZIG = re.compile(r"\bLIMIT\b", re.IGNORECASE)


class QueryTimeout(Exception):
    """De query liep langer dan TIMEOUT_S seconden en is afgebroken."""


class QueryFout(Exception):
    """SQLite gaf een fout bij het uitvoeren van de query."""


@dataclass
class UitvoerResultaat:
    sql: str  # de daadwerkelijk uitgevoerde query, incl. eventueel toegevoegde LIMIT
    rijen: list[dict]
    looptijd_s: float


def _met_limit(sql: str) -> str:
    if _LIMIT_PATROON_AANWEZIG.search(sql):
        return sql
    return f"{sql} LIMIT {STANDAARD_LIMIT}"


def voer_uit(sql: str, db_pad: str = "top2000.db") -> UitvoerResultaat:
    """Voert `sql` read-only uit. `sql` moet al gekeurd zijn door veiligheid.keur."""

    uit_te_voeren = _met_limit(sql)

    verbinding = sqlite3.connect(f"file:{db_pad}?mode=ro", uri=True)
    verbinding.row_factory = sqlite3.Row

    start = time.monotonic()

    def _bewaak_timeout() -> int:
        return 1 if time.monotonic() - start > TIMEOUT_S else 0

    # n=1000: elke ~1000 VM-instructies checkt SQLite of de handler moet afbreken
    verbinding.set_progress_handler(_bewaak_timeout, 1000)

    try:
        cursor = verbinding.execute(uit_te_voeren)
        rijen = [dict(rij) for rij in cursor.fetchall()]
    except sqlite3.OperationalError as fout:
        if time.monotonic() - start > TIMEOUT_S:
            raise QueryTimeout(
                f"Query afgebroken na {TIMEOUT_S:.0f} seconden."
            ) from fout
        raise QueryFout(str(fout)) from fout
    except sqlite3.Error as fout:
        raise QueryFout(str(fout)) from fout
    finally:
        verbinding.close()

    looptijd_s = time.monotonic() - start
    return UitvoerResultaat(sql=uit_te_voeren, rijen=rijen, looptijd_s=looptijd_s)
