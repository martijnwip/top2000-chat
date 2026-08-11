# Top2000 Chat — specificatie v1

*Concept, 11 augustus 2026.*

## 0. Vastgelegde keuze en openstaand punt

**Het model schrijft de SQL.** Dit volgt `docs/ARCHITECTUUR-EN-WAARDEN.md` §3:
het taalmodel vertaalt taal naar één `SELECT`, SQLite rekent. De vaste tools uit
de MCP-server (`zoek_noteringen`, `artiest_overzicht`, `songinfo`) blijven
bestaan als ontwikkelgereedschap en als bron voor geverifieerde testwaarden,
maar zitten niet in het draaipad van de app.

Gevolg voor `data/routering_vragen.csv`: de kolom `verwachte_tool` beschrijft een
route die niet gebouwd wordt. Het bestand blijft bruikbaar om de *vragen* en de
*verwachte antwoorden*, niet om de toolkeuze te toetsen.

**Nog open: de RAG-laag.** `data/rag_index.db` bevat 31.673 chunks en 47.624
bge-m3-vectoren plus een FTS-tabel; `data/rag_vragen.csv` bevat 28 vragen
daarvoor. Vragen als "wat weet je over dit nummer" horen daar te landen, niet
bij een SQL-query. De keuze tussen SQL en RAG hoort in een volgende versie van
dit document.

## 1. Doel en afbakening

Een lokale chatapplicatie die vragen beantwoordt over de NPO Radio 2 Top 2000 (jaargangen 1999 t/m 2025) en over de applicatie zelf.

Bronnen:

- `top2000.db` — SQLite, de enige bron van waarheid voor noteringen
- `data/rag_index.db` — chunks en vectoren voor tekstvragen (v2)
- `/docs` — documentatie over de applicatie zelf

**v1 is backend-only.** De interface is de commandoregel; de HTTP-laag komt erbij zodra de SQL-laag en de antwoordregels staan. De React-front-end volgt in v2.

Buiten scope voor v1: front-end, RAG-route, gebruikersaccounts, meerdere gelijktijdige gesprekken, audio.

## 2. Architectuur

```
CLI  ──>  chat.py  ──>  Ollama (qwen2.5-coder)
             │              │
             │              └─ stap 1: vraag  → SELECT
             │                 stap 2: rijen  → antwoordtekst
             │
             ├──> sql/veiligheid.py   (query keuren)
             └──> sql/uitvoeren.py    (read-only SQLite)

(v2)  React (Vite) ──HTTP/SSE──> FastAPI ──> dezelfde chat.py
```

Twee modelaanroepen per vraag. In stap 1 produceert het model uitsluitend een query. In stap 2 ziet het model alleen de teruggekomen rijen en formuleert daar een zin omheen. **Tussen die twee stappen rekent SQLite; het model rekent nooit zelf.** Een getal dat niet in de rijen staat, mag niet in het antwoord staan.

Alles draait lokaal. Geen uitgaande netwerkcalls.

### Mappenstructuur

```
top2000-chat/
├── backend/
│   ├── cli.py              # v1: commandoregel-interface
│   ├── chat.py             # de twee stappen, interface-onafhankelijk
│   ├── llm.py              # Ollama-client
│   ├── app.py              # v2: FastAPI
│   ├── sql/
│   │   ├── schema_prompt.py  # schemabeschrijving voor het model
│   │   ├── veiligheid.py     # keuring van de gegenereerde query
│   │   └── uitvoeren.py      # read-only verbinding, timeout, LIMIT
│   └── tests/
│       ├── test_veiligheid.py
│       └── test_antwoorden.py
├── data/
├── docs/
├── top2000.db
└── tests/testset-top2000-chat.yaml
```

## 2a. Commandoregel-interface (v1)

Eén ingang: `python -m backend.cli <subcommando>`.

| Commando | Doel |
|---|---|
| `ask "<vraag>"` | Eén vraag, antwoord naar stdout. De hoofdroute. |
| `chat` | Interactieve sessie; `/exit` sluit af, `/sql` toont de laatste query. |
| `sql "<vraag>"` | Alleen stap 1: toont de gegenereerde query en de rijen, zonder antwoordtekst. |
| `run "<SELECT ...>"` | Voert een handgeschreven query uit langs dezelfde keuring. Geen model nodig. |
| `check` | Status van database, Ollama en modelnaam. |
| `test [--case <id>]` | Draait `tests/testset-top2000-chat.yaml` en rapporteert per case. |

