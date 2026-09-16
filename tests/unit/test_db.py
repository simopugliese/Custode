"""La connessione SQLite parte in WAL, con le PRAGMA attese (§3).

E il «tutto o niente» con cui le rotte tengono insieme più scritture: senza,
una `PATCH` che valida ogni campo appena prima di scriverlo lascia scritti
quelli che precedono il campo storto, e risponde che non è cambiato niente.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from custode_core.db import connect, connessione, db_raggiungibile, transazione


def test_connessione_in_wal(db_path: Path) -> None:
    with connessione(db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_crea_la_cartella_mancante(tmp_path: Path) -> None:
    percorso = tmp_path / "non" / "ancora" / "esiste" / "custode.db"
    with connessione(percorso):
        pass
    assert percorso.exists()


def test_le_righe_sono_accessibili_per_nome(db_path: Path) -> None:
    with connessione(db_path) as conn:
        conn.execute("CREATE TABLE prova (titolo TEXT)")
        conn.execute("INSERT INTO prova (titolo) VALUES ('latte')")
        riga = conn.execute("SELECT titolo FROM prova").fetchone()
    assert riga["titolo"] == "latte"


def test_scrittura_persistente_fra_connessioni(db_path: Path) -> None:
    conn = connect(db_path)
    conn.execute("CREATE TABLE prova (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO prova (id) VALUES (1)")
    conn.close()

    with connessione(db_path) as altra:
        assert altra.execute("SELECT count(*) AS n FROM prova").fetchone()["n"] == 1


def test_db_raggiungibile(db_path: Path) -> None:
    assert db_raggiungibile(db_path) is True


def test_db_non_raggiungibile_se_il_percorso_non_e_un_file(tmp_path: Path) -> None:
    # Una cartella al posto del file: sqlite non può aprirla.
    cartella = tmp_path / "custode.db"
    cartella.mkdir()
    assert db_raggiungibile(cartella) is False


# — tutto o niente ——————————————————————————————————————


def _tabella(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE prova (id INTEGER PRIMARY KEY, titolo TEXT)")
    conn.execute("INSERT INTO prova (id, titolo) VALUES (1, 'prima')")


def test_la_transazione_consolida_quello_che_passa(db_path: Path) -> None:
    with connessione(db_path) as conn:
        _tabella(conn)
        with transazione(conn):
            conn.execute("UPDATE prova SET titolo = 'seconda' WHERE id = 1")

    with connessione(db_path) as altra:
        assert altra.execute("SELECT titolo FROM prova").fetchone()["titolo"] == "seconda"


def test_un_errore_a_meta_non_lascia_scritto_niente(db_path: Path) -> None:
    """Il caso per cui esiste: la prima scrittura passa, la seconda solleva."""
    with connessione(db_path) as conn:
        _tabella(conn)

        with pytest.raises(ValueError), transazione(conn):
            conn.execute("UPDATE prova SET titolo = 'seconda' WHERE id = 1")
            raise ValueError("il secondo campo è storto")

        assert conn.execute("SELECT titolo FROM prova").fetchone()["titolo"] == "prima"


def test_dopo_un_rollback_la_connessione_resta_usabile(db_path: Path) -> None:
    """Altrimenti il primo 422 di una richiesta rovinerebbe anche la risposta."""
    with connessione(db_path) as conn:
        _tabella(conn)

        with pytest.raises(ValueError), transazione(conn):
            raise ValueError("no")

        conn.execute("UPDATE prova SET titolo = 'terza' WHERE id = 1")
        assert conn.execute("SELECT titolo FROM prova").fetchone()["titolo"] == "terza"
