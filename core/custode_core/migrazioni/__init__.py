"""Migrazioni dello schema SQLite.

Ogni migrazione è un file `NNN_nome.sql` in questa cartella, applicato una sola
volta e in ordine di numero. La tabella `schema_migrations` tiene il conto: è
l'unica cosa che serve per sapere se un database è aggiornato, sul Pi come in
un container di test appena creato.

Le migrazioni non si modificano dopo essere state applicate in produzione: per
cambiare qualcosa se ne aggiunge una nuova.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

CARTELLA = Path(__file__).parent


def _file_migrazioni() -> list[Path]:
    return sorted(CARTELLA.glob("[0-9][0-9][0-9]_*.sql"))


def applicate(conn: sqlite3.Connection) -> set[str]:
    """Nomi delle migrazioni già applicate a questo database."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " nome TEXT PRIMARY KEY,"
        " applicata_il TEXT NOT NULL)"
    )
    return {riga["nome"] for riga in conn.execute("SELECT nome FROM schema_migrations")}


def migra(conn: sqlite3.Connection) -> list[str]:
    """Applica le migrazioni mancanti. Ritorna i nomi di quelle applicate ora.

    È idempotente: chiamarla su un database già aggiornato non fa nulla, quindi
    può girare all'avvio dell'API ad ogni deploy.
    """
    gia_fatte = applicate(conn)
    nuove: list[str] = []

    for percorso in _file_migrazioni():
        nome = percorso.name
        if nome in gia_fatte:
            continue
        if "'" in nome:  # il nome finisce dentro lo script, vedi sotto
            raise ValueError(f"nome di migrazione non ammesso: {nome}")

        # `executescript` fa un COMMIT implicito di qualunque transazione in
        # corso prima di partire: BEGIN e COMMIT devono quindi stare dentro lo
        # script stesso, altrimenti la migrazione non sarebbe atomica e un
        # errore a metà lascerebbe lo schema ibrido.
        script = (
            "BEGIN;\n"
            f"{percorso.read_text(encoding='utf-8')}\n"
            "INSERT INTO schema_migrations (nome, applicata_il)"
            f" VALUES ('{nome}', datetime('now'));\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        nuove.append(nome)

    return nuove
