# Top2000.ai — Architectuur & Waarden

*Werkdocument. Doel: vastleggen wat we bouwen, met welke infrastructuur, en —
eerlijk — hoe dicht dat bij het manifest van empathy.ai komt. De leidende
gedachte is niet zuiverheid maar transparantie: laten zien waar het wél en
niet lukt, en waarom.*

## 1. Doel

Een gratis, publiek toegankelijke demo-app waarmee je in natuurlijke taal
vragen kunt stellen over de NPO Radio 2 Top 2000 (1999–2025). De Top2000 is
het voertuig; het eigenlijke doel is een **demonstrator van waarden-gedreven
AI-infrastructuur**: privacy-respecterend, zo onafhankelijk mogelijk van Big
Tech, en zo milieuvriendelijk als haalbaar — met de keuzes en afwegingen
zichtbaar in plaats van verstopt achter een claim.

## 2. Wat er nu staat

- **Databron:** de samengevoegde Wikipedia-lijst van alle jaargangen,
  geparset naar een schone dataset (54.000 noteringen, ~4.925 unieke nummers,
  27 jaargangen). Validatie: elke jaargang telt precies 2000 noteringen.
- **Database:** SQLite, twee tabellen (`songs`, `notering`) met een stabiele
  `song_id` die genormaliseerde verrijking later mogelijk maakt.
- **Pijplijn:** `parse_wikipedia.py` (bron → CSV) en `load.py` (CSV → database),
  volledig reproduceerbaar uit de scripts.
- **Vraag-laag:** `ask.py` en `chat.py` — een lokaal taalmodel vertaalt de vraag
  naar SQL, een read-only SQLite-verbinding voert die uit. Model in overgang van
  `gemma4` naar `qwen2.5-coder:32b`, lokaal via Ollama.

## 3. Architectuurprincipes

**Het model vertaalt, de database rekent.** Het taalmodel zet alleen taal om in
SQL. Alle tellingen, sommen en sorteringen doet SQLite deterministisch. Zo
krijg je exacte antwoorden in plaats van een gokkend model — en dit is meteen
een efficiëntieprincipe: het model produceert korte uitvoer (een query), wat
weinig energie kost.

**Read-only en afgeschermd.** De database wordt alleen-lezen geopend en alleen
enkelvoudige `SELECT`-query's worden toegelaten. Dit is de basisbeveiliging die
nodig is zodra de app publiek staat.

**Reproduceerbaar en minimaal.** Geen serverdatabase, geen zware frameworks: één
SQLite-bestand en een handvol scripts. Minimalisme is hier ook een
duurzaamheidskeuze — minder draaiende onderdelen, minder verbruik.

**Kleinst werkbare model.** De centrale knop die privacy, onafhankelijkheid én
duurzaamheid tegelijk dient: gebruik het kleinste model dat de vragen nog goed
beantwoordt. Kleiner model = minder energie per vraag = goedkopere, groenere
hardware, terwijl het volledig zelf gehost blijft. Dit maakt een eval-set (een
vaste set vragen met geverifieerde antwoorden) belangrijk: die bewijst wat de
kleinste werkbare opstelling is.

## 4. Beoogde stack voor de publieke demo

- **Model:** open-weight, zelf gehost (Qwen2.5-Coder nu; Codestral 2 onder
  Apache 2.0 als waarden-alternatief in onderzoek).
- **Runtime:** Ollama lokaal; te wisselen naar MLX (Apple Silicon) of een VPS.
  Voorgenomen: `ask.py` naar de OpenAI-compatibele API zodat runtime én host
  één configregel worden.
- **Database:** SQLite (read-only in productie).
- **Backend:** FastAPI (hergebruikt de bestaande Python-logica).
- **Frontend:** één eenvoudige pagina met invoerveld en resultaattabel.
- **Hosting:** groene EU-optie. Infomaniak (Zwitsers, 100% hernieuwbaar,
  dataveiligheid) of Hetzner (Duits, 100% groen, goedkoper). Alternatief voor de
  demo: draaien op eigen M1 achter een tunnel — maximale soevereiniteit en
  hergebruik van bestaande hardware.

## 5. Eerlijke score op het manifest

