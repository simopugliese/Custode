"""Task e promemoria (ARCHITECTURE.md §8.2)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

Origine = Literal["dashboard", "telegram", "piano_ripasso", "regola"]

ETICHETTE_ORIGINE: dict[str, str] = {
    "dashboard": "Dashboard",
    "telegram": "Telegram",
    "piano_ripasso": "Piano di ripasso",
    "regola": "Regola di contesto",
}


class TaskInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessun task."""


@dataclass(frozen=True)
class Task:
    id: int
    titolo: str
    note: str | None
    # `date` = scadenza per tutto il giorno, `datetime` = a un'ora precisa.
    scadenza: date | datetime | None
    fatto: bool
    origine: str
    rinvii: int
    creato_il: datetime
    completato_il: datetime | None

    @property
    def scadenza_giorno(self) -> date | None:
        if self.scadenza is None:
            return None
        return self.scadenza.date() if isinstance(self.scadenza, datetime) else self.scadenza


def leggi_scadenza(testo: str | None) -> date | datetime | None:
    """Interpreta il campo `scadenza` come scritto sul database.

    Dieci caratteri (`YYYY-MM-DD`) significano "per tutto il giorno"; una forma
    più lunga (`YYYY-MM-DDTHH:MM[:SS]`) significa un'ora precisa.
    """
    if not testo:
        return None
    if len(testo) == 10:
        return date.fromisoformat(testo)
    return datetime.fromisoformat(testo)


def scrivi_scadenza(scadenza: date | datetime | None) -> str | None:
    if scadenza is None:
        return None
    if isinstance(scadenza, datetime):
        return scadenza.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    return scadenza.isoformat()


def _da_riga(riga: sqlite3.Row) -> Task:
    return Task(
        id=riga["id"],
        titolo=riga["titolo"],
        note=riga["note"],
        scadenza=leggi_scadenza(riga["scadenza"]),
        fatto=riga["stato"] == "fatto",
        origine=riga["origine"],
        rinvii=riga["rinvii"],
        creato_il=datetime.fromisoformat(riga["creato_il"]),
        completato_il=(
            datetime.fromisoformat(riga["completato_il"]) if riga["completato_il"] else None
        ),
    )


def elenco(conn: sqlite3.Connection, *, fatto: bool | None = None) -> list[Task]:
    """Tutti i task, o solo quelli aperti/chiusi.

    Ordine: prima chi ha una scadenza, dalla più vicina; poi chi non ce l'ha,
    dal più recente — lo stesso ordine in cui li si vuole vedere in una lista.
    """
    sql = "SELECT * FROM tasks" " {dove}" " ORDER BY scadenza IS NULL, scadenza ASC, creato_il DESC"
    dove = ""
    parametri: tuple[str, ...] = ()
    if fatto is not None:
        dove = "WHERE stato = ?"
        parametri = ("fatto" if fatto else "aperto",)
    return [_da_riga(r) for r in conn.execute(sql.format(dove=dove), parametri)]


def leggi(conn: sqlite3.Connection, task_id: int) -> Task:
    riga = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if riga is None:
        raise TaskInesistente(task_id)
    return _da_riga(riga)


def crea(
    conn: sqlite3.Connection,
    *,
    titolo: str,
    ora: datetime,
    scadenza: date | datetime | None = None,
    note: str | None = None,
    origine: Origine = "dashboard",
) -> Task:
    cursore = conn.execute(
        "INSERT INTO tasks (titolo, note, scadenza, stato, origine, rinvii, creato_il)"
        " VALUES (?, ?, ?, 'aperto', ?, 0, ?)",
        (
            titolo.strip(),
            note,
            scrivi_scadenza(scadenza),
            origine,
            ora.isoformat(timespec="seconds"),
        ),
    )
    return leggi(conn, int(cursore.lastrowid or 0))


