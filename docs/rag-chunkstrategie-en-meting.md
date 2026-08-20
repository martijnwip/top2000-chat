# RAG: chunkstrategie en meetopzet

*Concept, 13 augustus 2026. Alle cijfers in §1 zijn gemeten; de tabellen in §5
zijn leeg en horen door een meting gevuld te worden, niet door een schatting.*

## 1. Waar het nu op vastloopt

Gemeten met `eval_rag.py` tegen `data/rag_index.db`, corpus `songs`, k=5,
embedmodel `bge-m3` via Ollama, generatiemodel niet betrokken.

| Categorie | lexicaal | vector | hybride |
|---|---|---|---|
| naam (8 vragen) | 100% | 100% | 100% |
| omschrijving (10 vragen) | 10% | 20% | 10% |

De naam-vragen zijn klaar. De omschrijvingsvragen falen, en dat is precies
waarvoor de RAG-laag bestaat: alles wat met een titel of artiestnaam te
beantwoorden is, kan het SQL-pad al.

Twee van de twaalf omschrijvingsvragen tellen niet mee. *Another Brick in the
Wall* (song 118) en *Welterusten meneer de president* (song 560) hebben geen
verhalende tekst in het corpus, alleen een feitenblok van ongeveer 225 tekens.
Onvindbaar, niet gemist.

### 1.1 Het corpus is niet het probleem

Bij elk van de missers staat het antwoord letterlijk in de tekst:

| Nummer | Chunk | Wat er staat |
|---|---|---|
| Starman | 2.493 tekens | "de jeugd van de planeet aarde door middel van het gebruik van de radio, een redding van een alien genaamd Starman" |
| Every Breath You Take | 2.333 tekens | "gaat het nummer in essentie over stalking" |
| Hotel California | 2.366 tekens | "You can checkout any time you like, But you can never leave" |
| Eleanor Rigby | 1.319 tekens | "Een strijkoctet van vier violisten, twee altviolisten en twee cellisten" |

De vraag en het antwoord liggen dicht bij elkaar. De chunk waarin dat antwoord
staat gaat daarnaast over opnamen, hitnoteringen en covers. Eén vector over
2.500 tekens middelt die ene rake zin weg tegen alles eromheen.

### 1.2 De omvang van het probleem

Verhaal-chunks: 24.597 stuks, samen 21,0 miljoen tekens.

| Maat | Waarde |
|---|---|
| mediaan | 664 tekens |
| p75 | 1.186 |
| p90 | 1.849 |
| max | 2.504 |
| boven 1.500 tekens | 4.013 chunks (16%) |

Die lange chunks zijn juist de secties "Achtergrond" en "Interpretatie" — waar
de betekenis in staat.

### 1.3 Splitsen op alinea helpt nauwelijks

93% van de verhaal-chunks bestaat al uit één alinea. Splitsen op lege regel
brengt 24.597 chunks naar 27.179, en 32% van die alinea's blijft boven de 900
tekens. De alinea's in Wikipedia-artikelen zijn zelf lang.

Zinnen zijn wel kort: mediaan 106 tekens, p90 206.

### 1.4 Fusie verliest van de vector

Hybride scoort op omschrijvingen slechter dan vector alleen. RRF telt posities
uit twee ranglijsten op en veronderstelt dat beide iets weten. Bij naam-vragen
klopt dat. Bij omschrijvingen levert BM25 ruis, en die ruis krijgt in de fusie
evenveel gewicht. *Starman* staat bij vector buiten de top-5 maar bij hybride op
1; *Every Breath You Take* verdwijnt juist door de fusie.

## 2. Voorstel: vensters van zinnen

Knip de verhaal-tekst niet op sectie maar op zinnen, en groepeer die tot
vensters met overlap.

| Parameter | Waarde | Waarom |
|---|---|---|
| doelgrootte | 500 tekens | mediaan zin is 106 tekens; ongeveer vier zinnen per venster |
| overlap | 25%, oftewel ~1 zin | een antwoord dat over een zinsgrens loopt blijft in één venster |
| minimum | 200 tekens | kortere restjes plakken aan het vorige venster |
| maximum | 800 tekens | harde bovengrens; een zin langer dan 800 wordt op komma gesplitst |
| kop meegeëmbed | ja | "Starman — David Bowie · Achtergrond" hoort bij de betekenis van het venster |

