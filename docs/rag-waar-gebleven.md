# RAG — waar we gebleven zijn

*Stand op 19 augustus 2026 (bijgewerkt na de samenvoeging van de werklijst;
oorspronkelijk 13 augustus 2026). Geparkeerd, niet vastgelopen.*

## Klaar

- Text-to-SQL werkt (commit `026859e`).
- `backend/rag/` staat: `index.py`, `zoek.py`, `eval.py`, met bouwen en zoeken
  gescheiden. Gecommit (`e395e06`, `4c10d34`).
- De meetlat is verbreed: `data/rag_vragen_werklijst.csv` is ingevuld (38 van
  de 50 kandidaten bruikbaar bevonden) en samengevoegd met
  `data/rag_vragen.csv`. Van 12 naar 50 omschrijvingsvragen.
- Meting 1 is herhaald op die grotere set. Uitkomst wijkt af van de eerste,
  kleine meting — zie hieronder en `rag-chunkstrategie-en-meting.md` §5.
- De drie kleine taken uit de vorige versie van dit document (§2, hieronder
  ingekort bewaard) zijn gedaan.
- `backend/rag/herchunk.py` staat: knipt bestaande 'verhaal'-chunks van
  sectie (2.000-2.500 tekens) naar zinsvenster (doel 500, max 800, min 200).
  Getest op het songs-corpus: 21.193 -> 45.504 vensters, gemiddeld 497
  tekens, nul boven de 800-grens. Onderweg drie eigen bugs gevonden en
  gefixt (o.a. tracklists zonder punten/komma's die de 800-grens
  doorbraken). Nog niet ingeladen in de index — dat is de volgende stap.

## De stand van zaken in één alinea

Vragen mét een titel of artiestnaam werken (100%). Vragen waarin je een nummer
omschrijft zonder namen te noemen, werken slecht: op de nu 50 vragen grote
set haalt kale vector-search 32% recall@5, en dat is de beste van alle
geteste instellingen — beter dan elke geteste hybride fusie, inclusief de
w_lexicaal=0,50 die nu als standaard in `antwoord.py` staat (24%). Dat is
een omkering ten opzichte van de eerste meting op 12 vragen, waar 0,50 juist
won. Zie de nieuwe tabel in `rag-chunkstrategie-en-meting.md` §5.

De onderliggende oorzaak staat nog steeds: de juiste tekst staat wél in het
corpus, maar in chunks van 2.000 à 2.500 tekens waarin die ene rake zin
wegvalt tegen alinea's over opnamen en hitnoteringen. Zie
`rag-chunkstrategie-en-meting.md` §1.

## Beslissing over `W_LEXICAAL` in `antwoord.py`: laten staan

De 0,50 die daar als standaard staat, was gekozen op basis van de meting op
12 vragen. Die meting is met de herhaling op 50 vragen achterhaald: op de
grotere set wint vector-only (32% tegen 24%). Gekozen (19 augustus): **niet nu
aanpassen, wachten tot na het herchunken (meting 2)** en dan in één keer de
uiteindelijke instelling kiezen — liever één wijziging op basis van de
volledige meting dan twee. `W_LEXICAAL` blijft dus voorlopig op 0,50 staan,
wetende dat dat cijfer niet meer onderbouwd is; de docstring in `antwoord.py`
noemt dat expliciet.

## "Welke nummers gaan over X"-vragen: routing gefixt (20 augustus), lijst-volledigheid nog niet

Getest (19 augustus) met "Welke nummers zijn een protest tegen de oorlog in
Vietnam?" — een vraag die om een lijst van meerdere nummers vraagt, niet om
het ene nummer dat een omschrijving dekt. Twee losse gaten kwamen boven:

1. **De router stuurde 'm niet naar RAG — gefixt.** `router.py` herkende
   "zijn een protest tegen X" niet als omschrijving-signaal (wel al "gaat
   over X", die stond al in `data/pad_vragen.csv`), dus hij viel terug op
   sql. Nieuw signaal `duiding` toegevoegd (`protest\w*|verzet tegen|
   kritiek op|eerbetoon aan|ode aan|hommage aan`) — vangt de constructie
   "nummer is een [type] tegen/aan/op X" in het algemeen, niet alleen
   Vietnam. `router_eval.py`: 31/31, geen regressie op de bestaande 30.
   Getest via `backend.cli ask` (dezelfde functie die de frontend aanroept):
   komt nu terecht bij `rag_songs` en geeft een antwoord.
2. **De lijst is nog steeds niet compleet — niet gefixt, blijft open.**
   De zoeklaag vindt de juiste kandidaten (*Eve of Destruction*, *Goodnight
   Saigon*, *Street Fighting Man*, *We Gotta Get out of This Place*), maar
   het lokale generatiemodel (qwen2.5:7b-instruct) noemt er in het antwoord
   nog steeds niet alle vier en mist bij een test op 20 augustus opnieuw
   *Goodnight Saigon*. Dit is een ander soort vraag dan waar `rag_vragen.csv`
   op meet (steeds: "welk ENE nummer wordt hier omschreven") en dat is nooit
   apart gemeten. Met andere woorden: de vraag komt nu ergens terecht en
   levert een antwoord op, maar er is geen garantie dat dat antwoord
   compleet is.

## Herchunken is gedaan — en het hielp niet

**Stap 5/9 is uitgevoerd (19 augustus, ~2u 6min met `caffeinate -i`).**
`backend/rag/herchunk.py` knipt nu, `data/rag_index_zinsvenster.db` (310 MB)
bevat de volledige herbouwde songs-index, 50.429 chunks, versie
`zinsvenster-500-25`. Dit staat los van `data/rag_index.db` — de site draait
onaangetast door op de oude index.

**Uitkomst (meting 2, `rag-chunkstrategie-en-meting.md` §5): vector-only
recall@5 voor omschrijvingsvragen bleef exact 32%, hetzelfde als op de oude
index.** Top-1 en de gemiddelde rang verbeterden licht, maar het getal
waarvoor dit hele traject bedoeld was — hoe vaak het juiste nummer in de
top-5 staat — veranderde niet. Chunkgrootte was dus kennelijk niet de
bottleneck; `bge-m3` haalde de rake zin ook uit de oude, langere chunks al
overwegend goed op.

**Beslissing (19 augustus): optie 2 — oude index laten staan, dit hoofdstuk
afsluiten.** Overwogen zijn ook: (1) alsnog overstappen op de nieuwe index
voor de marginale top-1/gem.-rang-winst, verworpen omdat dat een tweede
RAG-bestand erbij betekent voor een wijziging die op recall@5 — het cijfer
waar dit om ging — niets oplevert; (2) meteen verder zoeken naar de echte
bottleneck, uitgesteld: 32% zit ver onder de 60%-drempel uit §5, dus er valt
nog wel iets te verbeteren, maar dat is open-eindig onderzoek en geen
vervolgstap op deze meting. `data/rag_index_zinsvenster.db` en
`backend/rag/herchunk.py` blijven staan als bewaard bewijs (en herbruikbaar
als een grotere eval-set chunkgrootte later alsnog interessant maakt) — niet
opgeruimd, niet in gebruik.

Wie dit oppakt: begin niet met een nieuwe lange draai, maar met een paar
missers met de hand bekijken (zoals bij het Vietnam-voorbeeld) om te zien of
het aan `bge-m3` zelf ligt, aan de kloof tussen vraagformulering en
artikeltekst, of aan iets anders.

Dit raakt `W_LEXICAAL` in `antwoord.py` niet meer — die beslissing (boven)
was al "wachten tot na het herchunken", en nu is dat gebeurd zonder dat de
onderliggende situatie veranderde. Vector-only wint nog steeds.

### Klein werk voor Claude Code, gedaan op 19 augustus

- Kolom `heeft_corpus_tekst` toegevoegd aan `data/rag_vragen.csv`.
  `eval.py` rapporteert sindsdien twee tabellen: over alle vragen, en over
  alleen de meetbare.
- De dode variant "geen fusie bij lege BM25" uit `VARIANTEN_METING1` in
  `eval.py` gehaald (kon nooit aanslaan, gemeten effect nul). De
  onderliggende `min_lex_kandidaten`-optie in `zoek.py` blijft staan.
- Gecontroleerd of hybride bij `w_lexicaal = 0,25` gelijk is aan vector-only:
  op de kleine set (20 vragen) wél, op de grote set (58 vragen) niet meer —
  zie de omkering hierboven.
- Werklijst samengevoegd met `rag_vragen.csv`, meting 1 herhaald als
  nulmeting op de grotere set.

## Eén ding om niet te vergeten

- **Opruimen van oude vectoren gebeurt ná het herchunken**, en pas als de
  nieuwe chunkstrategie de betere blijkt. Zolang de oude vectoren er staan,
  is een stap terug gratis.
