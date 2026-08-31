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


def test_una_migrazione_rotta_non_lascia_lo_schema_a_meta(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    # La prima è passata, la seconda no: nessuna traccia della sua tabella,
    # e non risulta applicata.
    assert "tasks" in _tabelle(conn)
    assert "buona" not in _tabelle(conn)
    assert migrazioni.applicate(conn) == {"001_task_lista_spesa.sql"}
    conn.close()