Verwachte omvang: ongeveer 56.000 verhaal-chunks in plaats van 24.597. Met de
7.076 feitenblokken erbij komt de index op circa 63.000 chunks.

### Wat níet verandert

- **Feitenblokken blijven zoals ze zijn.** Die zijn kort, gestructureerd, en
  doen hun werk bij naam-vragen. Alleen `soort_blok = 'verhaal'` wordt opnieuw
  geknipt.
- **Vectoren blijven op teksthash staan.** Dat is de reden dat een herbouw
  betaalbaar is. Vensters die identiek blijven, worden niet opnieuw geëmbed.
- **De FTS-tabel blijft ongewijzigd van vorm**, maar wordt opnieuw gevuld: de
  rowid's veranderen mee met de chunks.
- **`bge-m3` blijft het embedmodel.** Eén verandering per meting, anders is niet
  te zien wat het verschil maakte.

### Kosten van de herbouw

Ongeveer 56.000 vensters embedden. De bestaande vectoren zijn niet herbruikbaar,
want elk venster is een andere tekst en dus een andere hash. Meet hoe lang
`bge-m3` over duizend vensters doet voordat je de hele bak draait, en noteer dat
in §5. Dit is de bouwstap; hij draait één keer, niet per vraag.

### 2.1 Opruimen: wel bouwen, niet automatisch

Vectoren staan op teksthash en niet op chunk. Dat is met opzet zo: een herbouw
van het corpus hoeft dan niet alles opnieuw te embedden. De keerzijde is dat
vectoren blijven staan als de chunk waar ze bij hoorden verdwijnt. In de huidige
index zijn dat er 15.951 van de 47.624 — restanten van eerdere chunkversies.

Na het herchunken wordt dat een reëel probleem. Elke vector is 4 KB:

| | Vectoren | Omvang |
|---|---|---|
| bestaand, straks zonder chunk | 47.624 | 195 MB |
| nieuw, zinsvensters + feiten | ~63.000 | 258 MB |
| **index zonder opruimen** | | **~480 MB** |
| **index na opruimen** | | **~285 MB** |

De opruiming zelf is één query plus een `VACUUM`:

```sql
DELETE FROM vector
 WHERE tekst_hash NOT IN (SELECT tekst_hash FROM chunk);
VACUUM;
```

**Twee regels eromheen, en die zijn belangrijker dan de query zelf.**

*Nooit automatisch tijdens het bouwen.* Zolang de oude vectoren er staan, is
teruggaan naar de oude chunkstrategie gratis: de hashes bestaan nog, er hoeft
niets opnieuw geëmbed te worden. Ruim je op tijdens de herbouw, dan kost een
stap terug opnieuw 24.597 embeddings. Die 195 MB is de prijs van een omkeerbare
meting, en die is hem waard tot de keuze gemaakt is.

*Opruimen als aparte opdracht, na afloop.* Een `--opruimen`-vlag op het
bouwcommando, of een los subcommando. Draai die pas als meting 2 is afgerond én
de nieuwe chunkstrategie de betere blijkt. Rapporteer hoeveel vectoren zijn
verwijderd en hoeveel het bestand kleiner werd, zodat er iets te controleren
valt.

## 3. Voorstel: fusie alleen bij signaal

Twee wijzigingen in `zoek()`, beide zonder opnieuw te embedden te meten.

**a. Fuseer niet wanneer de lexicale lijst leeg of te kort is.** Levert BM25
minder dan een handvol kandidaten op, gebruik dan de vectorranglijst.

**b. Weeg de twee helften.** RRF met een gewicht per ranglijst: de bijdrage van
lijst *i* wordt `w_i / (K + rang)`. Met `w_vector = 1,0` en `w_lexicaal < 1,0`
telt BM25 mee zonder de vector te kunnen overstemmen. Meet bij `w_lexicaal` in
0,25 / 0,5 / 0,75 / 1,0 wat er met beide categorieën gebeurt — een gewicht dat
omschrijvingen redt maar naam-vragen sloopt, is geen verbetering.

