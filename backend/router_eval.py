"""Meet de padkeuze uit router.py: gaat elke vraag naar het pad waar hij hoort?

Overgezet uit eval_path.py (top2000.ai), ongewijzigd in opzet.

WAT DIT MEET, EN WAT NIET
--------------------------
Alleen de KEUZE. Of het gekozen pad daarna een goed antwoord oplevert is een
andere meting (backend.cli test voor SQL, backend.rag.eval voor het ophalen).
Die scheiding is het punt: een fout antwoord op het juiste pad los je anders
op dan een fout antwoord doordat de vraag naar het verkeerde pad ging, en als
je die twee samen meet zie je het verschil niet.

WAAROM HIER GEEN MODEL AAN TE PAS KOMT
-----------------------------------------
router.py doet nul inferentie, dus deze meting ook niet. Dat maakt de uitkomst
herhaalbaar tot op de vraag: draait dit script twee keer, dan staat er twee
keer hetzelfde. Vergelijk backend.rag.eval, dat bge-m3 via Ollama nodig heeft
om de vraag te embedden -- daar hoort een modelnaam bij de score, hier niet.

De verwachte paden in data/pad_vragen.csv komen NIET uit een model. Ze zijn
met de hand ingevuld en de kolom `gecontroleerd` staat op 'nee' tot een mens
ze heeft nagekeken. Zolang daar 'nee' staat is de score een indicatie, geen
meting -- hetzelfde voorbehoud als bij de RAG-meting.

DE TWEE FOUTEN ZIJN NIET GELIJK
----------------------------------
    sql -> rag        een vraag die exact te beantwoorden was, krijgt een
                      verhaal. Ziet er goed uit, is niet controleerbaar.
                      Dit is de dure fout.
    rag -> sql        levert een lege of onzinnige tabel. Zichtbaar fout,
                      dus goedkoop.
De verwarringstabel hieronder zet ze apart, zodat een score van 90% niet
verbergt welke tien procent het was.

Gebruik:
    python -m backend.router_eval
    python -m backend.router_eval --toon-goede      # ook de geslaagde regels tonen
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from backend import router as padkeuze

VRAGEN = "data/pad_vragen.csv"


def lees_vragen(pad: str) -> list[dict]:
    with open(pad, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def meet(vragen: list[dict], toon_goede: bool) -> int:
    resultaten = []
    for v in vragen:
        verwacht = v["verwacht_pad"].strip()
        keuze = padkeuze.kies(v["vraag"])
        resultaten.append((v["vraag"], verwacht, keuze, verwacht == keuze.pad))

    goed = sum(1 for *_, ok in resultaten if ok)
    n = len(resultaten)

    print(f"{goed}/{n} vragen naar het verwachte pad ({goed / n * 100:.0f}%)\n")

    # Per pad: hoeveel van de vragen die daar horen komen daar ook uit.
    print(f"{'verwacht pad':<14}{'goed':>6}{'totaal':>8}")
    print("-" * 28)
    for p in padkeuze.PADEN:
        rijen = [r for r in resultaten if r[1] == p]
        if rijen:
            print(f"{p:<14}{sum(1 for r in rijen if r[3]):>6}{len(rijen):>8}")

    # Verwarringstabel: waar gingen ze heen in plaats van waar ze hoorden.
    fouten = [r for r in resultaten if not r[3]]
    if fouten:
        print("\nVERWARRING (verwacht -> gekozen)")
        paren: dict[tuple[str, str], int] = {}
        for _, verwacht, keuze, _ in fouten:
            paren[(verwacht, keuze.pad)] = paren.get((verwacht, keuze.pad), 0) + 1
        for (verwacht, gekozen), aantal in sorted(paren.items()):
            duur = "  <- de dure fout" if verwacht == "sql" else ""
            print(f"  {verwacht:<12} -> {gekozen:<12} {aantal}{duur}")

        print("\nMISSERS")
        for vraag, verwacht, keuze, _ in fouten:
            signaal = f' op "{keuze.signaal}"' if keuze.signaal else ""
            print(f'\n  "{vraag}"')
            print(f"    verwacht: {verwacht}")
            print(f"    gekozen : {keuze.pad}  (regel: {keuze.regel}{signaal})")

    if toon_goede:
        print("\nGOED")
        for vraag, verwacht, keuze, ok in resultaten:
            if ok:
                signaal = f' op "{keuze.signaal}"' if keuze.signaal else ""
                print(f"  {verwacht:<12} {keuze.regel:<12}{signaal:<24} {vraag}")

    return len(fouten)


def main() -> None:
    p = argparse.ArgumentParser(description="Meet de padkeuze uit router.py")
    p.add_argument("--vragen", default=VRAGEN)
    p.add_argument("--toon-goede", action="store_true")
    a = p.parse_args()

    if not Path(a.vragen).exists():
        raise SystemExit(f"{a.vragen} bestaat niet.")
    vragen = lees_vragen(a.vragen)

    ongecontroleerd = sum(1 for v in vragen if v["gecontroleerd"].strip() != "ja")
    if ongecontroleerd:
        print(f"LET OP: {ongecontroleerd} van de {len(vragen)} verwachte paden zijn "
              f"nog niet door een mens nagekeken.\n"
              f"De uitkomst hieronder is een indicatie, geen vastgestelde meting.\n",
              file=sys.stderr)

    fouten = meet(vragen, a.toon_goede)
    raise SystemExit(1 if fouten else 0)


if __name__ == "__main__":
    main()
