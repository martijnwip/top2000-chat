"""Padkeuze: welk pad neemt een vraag, voordat er ook maar iets wordt opgehaald.

Drie uitkomsten:
    sql          tel-, som- en sorteervragen over de lijst   -> backend.chat
    rag_songs    achtergrond en betekenis van nummers        -> corpus 'songs'
    rag_project  vragen over deze toepassing zelf            -> corpus 'project'

Overgezet uit path.py (top2000.ai), ongewijzigd in regels en volgorde. De
meetloper staat apart in backend/router_eval.py, tegen data/pad_vragen.csv.

WAAROM REGELS EN GEEN MODEL
---------------------------
Een classificatie door een model is zelf een meetprobleem: hij is niet
deterministisch, dus een wijziging in de regels is niet te onderscheiden van
toeval in de sampling. Deze module doet nul inferentie. Dezelfde vraag geeft
altijd hetzelfde pad, de keuze is met de hand na te rekenen, en
router_eval.py draait zonder dat Ollama aan staat.

De prijs staat er eerlijk bij: formuleringen die buiten de patronen vallen
belanden in de terugval. Dat is een meetbaar tekort, geen verborgen fout --
router_eval.py laat per misser zien welk signaal wel of niet aansloeg.

WAAROM SQL DE TERUGVAL IS
--------------------------
CLAUDE.md: bouw geen RAG-antwoord op iets dat een SELECT exact kan
beantwoorden. Bij twijfel is het exacte pad daarom het veiligste. Een vraag die
onterecht naar SQL gaat levert een lege of rare tabel -- zichtbaar fout. Een
vraag die onterecht naar RAG gaat levert een vloeiend antwoord dat er goed
uitziet en het niet is. Van die twee fouten is de eerste te verkiezen.

VOLGORDE VAN DE REGELS
-----------------------
Van specifiek naar algemeen, eerste treffer wint:

  1. project       Woorden over de toepassing zelf komen in geen enkele
                   songvraag voor, dus dit mag voorop.
  2. omschrijving  "gaat over", "betekenis": SQL kan hier niet op filteren,
                   ook niet als er verder een jaartal in de vraag staat.
                   Daarom wint dit van een SQL-signaal, niet andersom --
                   "welk nummer uit 1975 gaat over oorlog" is geen SELECT.
  3. sql-signaal   Jaartallen, teltaal, posities.
  4. terugval      sql.

WAT HIER (NOG) NIET IN ZIT
----------------------------
De RAG-index bevat een vierde corpus, 'artiesten' (5.555 chunks). Vragen als
"wie is Queen" horen daarheen, maar dat pad staat bewust nog niet in deze
module: het is niet gebouwd en niet gemeten. Liever een ontbrekend pad dan
een pad dat er wel is en niemand heeft nagekeken.

Gebruik:
    python -m backend.router "Wat is de hoogste notering van Abba?"
    python -m backend.router --toon-regels
"""
from __future__ import annotations

import re
import sys
from collections import namedtuple

# pad    : waar de vraag heen gaat
# regel  : welke regel besliste -- nodig om een misser te kunnen verklaren
# signaal: de letterlijke tekst die aansloeg
Keuze = namedtuple("Keuze", "pad regel signaal")

PADEN = ("sql", "rag_songs", "rag_project")

# ---------------------------------------------------------------------------
# 1. PROJECT: gaat de vraag over de toepassing in plaats van over de muziek?
# ---------------------------------------------------------------------------
# Deze woorden komen in een vraag over een nummer niet voor. Dat maakt ze veilig
# om vooraan te zetten: een fout-positief is hier onwaarschijnlijk, en de winst
# is dat "moet ik me registreren" nooit in het songcorpus gaat vissen.
PROJECT = [
    ("toegang",
     r"\b(registr\w*|aanmeld\w*|inlogg?\w*|log ?in|account\w*|wachtwoord\w*|"
     r"abonnement\w*|proefperiode)\b"),
    ("toepassing",
     r"\b(deze (app|applicatie|toepassing|demo|website|chat|tool)|"
     r"dit (project|programma|systeem|prototype))\b"),
    ("techniek",
     r"\b(ollama|qwen\w*|bge-?m3|sqlite|fastapi|welk model|welke modellen|"
     r"open ?source|licentie|broncode|api-?sleutel)\b"),
    ("waarden",
     r"\b(privacy|tracking|getrackt|getracked|surveillance|dataveiligheid|"
     r"duurzaam\w*|energieverbruik|stroomverbruik|hosting|gehost|"
     r"soevereinit\w*)\b"),
    # Een bezittelijk voornaamwoord over de invoer van de gebruiker zelf is een
    # sterk teken: over een nummer vraag je niet wat er met "mijn gegevens"
    # gebeurt. Toegevoegd na een misser op "worden mijn vragen getrackt?".
    ("gebruiker",
     r"\bmijn (vraag|vragen|gegevens|data|invoer|zoekopdracht\w*)\b"),
]

