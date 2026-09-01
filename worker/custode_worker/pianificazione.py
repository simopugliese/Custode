"""Quando un job è dovuto — logica pura, nessun orologio e nessun database.

Tutto ciò che decide *se* è il momento sta qui e prende `adesso` come
parametro: la differenza fra un test che gira in un millesimo di secondo e uno
che aspetterebbe fino a domenica sera.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from custode_core.formato import inizio_settimana

RIEPILOGO_SETTIMANALE = "riepilogo_settimanale"


def momento_previsto(lunedi: date, giorno: str, ore: int, minuti: int) -> datetime:
    """Quando va chiusa la settimana che comincia il `lunedi` indicato.

    Con `domenica` è la sera dell'ultimo giorno della settimana stessa; con
    `lunedi` è il giorno dopo, cioè il lunedì successivo — in entrambi i casi
    la settimana è finita quando la si riepiloga.
    """
    scarto = 6 if giorno == "domenica" else 7
    return datetime.combine(lunedi + timedelta(days=scarto), time(hour=ore, minute=minuti))


def settimana_dovuta(adesso: datetime, *, giorno: str, ore: int, minuti: int) -> date | None:
    """Il lunedì della settimana da riepilogare adesso, o None se non è ora.

    Si guarda indietro di due settimane invece di controllare solo «è oggi il
    giorno giusto?»: se il Pi era spento all'ora prevista, il job deve partire
    appena torna acceso invece di saltare la settimana. Due e non di più perché
    dopo un'assenza lunga ha senso riprendere dall'ultima settimana, non
    rovesciare addosso quattro revisioni tutte insieme.
    """
    lunedi = inizio_settimana(adesso.date())
    for candidato in (lunedi, lunedi - timedelta(days=7)):
        if adesso >= momento_previsto(candidato, giorno, ore, minuti):
            return candidato
    return None


# — registro delle esecuzioni —


def gia_eseguito(conn: sqlite3.Connection, nome: str, chiave: date) -> bool:
    riga = conn.execute(
        "SELECT 1 FROM job_runs WHERE nome = ? AND chiave = ?", (nome, chiave.isoformat())
    ).fetchone()
    return riga is not None


def segna_eseguito(conn: sqlite3.Connection, nome: str, chiave: date, ora: datetime) -> None:
    """Registra che il job è stato fatto per quel periodo.

    Si segna anche quando il job non ha prodotto niente (una settimana senza
    voci approvate): senza, il worker ci riproverebbe ad ogni giro per sempre.
    """
    conn.execute(
        "INSERT OR IGNORE INTO job_runs (nome, chiave, eseguito_il) VALUES (?, ?, ?)",
        (nome, chiave.isoformat(), ora.isoformat(timespec="seconds")),
    )