Beide varianten moeten los gemeten worden, niet samen met de herchunking.

## 4. Voorstel: een versietabel in de index

De index is nu niet te onderscheiden van een andere index met andere
instellingen. Toevoegen:

```sql
CREATE TABLE IF NOT EXISTS index_versie (
    gebouwd_op    TEXT NOT NULL,   -- ISO-datum
    embed_model   TEXT NOT NULL,   -- 'bge-m3'
    dim           INTEGER NOT NULL,
    chunk_strategie TEXT NOT NULL, -- 'sectie' | 'zinsvenster-500-25'
    corpus_hash   TEXT NOT NULL,   -- sha256 over de jsonl-bestanden
    aantal_chunks INTEGER NOT NULL,
    toelichting   TEXT
);
```

De zoeklaag leest die tabel bij het openen en weigert te draaien wanneer het
embedmodel van de vraag afwijkt van het model in de tabel. Dat is de enige
faalmodus die zich niet als fout meldt maar als plausibel klinkende onzin.

## 5. Meetopzet

Elke meting draait `eval_rag.py` met dezelfde 20 vragen en dezelfde k, en
rapporteert het embedmodel. Eén verandering per meting.

**Meting 0 — nulmeting.** Al gedaan; de uitkomst staat in §1. Dit is de meetlat.

**Meting 1 — fusie herzien, oude chunks.** Draait op de bestaande index, dus
zonder opnieuw te embedden. Gemeten met `backend/rag/eval.py --meting1`,
embedmodel `bge-m3` via Ollama, corpus `songs`, k=5, 20 vragen.

| Variant | naam @5 | omschrijving @5 | opmerking |
|---|---|---|---|
| hybride, ongewogen (nul) | 100% | 8% | zie kanttekening hieronder |
| geen fusie bij lege BM25 | 100% | 8% | geen effect: BM25 levert hier altijd ≥5 kandidaten. Inmiddels uit `VARIANTEN_METING1` verwijderd — kan nooit aanslaan, zie `eval.py` |
| w_lexicaal = 0,75 | 100% | 8% | |
| w_lexicaal = 0,50 | 100% | 17% | gekozen als standaard in de antwoordlaag |
| w_lexicaal = 0,25 | 100% | 17% | zelfde score als 0,50 én als kale vector-search, zie kanttekening hieronder |

**Kanttekening bij de 8% versus de 10% uit §1.** §1 rapporteert de
omschrijvingsscore over 10 vragen: de twee onvindbare (*Another Brick in the
Wall*, *Welterusten meneer de president*) waren daar met de hand uit de
noemer gehaald. `eval.py` doet dat niet automatisch — precies zoals het
originele `eval_rag.py` dat ook niet deed — en telt over alle 12. Beide tellen
dezelfde ene juiste treffer; alleen de noemer verschilt (1/10 = 10%,
1/12 ≈ 8%). Geverifieerd door het originele `eval_rag.py` tegen dezelfde index
te draaien: identieke uitkomst. Inmiddels heeft `data/rag_vragen.csv` een
kolom `heeft_corpus_tekst` (`nee` voor die twee vragen); `eval.py` rapporteert
sindsdien automatisch beide tellingen — over alle vragen en over alleen de
meetbare — zodat dit verschil niet meer stilzwijgend hoeft te worden
uitgerekend.

**Aanvulling (op de 20-vragenset): w_lexicaal = 0,25 wint niets meer dan
vector-only.** Per-vraag vergeleken (top-5-samenstelling van kale
vector-search tegenover fuseer() met w_lexicaal=0,25, min_lex_kandidaten=5,
op alle 20 vragen): in 7 van de 20 verschilt de top-5 — BM25 schuift een
kandidaat naar binnen of herschikt de volgorde — maar in geen van die zeven
verandert dat of het verwachte nummer wél of niet in de top-5 staat. Op deze
kleine set was 0,25 dus effectief gelijk aan vector-only. **Dit hield geen
stand op de grotere set — zie hieronder.**

