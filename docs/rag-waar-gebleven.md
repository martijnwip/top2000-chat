# RAG — waar we gebleven zijn

*Stand op 13 augustus 2026. Geparkeerd, niet vastgelopen.*

## Klaar

- Text-to-SQL werkt (commit `026859e`).
- `backend/rag/` staat: `index.py`, `zoek.py`, `eval.py`, met bouwen en zoeken
  gescheiden. Gecommit (`e395e06`, `4c10d34`).
- Meting 1 is gedraaid op de bestaande index. Uitkomst: het gewicht van de
  lexicale helft verlagen brengt omschrijvingen van 8% naar 17% recall@5,
  zonder dat naam-vragen (100%) eronder lijden.
- De drie kleine taken hieronder (§2) zijn gedaan, zie de uitkomsten daar.

## De stand van zaken in één alinea

Vragen mét een titel of artiestnaam werken (100%). Vragen waarin je een nummer
omschrijft zonder namen te noemen, werken niet (17%). Dat tweede is waar de
RAG-laag voor bestaat — alles met een naam erin kan het SQL-pad al. De oorzaak
is gemeten: de juiste tekst staat wél in het corpus, maar in chunks van 2.000 à
2.500 tekens waarin die ene rake zin wegvalt tegen alinea's over opnamen en
hitnoteringen. Zie `rag-chunkstrategie-en-meting.md` §1.

## De volgende stap, en waarom die eerst komt

**Niet meteen herchunken.** De omschrijvingsset telt twaalf vragen; één vraag
die omslaat is acht procentpunt. Op zo'n set is niet te zien of het herchunken
werkt. Daarom eerst de meetlat verbreden.

### 1. Handwerk (ongeveer een uur, alleen door een mens te doen)

Vul `data/rag_vragen_werklijst.csv` in: dertig van de vijftig regels krijgen een
omschrijving in de kolom `omschrijving`. De rest krijgt `bruikbaar = nee`.

Vier regels:

- geen titel en geen artiestnaam in de omschrijving
- uit je eigen hoofd, niet overgeschreven uit het artikel
- één onderwerp per vraag
- geformuleerd zoals je het een vriend zou vragen

IJkpunten uit de bestaande set:

> lied over een bokser die onterecht werd veroordeeld
> nummer waarin de dood van een popmuzikant het einde van een tijdperk markeert

De kolom `secties_in_artikel` laat zien of het artikel over de betekenis gaat.
Staat daar alleen "Chart performance" en "Covers", dan is dat nummer geen goede
kandidaat.

### 2. Klein werk voor Claude Code (kan onafhankelijk van het handwerk) — gedaan

- Kolom `heeft_corpus_tekst` toegevoegd aan `data/rag_vragen.csv`: `nee` voor
  song 118 en 560, `ja` voor de rest (`nvt` voor de `afwezig`/`sql`-vragen,
  net als `heeft_nl_tekst`). `eval.py` rapporteert nu twee tabellen: over alle
  vragen, en over alleen de meetbare (18 van de 20).
- De variant "geen fusie bij lege BM25" uit `VARIANTEN_METING1` in `eval.py`
  gehaald. Kon niet aanslaan: `fts_escape` maakt van elke vraag een OR-reeks,
  dus BM25 levert altijd kandidaten. Gemeten in meting 1, effect nul. De
  onderliggende `min_lex_kandidaten`-optie in `zoek.py` blijft staan — dat is
  algemene functionaliteit (§3a), niet deze ene dode testvariant.
- Gecontroleerd of de hybride top-5 bij `w_lexicaal = 0,25` gelijk is aan de
  vector top-5: per-vraag vergeleken over alle 20 vragen, 7 hebben een andere
  top-5-samenstelling, maar in geen van die zeven verandert dat of het
  verwachte nummer wél of niet in de top-5 staat. De winst van meting 1 bij
  0,25 is dus niet meer dan "BM25 buiten de deur houden bij omschrijvingen" —
  vastgelegd in `rag-chunkstrategie-en-meting.md` §5.

### 3. Daarna

Werklijst samenvoegen met `rag_vragen.csv` — dan ruim veertig
omschrijvingsvragen. Meting 1 opnieuw draaien als nulmeting op die grotere set.
Pas dán stap 5: herchunken naar zinsvensters en opnieuw embedden. Dat is de
enige lange draai; zie `rag-chunkstrategie-en-meting.md` §2 en §7.

## Eén ding om niet te vergeten

- **Opruimen van oude vectoren gebeurt ná stap 5**, en pas als de nieuwe
  chunkstrategie de betere blijkt. Zolang de oude vectoren er staan, is een stap
  terug gratis.
