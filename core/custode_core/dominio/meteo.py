"""Le due domande che il meteo fa al database (§8.12), uguali per dashboard e bot.

Il testo e la chiamata a Open-Meteo stanno in `custode_meteo`; qui solo ciò che
si legge da SQLite. `core` non importa gli adattatori (come per il calendario):
chi compone la risposta — la rotta dell'API, il comando del bot — mette insieme
i due pezzi.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import posizione as dom_posizione
from custode_core.formato import etichetta_da_quando, etichetta_ora

DOPO_QUANTE_ORE_E_VECCHIA = 48
"""Oltre due giorni la posizione resta quella che usiamo, ma chi risponde lo
dice: potresti essere altrove."""


def punto(
    conn: sqlite3.Connection, casa: tuple[float, float] | None, ora: datetime
) -> tuple[float, float, str | None] | None:
    """Dove chiedere il meteo, e cosa dire sul posto se non è «dove sei».

    La posizione salvata vince sulla casa del `.env`. L'etichetta è `None` quando
    la posizione è fresca: è dove sei, non serve dirlo. Le altre due dicono di
    che posto parla il meteo, perché potrebbe non essere il tuo. `None` se non
    so dove sei: chi risponde lo dice invece di indovinare.
    """
    salvata = dom_posizione.leggi(conn)
    if salvata is None:
        if casa is None:
            return None
        return casa[0], casa[1], "casa"
    etichetta = None
    if salvata.eta(ora) > DOPO_QUANTE_ORE_E_VECCHIA:
        etichetta = f"ultima posizione: {etichetta_da_quando(salvata.aggiornata_il, ora)}"
    return salvata.lat, salvata.lon, etichetta


def prossimo_impegno(conn: sqlite3.Connection, ora: datetime) -> tuple[str, str] | None:
    """(ora, titolo) del prossimo impegno di oggi che ha un orario, se c'è.

    Quelli di giornata non contano: «porta l'ombrello» ha senso per qualcosa
    a cui si arriva a una certa ora.
    """
    return next(
        (
            (etichetta_ora(e.inizio), e.titolo)
            for e in dom_calendario.del_giorno(conn, ora.date())
            if not e.tutto_il_giorno and e.inizio >= ora
        ),
        None,
    )