**Conclusie meting 1 (20-vragenset, achterhaald).** w_lexicaal = 0,50
verdubbelt de omschrijvingsscore (8% → 17%) zonder dat naam-vragen zakken, en
leek daarmee per de maatstaf uit §3b een reële verbetering. Dit was de
aanleiding om `W_LEXICAAL = 0,50` als standaard in `antwoord.py` te zetten.
De herhaling hieronder, op bijna drie keer zoveel omschrijvingsvragen, laat
een ander beeld zien.

**Meting 1, herhaald op de grotere set (58 vragen, 13 augustus → nu).**
Na het samenvoegen van `data/rag_vragen_werklijst.csv` (spec §6 / stap 3 uit
`rag-waar-gebleven.md`) staan er 50 omschrijvingsvragen in plaats van 12.
Gemeten met `backend/rag/eval.py --meting1`, embedmodel `bge-m3` via Ollama,
corpus `songs`, k=5, 58 vragen (8 naam + 50 omschrijving).

| Variant | naam @5 | omschrijving @5 |
|---|---|---|
| vector-only (`--modus vector`, ter referentie) | 100% | 32% |
| hybride, ongewogen (nul) | 100% | 20% |
| w_lexicaal = 0,75 | 100% | 20% |
| w_lexicaal = 0,50 (huidige standaard in `antwoord.py`) | 100% | 24% |
| w_lexicaal = 0,25 | 100% | 28% |

**Dit keert de conclusie om.** Op de kleine set leek fusie neutraal tot licht
positief; op de grotere set is elke geteste fusieweging slechter dan kale
vector-search, en de terugval is monotoon met het gewicht: hoe meer BM25-
invloed, hoe lager de omschrijvingsscore. Per-vraag nagerekend op de 48
meetbare omschrijvingsvragen (`heeft_corpus_tekst = ja`): bij w_lexicaal=0,25
verliest hybride het verwachte nummer uit de top-5 bij 2 vragen waar
vector-only het wél vond, en wint bij geen enkele — een netto verlies, niet
ruis die toevallig de andere kant op viel zoals bij de kleine set.

**Openstaand: de standaard in `antwoord.py` (`W_LEXICAAL = 0,50`) is nu niet
meer onderbouwd door de meting die hem koos.** Vector-only scoort op deze
grotere set het best gemeten. Vóór dit wijzigen: nagaan of dit patroon
standhoudt na het herchunken (meting 2) — de huidige chunks van 2.000-2.500
tekens zijn de reden dat BM25 op exacte woorden hier weinig toevoegt, dat kan
met kleinere, preciezere chunks anders liggen.

**Voorbereiding gedaan (19 augustus): `backend/rag/herchunk.py` en de
benchmark.** De knipstap zelf staat en is getest — zie `rag-waar-gebleven.md`
voor de bug-geschiedenis. Op het songs-corpus: 21.193 sectie-chunks ->
45.504 zinsvensters, gemiddeld 497 tekens, nul boven de harde 800-grens.

Benchmark van de embedstap (§2 "Kosten van de herbouw"): 1.000 vensters uit
een aparte, wegwerpbare testdatabase (niet `data/rag_index.db`) embedden met
`bge-m3` via Ollama kostte **160s** (`caffeinate -i`, dus de Mac bleef wakker
tijdens het draaien). Dat is ~6,3 vensters/s. Geëxtrapoleerd naar alle 45.504
vensters: **circa 2 uur** (45.504 / 1000 × 160s ≈ 7.280s ≈ 121 min).

**De volledige herbouw is gedraaid (19 augustus, 17:48).** Tegen een aparte
database (`data/rag_index_zinsvenster.db`, 310 MB — nog steeds niet
`data/rag_index.db`, de site draaide gewoon door op de oude index). 50.429
chunks (45.504 vensters + 4.925 ongewijzigde feitenblokken, in een verse
database dus allebei opnieuw te embedden), 7.594s (~2u 6min), met
`caffeinate -i`. Versie geregistreerd als `zinsvenster-500-25`.

**Meting 2 — zinsvensters, gemeten met dezelfde 58 vragen als meting 1.**

