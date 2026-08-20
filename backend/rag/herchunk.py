"""Knipt bestaande 'verhaal'-chunks opnieuw, van sectie naar zinsvenster.

Chunkstrategie 'zinsvenster-500-25' uit `rag-chunkstrategie-en-meting.md` §2,
stap 9 van de bouwvolgorde in §7. Werkt op een bestaand JSONL-corpus (bv.
`data/corpus_songs.jsonl`) en herknipt alleen de rijen met
`meta.soort_blok == 'verhaal'` — feitenblokken gaan ongewijzigd door, die zijn
al kort en gestructureerd (§2 "Wat níet verandert"). Geen Ollama nodig, dit is
alleen de knipstap; embedden gebeurt daarna met `backend.rag.index indexeer`.

WAAROM ZINNEN EN NIET SECTIES
------------------------------
De huidige sectie-chunks zijn 2.000 à 2.500 tekens. Daarin verdrinkt de ene
zin die een omschrijvingsvraag beantwoordt ("de tekst gaat over...") tussen
alinea's over opnamen en hitnoteringen — gemeten in §1. Kleinere vensters van
een paar zinnen houden die ene rake zin dicht bij zijn eigen betekenis, met
een beetje overlap zodat een gedachte die over een zinsgrens loopt niet
doormidden wordt geknipt.

DE KOP GAAT ONGEWIJZIGD MEE
-----------------------------
Elk venster erft de `kop` van de sectie waaruit het komt (bv. "Bohemian
Rhapsody — Queen · Tekst en betekenis"). `index.indexeer()` plakt die kop al
vóór de tekst voordat er geëmbed wordt — dat is waar §2 "kop meegeëmbed: ja"
op doelt, dit bestand hoeft dat niet apart te doen.

DE ZINSSPLITSER IS EEN HEURISTIEK, GEEN NLP-MODEL
----------------------------------------------------
Regex op '.', '!', '?' gevolgd door een hoofdletter, cijfer of aanhalingsteken.
Geen nltk/spacy: die staan nergens anders in dit project en dit hoeft niet
perfect te zijn — een enkele foute knip bij een afkorting kost hooguit dat één
venster net iets anders loopt, en dat valt bij de eval op als het raak treft.

Gebruik:
    python -m backend.rag.herchunk data/corpus_songs.jsonl > data/corpus_songs_zinsvenster.jsonl
"""
from __future__ import annotations

import json
import re
import sys

DOELGROOTTE = 500   # mediaan zin ~106 tekens, dus ~4-5 zinnen per venster
MINIMUM = 200       # kortere restjes plakken aan het vorige venster
MAXIMUM = 800       # harde bovengrens; langere zinnen worden op komma gesplitst
OVERLAP_FRACTIE = 0.25

_ZINSPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9\"'„“(])")


def zinnen_splitsen(tekst: str) -> list[str]:
    tekst = re.sub(r"\s+", " ", tekst).strip()
    if not tekst:
        return []
    return [z.strip() for z in _ZINSPLIT.split(tekst) if z.strip()]


def _hard_split(stuk: str, maximum: int) -> list[str]:
    """Laatste redmiddel als er ook geen komma's zijn (bv. een tracklist
    zonder leestekens): knip op woordgrenzen bij `maximum` tekens. Dit is de
    enige plek die de harde bovengrens ook zonder leestekens garandeert."""
    if len(stuk) <= maximum:
        return [stuk]
    woorden = stuk.split(" ")
    stukken: list[str] = []
    huidig = ""
    for woord in woorden:
        kandidaat = f"{huidig} {woord}" if huidig else woord
        if len(kandidaat) > maximum and huidig:
            stukken.append(huidig)
            huidig = woord
        else:
            huidig = kandidaat
    if huidig:
        stukken.append(huidig)
    return stukken


def _splits_lange_zin(zin: str, maximum: int = MAXIMUM) -> list[str]:
    """Een zin langer dan `maximum` wordt op komma gesplitst (§2), en als dat
    niet genoeg is (geen komma's) alsnog op woordgrenzen — zie `_hard_split`."""
    if len(zin) <= maximum:
        return [zin]
    stukken: list[str] = []
    huidig = ""
    for deel in zin.split(", "):
        kandidaat = f"{huidig}, {deel}" if huidig else deel
        if len(kandidaat) > maximum and huidig:
            stukken.append(huidig)
            huidig = deel
        else:
            huidig = kandidaat
    if huidig:
        stukken.append(huidig)
    return [s for stuk in stukken for s in _hard_split(stuk, maximum)]


