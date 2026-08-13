"""Bewijst dat sql/veiligheid.py precies de vorm uit spec §3.3 toelaat."""

import pytest

from backend.sql.veiligheid import OnveiligeQuery, keur

# --- toegestaan ------------------------------------------------------------


def test_eenvoudige_select():
    assert keur("SELECT * FROM songs") == "SELECT * FROM songs"


def test_join_tussen_songs_en_notering():
    sql = "SELECT s.artiest, s.titel FROM notering n JOIN songs s USING(song_id) WHERE n.jaar=2025"
    assert keur(sql) == sql


def test_with_cte_over_toegestane_tabellen():
    sql = (
        "WITH top AS (SELECT song_id FROM notering WHERE jaar=2025 AND positie<=10) "
        "SELECT s.artiest FROM songs s JOIN top t ON t.song_id = s.song_id"
    )
    assert keur(sql) == sql


def test_trailing_puntkomma_wordt_verwijderd():
    assert keur("SELECT 1;") == "SELECT 1"


def test_kleine_letters_select_ook_toegestaan():
    assert keur("select * from songs") == "select * from songs"


def test_rand_whitespace_wordt_gestript():
    assert keur("  SELECT * FROM songs  \n") == "SELECT * FROM songs"


# --- geweigerd: verboden trefwoorden ---------------------------------------


@pytest.mark.parametrize(
    "trefwoord",
    [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "REPLACE",
        "PRAGMA",
        "ATTACH",
        "DETACH",
        "VACUUM",
    ],
)
def test_verboden_trefwoorden_worden_geweigerd(trefwoord):
    with pytest.raises(OnveiligeQuery):
        keur(f"SELECT * FROM songs; {trefwoord} songs")
    with pytest.raises(OnveiligeQuery):
        keur(f"{trefwoord} INTO songs VALUES (1)")


def test_delete_los_trefwoord_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("DELETE FROM songs")


def test_drop_table_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("DROP TABLE songs")


# --- geweigerd: meerdere statements ----------------------------------------


def test_meerdere_statements_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("SELECT * FROM songs; SELECT * FROM notering")


# --- geweigerd: commentaartekens --------------------------------------------


def test_dubbel_streepje_commentaar_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("SELECT * FROM songs -- DROP TABLE songs")


def test_blok_commentaar_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("SELECT * FROM songs /* verborgen */")


# --- geweigerd: sqlite_-tabellen --------------------------------------------


def test_sqlite_master_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("SELECT * FROM sqlite_master")


def test_sqlite_stat_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("SELECT * FROM sqlite_stat1")


# --- geweigerd: verkeerd startpunt of tabellen buiten het schema -----------


def test_query_moet_beginnen_met_select_of_with():
    with pytest.raises(OnveiligeQuery):
        keur("EXPLAIN SELECT * FROM songs")


def test_lege_query_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("   ")


def test_tabel_buiten_schema_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("SELECT * FROM wikipedia_tekst")


def test_join_met_niet_toegestane_tabel_geweigerd():
    with pytest.raises(OnveiligeQuery):
        keur("SELECT * FROM songs s JOIN wikidata_feit w ON w.qid = s.mb_artist_id")
