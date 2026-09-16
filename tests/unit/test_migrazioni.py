"""Il runner delle migrazioni: idempotenza e atomicità (§3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from custode_core import migrazioni
from custode_core.db import connect


def _tabelle(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_crea_lo_schema(db_path: Path) -> None:
    conn = connect(db_path)
    applicate = migrazioni.migra(conn)
    # Tutte quelle presenti, in ordine di numero: elencarle a mano qui
    # significherebbe aggiornare questo test ad ogni modulo nuovo senza
    # verificare niente di più.
    assert applicate == [p.name for p in migrazioni._file_migrazioni()]
    assert applicate[0] == "001_task_lista_spesa.sql"
    assert {
        "tasks",
        "shopping_list",
        "diary_entries",
        "diary_fragments",
        "schema_migrations",
    } <= _tabelle(conn)
    conn.close()


def test_e_idempotente(db_path: Path) -> None:
    conn = connect(db_path)
    migrazioni.migra(conn)
    # Il secondo giro non deve riapplicare niente: è quello che gira ad ogni
    # avvio dell'API, ad ogni deploy.
    assert migrazioni.migra(conn) == []
    conn.close()


def test_riprende_su_un_database_gia_migrato(db_path: Path) -> None:
    prima = connect(db_path)
    migrazioni.migra(prima)
    prima.execute("INSERT INTO tasks (titolo, creato_il) VALUES ('x', '2026-08-31T08:41:00')")
    prima.close()

    dopo = connect(db_path)
    assert migrazioni.migra(dopo) == []
    assert dopo.execute("SELECT count(*) AS n FROM tasks").fetchone()["n"] == 1
    dopo.close()


def test_una_migrazione_rotta_non_lascia_niente_a_meta(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tutto o niente: il database resta alla versione precedente."""
    rotta = tmp_path / "002_rotta.sql"
    rotta.write_text("CREATE TABLE buona (id INTEGER);\nQUESTA NON E SQL;", encoding="utf-8")
    monkeypatch.setattr(
        migrazioni,
        "_file_migrazioni",
        lambda: [migrazioni.CARTELLA / "001_task_lista_spesa.sql", rotta],
    )

    conn = connect(db_path)
    with pytest.raises(sqlite3.Error):
        migrazioni.migra(conn)

    assert "tasks" not in _tabelle(conn)
    assert "buona" not in _tabelle(conn)
    assert migrazioni.applicate(conn) == set()
    conn.close()


def test_due_processi_insieme_non_riapplicano_le_stesse_migrazioni(db_path: Path) -> None:
    """API e bot partono in parallelo sullo stesso file: non devono pestarsi.

    Le due connessioni sono aperte *prima* di qualunque migrazione, come
    succede quando i due container partono insieme.
    """
    primo = connect(db_path)
    secondo = connect(db_path)

    assert migrazioni.migra(primo) == [p.name for p in migrazioni._file_migrazioni()]
    # Il secondo trova il registro già aggiornato e non ritenta il DDL.
    assert migrazioni.migra(secondo) == []
    assert "tasks" in _tabelle(secondo)

    primo.close()
    secondo.close()


def test_spezza_le_istruzioni_senza_farsi_ingannare_dai_punti_e_virgola() -> None:
    sql = "CREATE TABLE a (t TEXT DEFAULT 'x; y');\nCREATE TABLE b (id INTEGER);\n"
    istruzioni = [i.strip() for i in migrazioni._istruzioni(sql)]
    assert istruzioni == [
        "CREATE TABLE a (t TEXT DEFAULT 'x; y');",
        "CREATE TABLE b (id INTEGER);",
    ]


# — la 009 ricostruisce una tabella piena (§8.10, pezzo 6) —


def _migra_fino_a(conn: sqlite3.Connection, esclusa: str) -> None:
    """Porta il database alla vigilia di una migrazione, come un Pi di ieri.

    Usa gli stessi pezzi del runner vero — spezzare lo script e segnare il
    registro — perché il punto di questi test è proprio come si comporta una
    migrazione applicata sopra dei dati già in tabella.
    """
    migrazioni._assicura_registro(conn)
    conn.execute("BEGIN IMMEDIATE")
    for percorso in migrazioni._file_migrazioni():
        if percorso.name >= esclusa:
            break
        for istruzione in migrazioni._istruzioni(percorso.read_text(encoding="utf-8")):
            conn.execute(istruzione)
        conn.execute(
            "INSERT INTO schema_migrations (nome, applicata_il) VALUES (?, datetime('now'))",
            (percorso.name,),
        )
    conn.execute("COMMIT")


