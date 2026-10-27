"""La posizione (§8.12): una riga sola, già approssimata."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from custode_core.dominio import posizione

ADESSO = datetime(2026, 8, 31, 8, 41)


def test_senza_posizione_non_c_e_nulla(conn: sqlite3.Connection) -> None:
    assert posizione.leggi(conn) is None


def test_salva_arrotonda_e_la_seconda_sostituisce_la_prima(conn: sqlite3.Connection) -> None:
    posizione.salva(conn, 45.070312, 7.686864, ADESSO)
    posizione.salva(conn, 41.9028, 12.4964, ADESSO + timedelta(hours=5))

    attuale = posizione.leggi(conn)
    assert attuale == posizione.Posizione(41.9, 12.5, ADESSO + timedelta(hours=5))
    assert conn.execute("SELECT COUNT(*) FROM posizione").fetchone()[0] == 1


def test_coordinate_fuori_dal_globo_si_rifiutano(conn: sqlite3.Connection) -> None:
    with pytest.raises(posizione.PosizioneNonValida):
        posizione.salva(conn, 91, 0, ADESSO)
    assert posizione.leggi(conn) is None


def test_l_eta_in_ore() -> None:
    p = posizione.Posizione(45.0, 7.0, ADESSO)
    assert p.eta(ADESSO + timedelta(hours=3, minutes=30)) == 3.5
    assert p.eta(ADESSO - timedelta(hours=1)) == 0.0
