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
    assert applicate == ["001_task_lista_spesa.sql"]
    assert {"tasks", "shopping_list", "schema_migrations"} <= _tabelle(conn)
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

    assert migrazioni.migra(primo) == ["001_task_lista_spesa.sql"]
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