| Modus | naam @5 | omschr. top-1 | top-3 | top-5 | gem. rang |
|---|---|---|---|---|---|
| lexicaal | 100% | 2% | 6% | 10% | 2.8 |
| vector | 100% | 18% | 26% | 32% | 1.9 |
| hybride (1,0/1,0) | 100% | 8% | 14% | 20% | 2.5 |

Fusievarianten (`--meting1`, zelfde opzet als §5 meting 1):

| Variant | naam @5 | omschrijving @5 |
|---|---|---|
| hybride, ongewogen (nul) | 100% | 20% |
| w_lexicaal = 0,75 | 100% | 24% |
| w_lexicaal = 0,50 | 100% | 24% |
| w_lexicaal = 0,25 | 100% | 24% |

**Conclusie meting 2 — het herchunken loste het probleem niet op.**
Vector-only haalt op de nieuwe index exact hetzelfde recall@5 als op de oude:
**32% blijft 32%**. Top-1 ging iets omhoog (14% → 18%) en de gemiddelde rang
verbeterde licht (2,1 → 1,9), maar het getal waar dit hele traject om
begonnen is — hoeveel vaker het juiste nummer in de top-5 staat — is
onveranderd. Bij de fusievarianten schoof iets: 0,75 werd beter (20% → 24%),
0,25 werd slechter (28% → 24%), maar geen enkele fusieweging haalt hier of
op de oude index vector-only in.

Dit weerlegt de werkhypothese uit §1 niet per se (de juiste zin ligt
aantoonbaar dichter bij zijn eigen betekenis nu, zie de kortere gem. rang),
maar het bevestigt ook niet dat kleinere chunks de kernbeperking waren.
`bge-m3` blijkt de rake zin kennelijk al goed genoeg op te pikken uit een
chunk van 2.000 tekens — het knippen zelf was dus niet de bottleneck. Waar
die wel zit, is nog niet gemeten; kandidaten: het model zelf (bge-m3 is een
kleine, algemene embedder), de vraagformulering versus de artikelformulering
("een lied over een bokser die onterecht is veroordeeld" tegenover een
Wikipedia-lopende tekst), of gewoon dat 12-50 vragen nog te weinig is om
verder dan ruis te onderscheiden.

**Meting 3 — drempel opnieuw ijken.** `antwoord_rag.py` weigert te antwoorden
onder een cosine van 0,50. Kleinere chunks verschuiven de cosine-verdeling, dus
die drempel moet opnieuw vastgesteld worden: meet de cosine van de juiste
treffer bij de 20 vragen, en de hoogste cosine bij de vier `afwezig`-vragen. De
drempel hoort tussen die twee verdelingen te liggen.

| Grootheid | Waarde |
|---|---|
| mediaan cosine bij een juiste treffer | |
| laagste cosine bij een juiste treffer | |
| hoogste cosine bij een `afwezig`-vraag | |
| voorgestelde drempel | |

### Wanneer is het goed genoeg

De vraag die dit moet beantwoorden: voegt de RAG-laag iets toe aan wat SQL al
kan? Voor naam-vragen is het antwoord nee — die kan SQL ook. Het bestaansrecht
zit volledig in de omschrijvingen.

Voorstel voor de ondergrens, vast te leggen vóór de meting: **omschrijving
recall@5 van 60% of hoger, zonder dat naam-vragen onder de 100% zakken.** Wordt
dat na meting 2 niet gehaald, dan is de conclusie niet "verder tunen" maar een
keuze: andere chunkgrootte, een ander embedmodel, of de RAG-laag beperken tot
vragen waar hij aantoonbaar wint.

## 6. Wat de eval-set zelf nog nodig heeft

Alle 28 vragen in `data/rag_vragen.csv` staan op `gecontroleerd = nee`. De
`song_id`'s zijn tegen de database gecontroleerd en kloppen, maar het oordeel
"dit is het enige juiste antwoord" is nog niet door een mens gegeven.

Eén geval laat zien waarom dat telt. Bij "Nederlandstalig nummer over de
dreiging van een kernoorlog" zet de vectorzoeker *99 Luftballons* op 1, met de
sectie "Use as a Cold War anthem". Inhoudelijk is dat een goed antwoord; alleen
het woord "Nederlandstalig" sluit het uit. Zolang zo'n vraag één gouden antwoord
kent, meet de uitslag ook de scherpte van de vraagstelling.