def vensters(tekst: str, doelgrootte: int = DOELGROOTTE, minimum: int = MINIMUM,
             maximum: int = MAXIMUM, overlap_fractie: float = OVERLAP_FRACTIE) -> list[str]:
    """Knipt tekst in vensters van ~doelgrootte tekens met overlap tussen vensters.

    Grof gezegd: vul een venster met zinnen tot het de doelgrootte haalt (nooit
    voorbij maximum), begin het volgende venster een stukje terug zodat er
    overlap ontstaat, en plak een te kort laatste restje aan het venster
    ervoor in plaats van het als eigen chunk te laten staan.
    """
    elementen: list[str] = []
    for zin in zinnen_splitsen(tekst):
        elementen.extend(_splits_lange_zin(zin, maximum))
    if not elementen:
        return []

    ruwe_vensters: list[list[str]] = []
    i, n = 0, len(elementen)
    while i < n:
        j, lengte = i, 0
        while j < n:
            toevoeging = len(elementen[j]) + (1 if lengte else 0)  # spatie
            if lengte + toevoeging > maximum and j > i:
                break
            lengte += toevoeging
            j += 1
            if lengte >= doelgrootte:
                break
        ruwe_vensters.append(elementen[i:j])
        if j >= n:
            break
        overlap = max(1, round((j - i) * overlap_fractie))
        i = max(i + 1, j - overlap)  # altijd vooruitgang, ook bij venster van 1 zin

    teksten = [" ".join(v) for v in ruwe_vensters]

    samengevoegd: list[str] = []
    for t in teksten:
        # Alleen plakken als dat niet alsnog de harde bovengrens doorbreekt —
        # die weegt zwaarder dan het zachte streven naar een minimumlengte.
        if (samengevoegd and len(t) < minimum
                and len(samengevoegd[-1]) + 1 + len(t) <= maximum):
            samengevoegd[-1] = f"{samengevoegd[-1]} {t}"
        else:
            samengevoegd.append(t)
    return samengevoegd


def herchunk_document(d: dict) -> list[dict]:
    """Eén regel uit het bronbestand -> één of meer chunks.

    Feitenblokken (en alles zonder `soort_blok == 'verhaal'`) gaan ongewijzigd
    door als lijst van één element, zodat de aanroeper niet hoeft te weten
    welke rijen wel of niet herknipt zijn.
    """
    if d.get("meta", {}).get("soort_blok") != "verhaal":
        return [d]

    stukken = vensters(d.get("tekst", ""))
    if not stukken:
        return []
    if len(stukken) == 1:
        # Bron blijft ongewijzigd (geen :v-suffix, dit document had geen
        # venstering nodig), maar de TEKST moet wel de verwerkte versie zijn
        # — anders omzeilt de rauwe originele tekst de harde bovengrens die
        # vensters()/_hard_split net had gegarandeerd.
        return [{**d, "tekst": stukken[0]}]

    return [
        {**d, "bron": f"{d['bron']}:v{i}", "tekst": stuk}
        for i, stuk in enumerate(stukken, 1)
    ]


def herchunk_bestand(regels: list[dict]) -> list[dict]:
    uit: list[dict] = []
    for d in regels:
        uit.extend(herchunk_document(d))
    return uit


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("gebruik: python -m backend.rag.herchunk <jsonl-bestand>")

    with open(sys.argv[1], encoding="utf-8") as f:
        regels = [json.loads(r) for r in f if r.strip()]

    verhaal_voor = sum(1 for d in regels if d.get("meta", {}).get("soort_blok") == "verhaal")
    feiten = sum(1 for d in regels if d.get("meta", {}).get("soort_blok") != "verhaal")

    uit = herchunk_bestand(regels)
    for d in uit:
        print(json.dumps(d, ensure_ascii=False))

    verhaal_na = len(uit) - feiten
    lengtes = [len(d["tekst"]) for d in uit
               if d.get("meta", {}).get("soort_blok") == "verhaal"]
    gem = sum(lengtes) / len(lengtes) if lengtes else 0
    print(
        f"{len(regels)} regels in -> {len(uit)} chunks uit "
        f"({feiten} feitenblokken ongewijzigd, {verhaal_voor} verhaal-chunks "
        f"-> {verhaal_na} vensters, gemiddeld {gem:.0f} tekens)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
