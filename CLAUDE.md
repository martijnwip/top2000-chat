# Werkafspraken voor Claude in deze repo

Top2000.ai is een demonstrator van waarden-gedreven AI-infrastructuur; de Top 2000
is het voertuig. Zie `docs/ARCHITECTUUR-EN-WAARDEN.md` voor het waarom.
Dit bestand legt vast wat dat betekent voor jouw manier van werken hier.

## De belangrijkste grens

**Claude bouwt, Ollama draait.** Zie `docs/ontwikkeltijd_vs_draaitijd.svg`.

Er komt geen enkele API-call van een extern model in het draaipad van de app.
Alles onder de lijn in dat schema is lokaal: `bge-m3` embedt, een Qwen-model
genereert. Dat is geen implementatiedetail maar de kern van wat deze repo laat
zien; een "tijdelijke" externe call in het antwoordpad maakt de demonstratie
waardeloos.

## De val die daaruit volgt

Ontwikkel je de RAG mét Claude in de lus, dan tune je tegen een model dat een
orde van grootte capabeler is dan `qwen2.5:7b-instruct`. Middelmatige chunks die
Claude nog goed interpreteert, lopen op een 7B-model stuk — en dan concludeer je
dat je retrieval klopt terwijl je Claudes compensatievermogen hebt gemeten.

Daarom:

- **Elke eval draait tegen het productiemodel via Ollama, nooit tegen Claude.**
- Claude mag de eval-set schrijven, maar niet de gouden antwoorden leveren.
  Die komen uit de database, uit de bron, of uit handmatige controle.
- Rapporteer bij een meting altijd welk model draaide. Een getal zonder
  modelnaam is geen meting.

### Wat Claude wel en niet doet

| Wel                                   | Niet                                           |
| ------------------------------------- | ---------------------------------------------- |
| Ophaalscripts en pijplijnen schrijven | Antwoorden genereren die als referentie gelden |
| Corpora en eval-sets bouwen           | Zelf de kwaliteitsscore bepalen                |
| Data ophalen en normaliseren          | In het draaipad van de app zitten              |
| Code reviewen en meten                | Meetuitslagen invullen die niet zijn gedraaid  |

## Waar je begint

- `docs/spec-top2000-chat.md` — wat er gebouwd wordt: de SQL-route, de keuring
  van gegenereerde query's, de CLI en de bouwvolgorde. Lees dit voor je code
  schrijft.
- `tests/testset-top2000-chat.yaml` — 31 cases met een handgeschreven
  `controle_sql` per case. De gouden antwoorden komen uit de database, niet uit
  een model. Beoordeling gaat op resultaat, niet op de query: elke SQL die tot
  het goede antwoord leidt is goed.
- `data/routering_vragen.csv` — oudere eval-set. De kolom `verwachte_tool`
  beschrijft een route die niet gebouwd wordt, en drie antwoorden dateren van
  toen de verrijking op 1% stond. Zie spec §3.2b voor de gemeten waarden.

## Drie valkuilen in de data

Deze staan uitgewerkt in spec §3.2 en zijn alle drie tegen de database
gecontroleerd. Ze kosten je een halve dag als je ze zelf moet ontdekken.

1. **`song_id` is gelijk aan de positie in 2025**, voor alle 2000 rijen. Een
   query met `WHERE song_id <= 10` levert toevallig de top 10 van 2025 en is in
   elk ander jaar fout.
2. **Artiestnamen falen naar twee kanten.** De Dijk staat als
   `"Dijk , De DeDijk"`, dus `LIKE '%De Dijk%'` mist de band. En
   `LIKE '%Queen%'` sleept Queens of the Stone Age mee.
3. **`NULL` in een verrijkt veld betekent "nog niet opgehaald"**, niet
   "onbekend". Dekking: releasejaar 91%, land 91%, duur 87%. Een aggregatie
   zonder die dekking erbij is misleidend.

## Bronnen en licenties

- Wikipedia en Wikidata zijn CC BY-SA: bewaar bij elk opgehaald document de URL
  én de revisie-ID, zodat bronvermelding klopt en herhaalbaar is.
- Geen songteksten binnenhalen (auteursrecht).
- Wees zuinig met externe API's: cache op schijf, batch je queries, en zet een
  herkenbare User-Agent op verzoeken aan Wikimedia- en MusicBrainz-endpoints.

## Taal

Code, commentaar, commits en documentatie in het Nederlands. Commentaar legt uit
_waarom_ een keuze gemaakt is — en waar dat uit een meting of een fout volgde,
hoort dat erbij.