# ---------------------------------------------------------------------------
# 2. OMSCHRIJVING: de vraag beschrijft een onderwerp in plaats van een feit
# ---------------------------------------------------------------------------
# Dit is het bestaansrecht van de RAG-laag. SQL heeft geen kolom 'waar gaat dit
# nummer over', dus zodra een van deze wendingen valt is er geen exact pad meer
# -- ook niet als er een jaartal in dezelfde zin staat.
OMSCHRIJVING = [
    ("onderwerp",
     r"\b(gaat over|gaan over|ging over|waarover|waar gaat|waar gaan|"
     r"handelt over|handelen over)\b"),
    # "nummers over de Vietnamoorlog" heeft geen werkwoord: het voorzetsel doet
    # al het werk. Zonder deze regel won het jaartal in dezelfde zin, en ging
    # een vraag die SQL niet kan beantwoorden alsnog naar SQL.
    ("onderwerp_kaal", r"\b(nummers?|liedjes?|songs?|platen?) over\b"),
    ("betekenis",
     r"\b(betekenis|betekent|achtergrond|verhaal achter|ge[iï]nspireerd|"
     r"inspiratie|thema|boodschap|symbol\w*)\b"),
    # "zijn een protest tegen X" beschrijft net als 'gaat over' een onderwerp,
    # maar zonder een van de onderwerp/betekenis-woorden hierboven. Toegevoegd
    # na een misser op "Welke nummers zijn een protest tegen de oorlog in
    # Vietnam?" -- viel terug op sql, want geen enkel ander signaal sloeg aan.
    ("duiding",
     r"\b(protest\w*|verzet tegen|kritiek op|eerbetoon aan|ode aan|"
     r"hommage aan)\b"),
    ("ontstaan",
     r"\b(waarom schreef|waarom maakte|geschreven over|geschreven naar "
     r"aanleiding|ontstaan van|hoe kwam .{0,20}\btot stand)\b"),
]

# ---------------------------------------------------------------------------
# 3. SQL-SIGNAAL: er wordt geteld, gesorteerd of op een jaargang gefilterd
# ---------------------------------------------------------------------------
# Deze staan er niet om SQL te kiezen -- dat is toch al de terugval -- maar om
# in de uitvoer te kunnen laten zien wáárom. Een keuze zonder reden is bij het
# nakijken van een misser niets waard.
SQL = [
    ("jaartal", r"\b(19|20)\d{2}\b"),
    ("telwoord",
     r"\b(hoe vaak|hoeveel|aantal|meeste|minste|vaakst\w*|hoogste|laagste|"
     r"langste|kortste|eerste|laatste|gemiddeld\w*)\b"),
    ("ranglijst",
     r"\b(positie\w*|notering\w*|plek|plaats|top ?\d+|nummer ?1|"
     r"steeg|stegen|daalde|daalden|gestegen|gedaald|binnenkwam)\b"),
]

REGELS = [("rag_project", PROJECT), ("rag_songs", OMSCHRIJVING), ("sql", SQL)]

# Vooraf compileren: kies() wordt per vraag aangeroepen en in router_eval.py
# een paar honderd keer achter elkaar.
_GECOMPILEERD = [
    (pad, naam, re.compile(patroon, re.IGNORECASE))
    for pad, groep in REGELS for naam, patroon in groep
]


def kies(vraag: str) -> Keuze:
    """Bepaal het pad en geef erbij welke regel besliste.

    De regelnaam en het aangeslagen stukje tekst gaan mee terug, niet omdat de
    aanroeper ze nodig heeft om te routeren, maar omdat je zonder die twee een
    verkeerde keuze niet kunt uitleggen. Vergelijk de deelscores in
    backend.rag.zoek.zoek(): dezelfde reden.
    """
    for pad, naam, patroon in _GECOMPILEERD:
        treffer = patroon.search(vraag)
        if treffer:
            return Keuze(pad, naam, treffer.group(0))
    return Keuze("sql", "terugval", "")


def bepaal_pad(vraag: str) -> str:
    """Alleen het pad, voor aanroepers die de verklaring niet gebruiken."""
    return kies(vraag).pad


def toon_regels() -> None:
    for pad, groep in REGELS:
        print(f"\n{pad}")
        for naam, patroon in groep:
            print(f"  {naam:<14} {patroon}")


def main() -> None:
    if len(sys.argv) < 2:
        print('Gebruik: python -m backend.router "je vraag hier"')
        print('         python -m backend.router --toon-regels')
        raise SystemExit(1)
    if sys.argv[1] == "--toon-regels":
        toon_regels()
        return
    k = kies(sys.argv[1])
    signaal = f' op "{k.signaal}"' if k.signaal else ""
    print(f"{k.pad}   (regel: {k.regel}{signaal})")


if __name__ == "__main__":
    main()
