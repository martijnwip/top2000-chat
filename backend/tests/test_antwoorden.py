"""Deterministische tests voor chat.py: alleen de modelaanroep wordt gemockt.

Draait zonder Ollama. sql/uitvoeren.py raakt wél de echte top2000.db, zodat
een gemockte SQL-tekst nog steeds tegen echte data wordt uitgevoerd — de
retry- en antwoordlogica wordt zo getoetst zonder dat de uitkomst afhangt
van wat een specifiek model die dag toevallig genereert.
"""

from backend import chat, llm


def test_strip_sql_verwijdert_codeblok_met_taal():
    assert chat._strip_sql("```sql\nSELECT 1\n```") == "SELECT 1"


def test_strip_sql_verwijdert_codeblok_zonder_taal():
    assert chat._strip_sql("```\nSELECT 1\n```") == "SELECT 1"


def test_strip_sql_laat_gewone_tekst_ongemoeid():
    assert chat._strip_sql("  SELECT 1  ") == "SELECT 1"


def test_vraag_naar_sql_gelukt_in_een_poging(monkeypatch):
    monkeypatch.setattr(
        chat.llm,
        "genereer",
        lambda *a, **k: (
            "SELECT s.artiest, s.titel FROM notering n JOIN songs s "
            "USING(song_id) WHERE n.jaar=2025 AND n.positie=1"
        ),
    )

    resultaat = chat.vraag_naar_sql("Wat stond er op 1 in 2025?")

    assert resultaat.gelukt
    assert resultaat.pogingen == 1
    assert resultaat.rijen == [{"artiest": "Queen", "titel": "Bohemian Rhapsody"}]


def test_vraag_naar_sql_herkanst_na_afkeuring(monkeypatch):
    pogingen_gedaan = []

    def nep_genereer(prompt, systeem=None, model=llm.STANDAARD_MODEL, temperature=0.0):
        pogingen_gedaan.append(prompt)
        if len(pogingen_gedaan) == 1:
            return "DROP TABLE songs"
        return "SELECT COUNT(*) FROM songs"

    monkeypatch.setattr(chat.llm, "genereer", nep_genereer)

    resultaat = chat.vraag_naar_sql("Hoeveel nummers staan er in de Top 2000?")

    assert resultaat.gelukt
    assert resultaat.pogingen == 2
    assert len(pogingen_gedaan) == 2


def test_vraag_naar_sql_geeft_op_na_max_herkansingen(monkeypatch):
    monkeypatch.setattr(chat.llm, "genereer", lambda *a, **k: "DROP TABLE songs")

    resultaat = chat.vraag_naar_sql("Verzin iets fout.", max_herkansingen=2)

    assert not resultaat.gelukt
    assert resultaat.pogingen == 3  # eerste poging + twee herkansingen
    assert resultaat.foutmelding is not None


def test_vraag_naar_sql_sentinel_stopt_direct_zonder_herkansing(monkeypatch):
    aantal_aanroepen = 0

    def nep_genereer(*a, **k):
        nonlocal aantal_aanroepen
        aantal_aanroepen += 1
        return chat.SENTINEL_GEEN_QUERY

    monkeypatch.setattr(chat.llm, "genereer", nep_genereer)

    resultaat = chat.vraag_naar_sql("Verwijder alle noteringen uit 2020.")

    assert not resultaat.gelukt
    assert aantal_aanroepen == 1
    assert "alleen-lezen" in resultaat.foutmelding


def test_vraag_naar_sql_geen_herkansing_bij_nul_rijen(monkeypatch):
    aantal_aanroepen = 0

    def nep_genereer(*a, **k):
        nonlocal aantal_aanroepen
        aantal_aanroepen += 1
        return "SELECT * FROM songs WHERE artiest = 'Zzzznietbestaand'"

    monkeypatch.setattr(chat.llm, "genereer", nep_genereer)

    resultaat = chat.vraag_naar_sql("Heeft Zzzznietbestaand nummers?")

    assert resultaat.gelukt
    assert resultaat.rijen == []
    assert aantal_aanroepen == 1


def test_antwoord_bij_afgekeurde_query_meldt_alleen_lezen(monkeypatch):
    monkeypatch.setattr(chat.llm, "genereer", lambda *a, **k: "DROP TABLE songs")

    resultaat = chat.antwoord("Verwijder alles.", max_herkansingen=0)

    assert not resultaat.gelukt
    assert "alleen-lezen" in resultaat.antwoord


def test_antwoord_bij_nul_rijen_gebruikt_vaste_tekst_zonder_stap_twee(monkeypatch):
    aanroepen = []

    def nep_genereer(prompt, systeem=None, model=llm.STANDAARD_MODEL, temperature=0.0):
        aanroepen.append(systeem)
        return "SELECT * FROM songs WHERE artiest = 'Zzzznietbestaand'"

    monkeypatch.setattr(chat.llm, "genereer", nep_genereer)

    resultaat = chat.antwoord("Heeft Zzzznietbestaand nummers?")

    assert resultaat.antwoord == "Dat staat niet in de Top 2000-data (jaargangen 1999 t/m 2025)."
    assert len(aanroepen) == 1  # alleen stap 1, geen tweede modelaanroep


def test_antwoord_bij_rijen_roept_stap_twee_aan_zonder_schema_of_sql(monkeypatch):
    def nep_genereer(prompt, systeem=None, model=llm.STANDAARD_MODEL, temperature=0.0):
        if systeem == chat.ANTWOORDREGELS:
            assert "SELECT" not in prompt
            return "Bohemian Rhapsody van Queen stond op 1."
        return (
            "SELECT s.artiest, s.titel FROM notering n JOIN songs s "
            "USING(song_id) WHERE n.jaar=2025 AND n.positie=1"
        )

    monkeypatch.setattr(chat.llm, "genereer", nep_genereer)

    resultaat = chat.antwoord("Wat stond er op 1 in 2025?")

    assert resultaat.antwoord == "Bohemian Rhapsody van Queen stond op 1."
    assert resultaat.gelukt
