"""Lista della spesa (ARCHITECTURE.md §8.3)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

REPARTO_PREDEFINITO = "Altro"


class VoceInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessuna voce."""


@dataclass(frozen=True)
class Voce:
    id: int
    nome: str
    quantita: str | None
    reparto: str
    preso: bool
    aggiunto_il: datetime
    comprato_il: datetime | None


def _da_riga(riga: sqlite3.Row) -> Voce:
    return Voce(
        id=riga["id"],
        nome=riga["item"],
        quantita=riga["quantita"],
        reparto=riga["reparto"],
        preso=bool(riga["comprato"]),
        aggiunto_il=datetime.fromisoformat(riga["aggiunto_il"]),
        comprato_il=(datetime.fromisoformat(riga["comprato_il"]) if riga["comprato_il"] else None),
    )


def elenco(conn: sqlite3.Connection, *, preso: bool | None = None) -> list[Voce]:
    """Voci della lista, dalla più vecchia alla più recente."""
    sql = "SELECT * FROM shopping_list {dove} ORDER BY aggiunto_il ASC, id ASC"
    dove = ""
    parametri: tuple[int, ...] = ()
    if preso is not None:
        dove = "WHERE comprato = ?"
        parametri = (1 if preso else 0,)
    return [_da_riga(r) for r in conn.execute(sql.format(dove=dove), parametri)]


def leggi(conn: sqlite3.Connection, voce_id: int) -> Voce:
    riga = conn.execute("SELECT * FROM shopping_list WHERE id = ?", (voce_id,)).fetchone()
    if riga is None:
        raise VoceInesistente(voce_id)
    return _da_riga(riga)


def aggiungi(
    conn: sqlite3.Connection,
    *,
    nome: str,
    ora: datetime,
    quantita: str | None = None,
    reparto: str | None = None,
) -> Voce:
    """Aggiunge una voce da prendere.

    Se una voce con lo stesso nome è già in lista e non è stata presa, non se ne
    crea una seconda: "sto finendo il latte" detto due volte non deve produrre
    due righe "latte" (§8.3).
    """
    nome_pulito = nome.strip()
    if not nome_pulito:
        raise ValueError("il nome della voce non può essere vuoto")

    esistente = conn.execute(
        "SELECT * FROM shopping_list WHERE comprato = 0 AND lower(item) = lower(?)",
        (nome_pulito,),
    ).fetchone()
    if esistente is not None:
        return _da_riga(esistente)

    cursore = conn.execute(
        "INSERT INTO shopping_list (item, quantita, reparto, comprato, aggiunto_il)"
        " VALUES (?, ?, ?, 0, ?)",
        (
            nome_pulito,
            quantita,
            (reparto or REPARTO_PREDEFINITO).strip() or REPARTO_PREDEFINITO,
            ora.isoformat(timespec="seconds"),
        ),
    )
    return leggi(conn, int(cursore.lastrowid or 0))


def imposta_preso(conn: sqlite3.Connection, voce_id: int, preso: bool, ora: datetime) -> Voce:
    leggi(conn, voce_id)  # solleva VoceInesistente prima di scrivere
    conn.execute(
        "UPDATE shopping_list SET comprato = ?, comprato_il = ? WHERE id = ?",
        (1 if preso else 0, ora.isoformat(timespec="seconds") if preso else None, voce_id),
    )
    return leggi(conn, voce_id)


def elimina(conn: sqlite3.Connection, voce_id: int) -> None:
    """Cancella una voce. Serve ad annullare un'aggiunta appena fatta."""
    leggi(conn, voce_id)  # solleva VoceInesistente se non c'è
    conn.execute("DELETE FROM shopping_list WHERE id = ?", (voce_id,))


def svuota_presi(conn: sqlite3.Connection) -> int:
    """Rimuove le voci già prese. Ritorna quante ne ha tolte."""
    cursore = conn.execute("DELETE FROM shopping_list WHERE comprato = 1")
    return cursore.rowcount


def per_reparto(voci: list[Voce]) -> list[tuple[str, list[Voce]]]:
    """Raggruppa per reparto, reparti in ordine alfabetico con 'Altro' in fondo."""
    gruppi: dict[str, list[Voce]] = {}
    for voce in voci:
        gruppi.setdefault(voce.reparto, []).append(voce)
    return sorted(
        gruppi.items(),
        key=lambda coppia: (coppia[0] == REPARTO_PREDEFINITO, coppia[0].lower()),
    )
