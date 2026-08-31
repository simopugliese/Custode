"""Migrazioni dello schema SQLite.

Ogni migrazione è un file `NNN_nome.sql` in questa cartella, applicato una sola
volta e in ordine di numero. La tabella `schema_migrations` tiene il conto: è
l'unica cosa che serve per sapere se un database è aggiornato, sul Pi come in
un container di test appena creato.

Le migrazioni non si modificano dopo essere state applicate in produzione: per
cambiare qualcosa se ne aggiunge una nuova.

**Più processi insieme.** API e bot partono in parallelo e migrano entrambi
lo stesso file. Per questo l'intera operazione — leggere cosa è già applicato
*e* applicare il resto — sta dentro un'unica transazione aperta con
`BEGIN IMMEDIATE`: chi arriva secondo aspetta il lock di scrittura (fino a
`busy_timeout`) e poi trova il registro già aggiornato, invece di riprovare ad
applicare migrazioni già fatte.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

CARTELLA = Path(__file__).parent


def _file_migrazioni() -> list[Path]:
    return sorted(CARTELLA.glob("[0-9][0-9][0-9]_*.sql"))


def _istruzioni(sql: str) -> Iterator[str]:
    """Spezza uno script SQL nelle sue istruzioni.

    Si usa `sqlite3.complete_statement` invece di dividere sul punto e virgola:
    riconosce le istruzioni davvero terminate, quindi non si fa ingannare da un
    `;` dentro una stringa o un trigger. Serve perché `executescript` farebbe un
    COMMIT implicito, rompendo la transazione che tiene insieme la migrazione.
    """
    corrente = ""
    for riga in sql.splitlines(keepends=True):
        corrente += riga
        if sqlite3.complete_statement(corrente):
            if corrente.strip():
                yield corrente
            corrente = ""
    if corrente.strip():
        yield corrente


def _assicura_registro(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " nome TEXT PRIMARY KEY,"
        " applicata_il TEXT NOT NULL)"
    )


def applicate(conn: sqlite3.Connection) -> set[str]:
    """Nomi delle migrazioni già applicate a questo database."""
    _assicura_registro(conn)
    return {riga["nome"] for riga in conn.execute("SELECT nome FROM schema_migrations")}


def migra(conn: sqlite3.Connection) -> list[str]:
    """Applica le migrazioni mancanti. Ritorna i nomi di quelle applicate ora.

    È idempotente: chiamarla su un database già aggiornato non fa nulla, quindi
    può girare all'avvio di ogni servizio, ad ogni deploy.
    """
    _assicura_registro(conn)
    nuove: list[str] = []

    # IMMEDIATE prende subito il lock di scrittura: da qui nessun altro
    # processo può infilarsi fra la lettura del registro e la scrittura.
    conn.execute("BEGIN IMMEDIATE")
    try:
        gia_fatte = {riga["nome"] for riga in conn.execute("SELECT nome FROM schema_migrations")}
        for percorso in _file_migrazioni():
            if percorso.name in gia_fatte:
                continue
            for istruzione in _istruzioni(percorso.read_text(encoding="utf-8")):
                conn.execute(istruzione)
            conn.execute(
                "INSERT INTO schema_migrations (nome, applicata_il)" " VALUES (?, datetime('now'))",
                (percorso.name,),
            )
            nuove.append(percorso.name)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")

    return nuove