EVENTI_DI_IERI = [
    # (id_esterno, titolo, inizio, serie_id, tipo, tag_proposto_il, confermato)
    ("ev1", "Analisi Matematica I", "2026-09-15T09:00:00", "serie-an", "lezione", True, True),
    ("ev2", "Analisi Matematica I", "2026-09-22T09:00:00", "serie-an", "lezione", True, True),
    ("ev3", "Palestra", "2026-09-15T18:00:00", "serie-pal", "palestra", True, False),
    ("ev4", "Treno per Napoli", "2026-09-20T07:00:00", "", "viaggio", False, False),
    ("ev5", "Ricevimento", "2026-09-16T15:00:00", "", "altro", False, False),
]


def _riempi_calendario(conn: sqlite3.Connection) -> None:
    timbro = "2026-09-15T08:00:00"
    conn.executemany(
        "INSERT INTO calendar_events (fonte, id_esterno, titolo, inizio, fine,"
        " tutto_il_giorno, luogo, serie_id, tipo, sincronizzato_il, tag_proposto_il,"
        " tag_confermato_da_te) VALUES ('google', ?, ?, ?, ?, 0, 'Aula 3', ?, ?, ?, ?, ?)",
        [
            (
                id_esterno,
                titolo,
                inizio,
                inizio.replace("T0", "T1"),
                serie,
                tipo,
                timbro,
                timbro if proposto else None,
                int(confermato),
            )
            for id_esterno, titolo, inizio, serie, tipo, proposto, confermato in EVENTI_DI_IERI
        ],
    )


def test_la_009_non_perde_un_evento_ne_un_tag(db_path: Path) -> None:
    """La ricostruzione della tabella è il momento in cui si perde tutto.

    Sul Pi `calendar_events` è piena di eventi veri, con dentro tag corretti a
    mano che non si possono ricostruire: qui si verifica che la 009 li rimetta
    **identici riga per riga**, id compresi — l'id esce nel contratto REST ed è
    quello su cui la pagina manda una correzione.
    """
    conn = connect(db_path)
    _migra_fino_a(conn, "009")
    _riempi_calendario(conn)
    prima = [dict(r) for r in conn.execute("SELECT * FROM calendar_events ORDER BY id")]

    # Da qui in poi ne arrivano altre: si controlla che la 009 sia quella
    # applicata per prima, non che sia l'unica.
    assert migrazioni.migra(conn)[0] == "009_tag_calendario_miei.sql"

    dopo = [dict(r) for r in conn.execute("SELECT * FROM calendar_events ORDER BY id")]
    assert dopo == prima
    conn.close()


def test_la_009_rimette_gli_indici_che_la_tabella_si_porta_via(db_path: Path) -> None:
    """Un DROP TABLE si porta via anche i suoi indici, e nessuno se ne accorge.

    Non si accorgerebbe nemmeno un test sui dati: senza indici il calendario
    risponde uguale, solo più piano — e su un Pi, con qualche migliaio di righe
    e una query ogni cinque minuti, «più piano» non si vede finché non è tardi.
    """
    conn = connect(db_path)
    migrazioni.migra(conn)

    indici = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
            " AND tbl_name = 'calendar_events' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert indici == {
        "idx_calendario_inizio",
        "idx_calendario_serie",
        "idx_calendario_da_taggare",
    }
    conn.close()


def test_la_009_toglie_il_check_e_mette_la_chiave_esterna(db_path: Path) -> None:
    """Il punto di tutta la ricostruzione: un tipo nuovo deve poter entrare.

    E uno che non esiste no — il CHECK se ne va, ma non lascia la colonna libera
    di contenere qualunque parola: al suo posto c'è la FK verso `calendar_tags`.
    """
    conn = connect(db_path)
    migrazioni.migra(conn)
    _riempi_calendario(conn)

    conn.execute(
        "INSERT INTO calendar_tags (slug, nome, descrizione, creato_il)"
        " VALUES ('spesa', 'Spesa', 'il supermercato.', '2026-09-15T08:00:00')"
    )
    conn.execute("UPDATE calendar_events SET tipo = 'spesa' WHERE id = 5")
    assert (
        conn.execute("SELECT tipo FROM calendar_events WHERE id = 5").fetchone()["tipo"] == "spesa"
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE calendar_events SET tipo = 'inventato' WHERE id = 5")
    conn.close()


def test_la_009_non_lascia_cancellare_un_tipo_ancora_addosso_a_un_evento(db_path: Path) -> None:
    """La FK è la rete sotto `elimina_tag`, non un suo duplicato.

    Il dominio controlla prima per poter dire *quanti* eventi lo usano; se
    qualcuno scrivesse in tabella senza passare di lì, questo è ciò che
    impedisce a un evento di restare con un tipo che non esiste più.
    """
    conn = connect(db_path)
    migrazioni.migra(conn)
    _riempi_calendario(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM calendar_tags WHERE slug = 'lezione'")

    # Uno che nessuno usa se ne va senza discutere.
    conn.execute("DELETE FROM calendar_events WHERE tipo = 'viaggio'")
    conn.execute("DELETE FROM calendar_tags WHERE slug = 'viaggio'")
    conn.close()