| Pijler (empathy.ai) | Status | Toelichting |
|---|---|---|
| Data blijft van jou, lokaal verwerkt | Grotendeels | De data (Top2000) is openbaar en staat lokaal; queries verlaten de server niet. Er is geen persoonlijke data in het spel, dus dit is makkelijker dan voor de meeste apps. |
| Getraind op data die je bezit | Nee | Het model (Qwen/Codestral) is getraind door een groot techlab, niet door ons. Dit is eerlijk gezien niet haalbaar; we hergebruiken open gewichten. |
| Onafhankelijk van Big Tech | Deels | Geen afhankelijkheid van betaalde API's tijdens gebruik; alles draait op eigen/gehoste infra. Maar de modellen (Alibaba/Mistral) en hardware (Apple/NVIDIA) komen wél van grote spelers. Onafhankelijkheid is een spectrum, geen schakelaar. |
| Draait op hernieuwbare energie | Doel, deels | Haalbaar via een groene EU-host (Infomaniak/Hetzner). Op eigen hardware afhankelijk van de thuisstroom. Wordt pas "waar" na een expliciete hostingkeuze. |
| Duurzaamheid wordt gemeten | Voorgenomen | Plan: per vraag tonen welk model draaide, wáár, en een schatting van het verbruik. Dit maakt de claim controleerbaar in plaats van marketing. |
| Geen surveillance / tracking | Ja (ontwerp) | Geen tracking, geen doorverkoop; enkel de query wordt lokaal verwerkt. Vast te leggen zodra de publieke frontend er is. |
| AI als gereedschap, niet als companion | Ja | De app is puur een vraag-naar-antwoord-hulpmiddel over feiten; geen imitatie van menselijke empathie. |
| Gebouwd zonder Big Tech-modellen | Nee | Bij het bouwen van de pijplijn, corpora en scripts is Claude (Anthropic) gebruikt. Dat raakt het draaipad niet — daar komt geen externe API aan te pas — maar het weglaten zou de tabel oneerlijk maken. Zie §6. |

## 6. Belangrijkste spanningen

De pijlers maximaliseren niet samen. Een groot model zelf hosten voor een
publieke app is tegelijk het minst groene en het duurste deel — een gedeelde
gehoste API kan per vraag zuiniger zijn door hogere benutting, maar dat
ondermijnt de onafhankelijkheid. De eerlijke uitweg voor een demo is niet
kiezen-en-verbergen, maar de keuze labelen en meten. De "kleinst werkbare
model"-knop is de enige die alle drie de pijlers tegelijk vooruithelpt.

Een tweede spanning zit in het bouwproces zelf. De pijplijn wordt ontwikkeld met
hulp van een groot extern model, terwijl de app draait op een klein lokaal model.
Dat is verdedigbaar — het draaipad blijft schoon, en gereedschap is iets anders
dan infrastructuur — maar het brengt een meetfout met zich mee die je niet ziet
als je er niet op let: retrieval die "werkt" omdat een capabel model middelmatige
context nog goed interpreteert, valt om zodra een 7B-model het overneemt.

De regel die dat afvangt: **elke evaluatie draait tegen het productiemodel, nooit
tegen het model dat meebouwde.** De grens tussen bouwen en draaien staat getekend
in `ontwikkeltijd_vs_draaitijd.svg` en als werkafspraak in `CLAUDE.md`.

## 7. Openstaande beslissingen

- Eval-set bouwen (resultaat-gebaseerd, gelijkspel toegestaan) om de kleinste
  werkbare modelopstelling te bewijzen.
- `ask.py` naar de OpenAI-compatibele API voor wisselbare runtime/host.
- Definitieve hostingkeuze (eigen M1 vs groene EU-VPS).
- Verbruiksmeting per vraag als zichtbare functie in de demo.
- Codestral 2 (Apache 2.0) via MLX als waarden-alternatief evalueren tegen Qwen.

## Bronnen

- Infomaniak — 100% hernieuwbare energie, Zwitserse dataveiligheid:
  https://european-alternatives.eu/product/infomaniak
- Hetzner — duurzaam hosting-alternatief:
  https://www.sustysubs.net/alternatives/hetzner/
- Codestral 2 onder Apache 2.0:
  https://aitooltier.com/tools/codestral