Vlaggen op `ask` en `chat`:

- `--show-sql` — toont de query, het aantal rijen en de looptijd
- `--json` — machineleesbare uitvoer: `{"antwoord": ..., "sql": ..., "rijen": [...], "pogingen": n}`
- `--model <naam>` — overschrijft het model uit de config
- `--geen-tekst` — stopt na stap 1; gelijk aan `sql`

`run` en `sql` maken het mogelijk de datalaag te toetsen zonder dat het antwoordmodel meespreekt. `run` heeft Ollama helemaal niet nodig.

Voorbeelden:

```bash
python -m backend.cli check
python -m backend.cli run "SELECT titel FROM songs s JOIN notering n USING(song_id) WHERE n.jaar=2025 AND n.positie=1"
python -m backend.cli sql "Hoe is het De Dijk vergaan?"
python -m backend.cli ask "Wie heeft de meeste noteringen ooit?" --show-sql
python -m backend.cli test --case top1-2025
```

Exitcodes: 0 geslaagd, 1 inhoudelijke fout (case gefaald, lege uitkomst, query afgekeurd), 2 storing (database of Ollama niet bereikbaar).

Uitvoer gaat naar stdout, diagnostiek naar stderr.

## 3. Datalaag

### 3.1 Schema

Twee tabellen dragen alle noteringsvragen. Dit is de beschrijving die letterlijk in de prompt gaat.

```sql
-- 4.925 nummers
songs(
  song_id INTEGER PRIMARY KEY,
  artiest TEXT NOT NULL,        -- ruwe schrijfwijze, niet genormaliseerd
  titel   TEXT NOT NULL,
  release_jaar INTEGER,         -- 91% gevuld; NULL = nog niet opgehaald
  land TEXT,                    -- ISO-2, 91% gevuld
  gender TEXT, artiest_type TEXT, artiest_overleden INTEGER,
  duur_ms INTEGER,              -- 87% gevuld
  mb_recording_id TEXT, mb_artist_id TEXT, mb_artiest_naam TEXT,
  release_bron TEXT, release_titel TEXT, release_type TEXT,
  verdacht TEXT                 -- gevuld = verrijking twijfelachtig
)

-- 54.000 noteringen, 27 jaargangen van precies 2000
notering(
  song_id INTEGER REFERENCES songs(song_id),
  jaar    INTEGER,              -- 1999 t/m 2025
  positie INTEGER,              -- 1 = hoogste, 2000 = laagste
  PRIMARY KEY (jaar, positie),
  UNIQUE (song_id, jaar)
)
```

Aanvullend, voor tekstvragen in v2: `wikipedia_tekst` (10.467 rijen, met `url` en `revisie`), `wikidata_feit` (38.483 rijen), `wikidata_link`.

### 3.2 Vastgestelde eigenaardigheden

Vier punten, alle geverifieerd tegen de database. Ze horen in de prompt, want het model kan ze niet raden.

1. **`song_id` is gelijk aan de positie in 2025.** Voor alle 2000 rijen van jaargang 2025 geldt `positie = song_id`; nummers die in 2025 ontbreken hebben een id boven 2000, tot 4925. Het model mag `song_id` nooit als positie of als rangorde gebruiken — `WHERE song_id <= 10` levert toevallig de top 10 van 2025 en is in elke andere context fout.
2. **Artiestnamen zijn niet genormaliseerd, en dat faalt naar twee kanten.** Dit is het lastigste punt van de hele SQL-route.

   *Te smal.* De Dijk staat in de database als `"Dijk , De DeDijk"` — een parse-artefact uit de bronlijst. `LIKE '%De Dijk%'` matcht die naam **niet** en vindt alleen `"Solomon Burke & De Dijk"`. De vraag "wat is de hoogste notering van De Dijk" levert dan 1505 in plaats van 92. Alleen `LIKE '%Dijk%'` geeft het goede antwoord.

   *Te breed.* `LIKE '%Queen%'` in jaargang 2024 geeft 39 noteringen: 32 van Queen, 4 van Queens of the Stone Age, 1 van Queensrÿche, plus twee samenwerkingen. `data/routering_vragen.csv` noemt 34 als gouden antwoord; het juiste getal voor "nummers van Queen" is 32.

   Zolang er geen genormaliseerde kolom is, moet de prompt beide gevallen tonen en moet het antwoord noemen welke schrijfwijzen zijn meegeteld. **Aanbeveling:** een `artiest_norm`-kolom of een aliastabel in de laadpijplijn, zodat het model op een schone naam kan matchen. 33 van de 2143 unieke artiestnamen bevatten een komma; de meeste daarvan zijn legitiem (`Earth, Wind & Fire`), een handvol is stuk.