def imposta_fatto(conn: sqlite3.Connection, task_id: int, fatto: bool, ora: datetime) -> Task:
    """Segna un task come fatto o lo riapre.

    `completato_il` serve al conteggio "chiusi questa settimana": riaprendo un
    task va azzerato, altrimenti continuerebbe a contare come chiuso.
    """
    leggi(conn, task_id)  # solleva TaskInesistente prima di scrivere
    conn.execute(
        "UPDATE tasks SET stato = ?, completato_il = ? WHERE id = ?",
        (
            "fatto" if fatto else "aperto",
            ora.isoformat(timespec="seconds") if fatto else None,
            task_id,
        ),
    )
    return leggi(conn, task_id)


def rinvia(conn: sqlite3.Connection, task_id: int, giorni: int, ora: datetime) -> Task:
    """Sposta la scadenza in avanti di `giorni` e incrementa il contatore.

    Un task senza scadenza ne riceve una a partire da oggi: rinviare qualcosa
    che non era in scadenza significa comunque "rivedilo fra N giorni".
    """
    if giorni < 1:
        raise ValueError("i giorni di rinvio devono essere almeno 1")

    task = leggi(conn, task_id)
    delta = timedelta(days=giorni)
    if task.scadenza is None:
        nuova: date | datetime = ora.date() + delta
    else:
        nuova = task.scadenza + delta

    conn.execute(
        "UPDATE tasks SET scadenza = ?, rinvii = rinvii + 1 WHERE id = ?",
        (scrivi_scadenza(nuova), task_id),
    )
    return leggi(conn, task_id)


def elimina(conn: sqlite3.Connection, task_id: int) -> None:
    """Cancella un task. Serve ad annullare una creazione appena fatta."""
    leggi(conn, task_id)  # solleva TaskInesistente se non c'è
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def annulla_rinvio(conn: sqlite3.Connection, task_id: int, giorni: int) -> Task:
    """Riporta indietro la scadenza e scala il contatore dei rinvii.

    Non è `rinvia` con giorni negativi: quella incrementerebbe il contatore, e
    un rinvio annullato non deve restare scritto nella storia del task.
    """
    task = leggi(conn, task_id)
    nuova = task.scadenza - timedelta(days=giorni) if task.scadenza is not None else None
    conn.execute(
        "UPDATE tasks SET scadenza = ?, rinvii = max(rinvii - 1, 0) WHERE id = ?",
        (scrivi_scadenza(nuova), task_id),
    )
    return leggi(conn, task_id)


def chiusi_per_giorno(conn: sqlite3.Connection, lunedi: date) -> list[int]:
    """Quanti task chiusi in ciascuno dei 7 giorni a partire da `lunedi`."""
    conteggi = [0] * 7
    righe = conn.execute(
        "SELECT date(completato_il) AS giorno, count(*) AS n FROM tasks"
        " WHERE completato_il IS NOT NULL AND date(completato_il) BETWEEN ? AND ?"
        " GROUP BY giorno",
        (lunedi.isoformat(), (lunedi + timedelta(days=6)).isoformat()),
    )
    for riga in righe:
        indice = (date.fromisoformat(riga["giorno"]) - lunedi).days
        if 0 <= indice < 7:
            conteggi[indice] = riga["n"]
    return conteggi


def conteggio_per_origine(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Task aperti raggruppati per provenienza, dal più frequente."""
    righe = conn.execute(
        "SELECT origine, count(*) AS n FROM tasks WHERE stato = 'aperto'"
        " GROUP BY origine ORDER BY n DESC, origine ASC"
    )
    return [(ETICHETTE_ORIGINE.get(r["origine"], r["origine"]), r["n"]) for r in righe]


def in_ritardo(task: Task, oggi: date) -> bool:
    giorno = task.scadenza_giorno
    return not task.fatto and giorno is not None and giorno < oggi


def per_oggi(task: Task, oggi: date) -> bool:
    return not task.fatto and task.scadenza_giorno == oggi


def entro_giorni(task: Task, oggi: date, giorni: int) -> bool:
    giorno = task.scadenza_giorno
    if task.fatto or giorno is None:
        return False
    return oggi < giorno <= oggi + timedelta(days=giorni)


def conta_aperti(task: Sequence[Task]) -> int:
    return sum(1 for t in task if not t.fatto)