Aan te bevelen: een kolom voor aanvaardbare alternatieven, zodat een tweede
juist antwoord niet als misser telt.

## 7. Bouwvolgorde

Stap 1 t/m 4 zijn gedaan zoals hieronder beschreven. Stap 5 t/m 8 wijken af
van de oorspronkelijke volgorde: de meetlat uit §5 is er om het herchunken
(het oude stap 5) te sturen, maar het grootste deel van de applicatie —
padkeuze, antwoordlaag, CLI, project-corpus — hangt daar niet van af en kan
eerder. Het herchunken is met opzet naar achteren geschoven, niet geschrapt:
zonder een gemeten omschrijvingsscore van 60%+ is er nog geen reden om de
huidige aanpak (antwoorden op 17% @5 voor omschrijvingen) als eindpunt te
beschouwen.

| Stap | Wat | Zwaar? | Status |
|---|---|---|---|
| 1 | `backend/rag/index.py` — bouwen: chunken, embedden, FTS vullen, versietabel schrijven, plus de opruiming uit §2.1 achter een aparte vlag. Overzetten uit `rag_index.py`, met bouwen en zoeken gescheiden. | nee, alleen code | gedaan |
| 2 | `backend/rag/zoek.py` — zoeken: BM25, cosine, gewogen fusie. Leest de versietabel en weigert bij een modelverschil. | nee | gedaan |
| 3 | `backend/rag/eval.py` — de meetlopers uit §5. Draait zonder generatiemodel. | nee | gedaan |
| 4 | Meting 1: fusie bijstellen op de bestaande index. Geen herbouw, twintig vragen per variant. | nee, seconden | gedaan, zie §5 |
| 5 | Padkeuze — `backend/router.py` met `backend/router_eval.py` als meetloper tegen `data/pad_vragen.csv`. Regels, geen model. | nee | gedaan, 30/30 (§5-achtig, zie router_eval) |
| 6 | Antwoordlaag — `antwoord_rag.py` overzetten, cosine-drempel vóór het model. Gebruikt de w_lexicaal = 0,50-fusie uit meting 1 als standaard. | nee | gedaan |
| 7 | CLI koppelen — één `ask` die routeert (sql / rag_songs / rag_project) en antwoordt, met `--show-sql` of de opgehaalde bronnen erbij. | nee | gedaan |
| 8 | Project-corpus — de markdown-bestanden in `docs/` chunken en indexeren onder corpus `project`, zodat het pad `rag_project` iets vindt. | nee, klein | gedaan, 129 chunks uit 4 bestanden — `reclaim-intelligence.md` bewust buiten de corpus gelaten, zie `backend/rag/corpus_project.py` |
| 9 | **Herchunken en opnieuw embedden** (het oude stap 5), daarna meting 2. | **ja — dit is de enige lange draai** | |
| 10 | Meting 3: de cosine-drempel opnieuw ijken na het herchunken. | nee | |

Opruimen gebeurt ná stap 9, en pas wanneer de nieuwe chunkstrategie de betere
blijkt.

### De lange draai van stap 9 in de praktijk

```bash
caffeinate -i python3 -m backend.rag.index --herbouw 2>&1 | tee logs/herbouw.log
```

`caffeinate -i` houdt de machine wakker zolang het commando loopt. De klep
dichtdoen laat hem alsnog slapen; dat vangt `caffeinate` niet af.

Het logbestand is er voor §5: embedtijd, aantal vensters en eventuele fouten
staan er achteraf in, in plaats van in een teruggescrolde terminal.

Afbreken is niet erg. Vectoren staan op teksthash, dus een herstart slaat over
wat al geëmbed is. De bouwstap moet daarom idempotent zijn: twee keer draaien
levert dezelfde index op, niet dubbele chunks. Dat is een eis aan `index.py`,
geen vanzelfsprekendheid — chunks staan op `chunk_id`, niet op hash, dus een
herbouw moet de oude chunks van het corpus eerst weggooien.