3. **Ontbrekende verrijking is geen ontbrekend feit.** `release_jaar IS NULL` betekent "nog niet opgehaald" (9% van de nummers), niet "onbekend". Aggregaties over `release_jaar`, `land` of `duur_ms` moeten de dekking melden, anders is het gemiddelde misleidend.
4. **`duur_ms` staat in milliseconden.** Africa van Toto is 296906, oftewel 4:56. De omrekening hoort in de antwoordlaag, niet in het hoofd van het model.

5. **Er zijn geen indexen op `songs.artiest` of `songs.titel`.** Een `LIKE` over 4.925 rijen is snel genoeg; een `LIKE` over `notering` gejoind zonder filter op `jaar` niet. Dat is de reden voor de timeout in 3.4.

### 3.2b Verouderde waarden in `data/routering_vragen.csv`

Dat bestand markeert drie antwoorden als "NOG NIET BETROUWBAAR: verrijking 1% compleet". De verrijking staat inmiddels op 87–91%. De gemeten waarden van 11 augustus 2026:

| Vraag | In de CSV | Gemeten |
|---|---|---|
| Gemiddeld releasejaar in 2025 | 1984,8 | 1991,7 (over 1849 van de 2000) |
| Nederlandse artiesten in 2025 | 3 | 329 |
| Nummers van Queen in 2024 | 34 | 32 (39 met `LIKE '%Queen%'`) |
| Duur van Roller Coaster | 4:29 | 4:29 — klopt |
| Releasejaar van Africa | 1982 | 1982 — klopt |

De eerste drie regels horen bijgewerkt te worden.

### 3.3 Keuring van de gegenereerde query

`sql/veiligheid.py` keurt elke query voordat die de database raakt. Afkeuring geeft exitcode 1 en een leesbare melding; er volgt geen antwoord uit modelkennis.

Toegestaan:

- Precies één statement, beginnend met `SELECT` of `WITH`
- Alleen de tabellen uit 3.1
- Maximaal één trailing puntkomma

Geweigerd:

- `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `REPLACE`, `PRAGMA`, `ATTACH`, `DETACH`, `VACUUM`
- Meerdere statements (puntkomma gevolgd door tekst)
- Commentaartekens `--` en `/* */` (verbergen makkelijk een tweede statement)
- Verwijzingen naar `sqlite_master` of andere `sqlite_`-tabellen

De verbinding is daarnaast alleen-lezen (`file:top2000.db?mode=ro`, `uri=True`), zodat de keuring niet het enige slot is.

### 3.4 Uitvoeren

- Ontbreekt een `LIMIT`, dan wordt `LIMIT 200` toegevoegd
- Timeout van 5 seconden via `set_progress_handler`; daarna afbreken met een leesbare melding
- `row_factory = sqlite3.Row`, resultaat als lijst van dicts
- Query en looptijd worden gelogd bij `--show-sql`

## 4. Modellaag

### Stap 1 — vraag naar SQL

- Model: `qwen2.5-coder` via Ollama, `temperature` 0
- De prompt bevat: het schema uit 3.1, de vier eigenaardigheden uit 3.2, de keuringsregels uit 3.3, en vijf voorbeelden vraag→query
- Het model geeft uitsluitend de query terug, zonder uitleg en zonder codeblok-tekens; de parser strookt beide alsnog weg
- Faalt de keuring of geeft SQLite een fout, dan gaat de foutmelding terug naar het model. **Maximaal twee herkansingen**, daarna een melding dat de vraag niet in een query is om te zetten
- Levert de query nul rijen, dan volgt geen herkansing — leeg is een geldig antwoord

De vijf voorbeelden in de prompt dekken de gevallen waar een 7B- of 14B-model het vaakst op stukloopt: een join tussen `songs` en `notering`, een `LIKE` op artiest, een aggregatie per jaar, een `GROUP BY` met `COUNT`, en een vraag over een jaar buiten 1999–2025.

### Stap 2 — rijen naar antwoord

- Zelfde model, `temperature` 0.2
- Invoer: de oorspronkelijke vraag, de rijen (maximaal 50, daarboven een samenvatting plus het totaal), en de antwoordregels uit sectie 5
- Geen schema en geen query in deze prompt — het model hoeft alleen te formuleren

### Modelkeuze meten

`ARCHITECTUUR-EN-WAARDEN.md` §3 noemt het kleinste werkbare model als leidende knop. `cli test` rapporteert daarom altijd de modelnaam, het aantal geslaagde cases en de gemiddelde looptijd per vraag. Een uitslag zonder modelnaam is geen meting. De testset draait tegen het productiemodel via Ollama, nooit tegen een extern model.

## 5. Antwoordregels

Deze regels horen in de prompt van stap 2 én in de testset.

**Herkomst**

- Elk cijfer in het antwoord komt uit de teruggekomen rijen. Geen enkel getal uit modelkennis, ook niet als het klopt.
- Levert de query nul rijen, dan luidt het antwoord dat het niet in de gegevens staat.
- Wordt de query afgekeurd of loopt hij vast, dan meldt het antwoord dat; er volgt geen omweg via modelkennis.
- Vragen buiten de Top 2000 en buiten de applicatie krijgen een korte weigering plus een verwijzing naar wat er wél beschikbaar is.

**Volledigheid**

- Zijn er meer rijen dan getoond, dan noemt het antwoord het totaal en meldt het dat een selectie wordt getoond.
- Bij meerdere schrijfwijzen van een artiest noemt het antwoord welke zijn meegeteld.
- Bij een aggregatie over een verrijkt veld wordt de dekking genoemd: "gebaseerd op de 91% van de nummers waarvan het releasejaar is opgehaald".
- `NULL` in een verrijkt veld heet "nog niet opgehaald", niet "onbekend".

**Vorm**

- Antwoord in de taal van de vraag; standaard Nederlands.
- Eerst het directe antwoord, daarna pas de onderbouwing.
- Meer dan drie rijen: een uitgelijnde tekstkolom, geen Markdown-pipes.
- Geen `song_id`, geen SQL en geen ruwe JSON in de tekst; die verschijnen alleen bij `--show-sql` of `--json`.
- Derde persoon, geen "ik" of "wij".

**Grenzen**

- Geen speculatie over oorzaken van stijgingen of dalingen.
- Geen voorspellingen over toekomstige jaargangen.

## 6. Privacy

Vragen en antwoorden blijven op de machine. Geen telemetrie, geen externe API-calls. Gespreksgeschiedenis leeft binnen de CLI-sessie; schrijven naar schijf gebeurt alleen na een expliciete exportactie.

## 7. Definitie van gereed voor v1

- `python -m backend.cli test` slaagt op alle cases in `tests/testset-top2000-chat.yaml`, met de modelnaam in de uitslag
- `run` werkt zonder dat Ollama draait
- Geen enkele query buiten de toegestane vorm komt langs de keuring; `test_veiligheid.py` bewijst dat met afgekeurde voorbeelden
- `--show-sql` toont bij elk antwoord met cijfers de query die het opleverde
- `check` geeft een bruikbare foutmelding bij een ontbrekende database of een niet-draaiende Ollama
- De backend draait zonder netwerkverbinding

## 8. Bouwvolgorde

1. `sql/veiligheid.py` en `sql/uitvoeren.py`, plus `test_veiligheid.py` — te toetsen met `cli run`, nog zonder model
2. `cli.py` met `check` en `run`
3. `sql/schema_prompt.py` en stap 1, plus `cli sql` — hier blijkt of het model bruikbare query's schrijft
4. Stap 2 en `cli ask` / `cli chat`
5. `cli test` als loper over de testset
6. Pas daarna de RAG-route, `app.py` en de front-end
