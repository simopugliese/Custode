"""Dove sei, l'ultima volta che l'hai detto (§8.12).

Una riga sola (migrazione 013): la posizione serve per il meteo di adesso e per
il digest del mattino, che gira sul Pi senza nessun browser aperto. Di dove sei
stato ieri non c'è niente da ricordare.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

DECIMALI = 2
"""Circa un chilometro. Lo fa già il browser prima di mandarla; ripeterlo qui
vuol dire che un client diverso non può salvare la via di casa."""


class PosizioneNonValida(ValueError):
    """Coordinate fuori dal globo."""


@dataclass(frozen=True)
class Posizione:
    lat: float
    lon: float
    aggiornata_il: datetime

    def eta(self, ora: datetime) -> float:
        """Da quante ore l'hai detta."""
        return max(0.0, (ora - self.aggiornata_il).total_seconds() / 3600)


def salva(conn: sqlite3.Connection, lat: float, lon: float, ora: datetime) -> Posizione:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise PosizioneNonValida(f"coordinate fuori intervallo: {lat}, {lon}")
    pulita = Posizione(round(lat, DECIMALI), round(lon, DECIMALI), ora)
    conn.execute(
        "INSERT INTO posizione (id, lat, lon, aggiornata_il) VALUES (1, ?, ?, ?)"
        " ON CONFLICT (id) DO UPDATE SET lat = excluded.lat, lon = excluded.lon,"
        " aggiornata_il = excluded.aggiornata_il",
        (pulita.lat, pulita.lon, ora.isoformat(timespec="seconds")),
    )
    return pulita


def leggi(conn: sqlite3.Connection) -> Posizione | None:
    riga = conn.execute("SELECT lat, lon, aggiornata_il FROM posizione WHERE id = 1").fetchone()
    if riga is None:
        return None
    return Posizione(riga["lat"], riga["lon"], datetime.fromisoformat(riga["aggiornata_il"]))
