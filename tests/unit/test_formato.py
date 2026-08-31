"""Etichette in italiano: sono ciò che l'utente legge, quindi vanno fissate."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from custode_core.formato import (
    etichetta_data_lunga,
    etichetta_data_ora,
    etichetta_giorno,
    etichetta_ora,
    etichetta_scadenza,
    inizio_settimana,
    plurale,
)

# Lunedì 31 agosto 2026, 08:41.
ORA = datetime(2026, 8, 31, 8, 41)
OGGI = ORA.date()


@pytest.mark.parametrize(
    ("giorno", "atteso"),
    [
        (date(2026, 8, 31), "oggi"),
        (date(2026, 9, 1), "domani"),
        (date(2026, 8, 30), "ieri"),
        (date(2026, 9, 3), "giovedì"),  # entro la settimana: il nome del giorno
        (date(2026, 9, 6), "domenica"),
        (date(2026, 9, 7), "7 set"),  # oltre i sei giorni: la data
        (date(2026, 8, 26), "26 ago"),  # nel passato
        (date(2027, 1, 4), "4 gen 2027"),  # altro anno: l'anno è necessario
    ],
)
def test_etichetta_giorno(giorno: date, atteso: str) -> None:
    assert etichetta_giorno(giorno, OGGI) == atteso


def test_scadenza_di_oggi_mostra_solo_l_ora() -> None:
    # "oggi 18:00" sarebbe ridondante in una pagina che parla di oggi.
    assert etichetta_scadenza(datetime(2026, 8, 31, 18, 0), ORA) == "18:00"


def test_scadenza_con_ora_in_un_altro_giorno() -> None:
    assert etichetta_scadenza(datetime(2026, 9, 1, 18, 0), ORA) == "domani 18:00"


def test_scadenza_per_tutto_il_giorno() -> None:
    assert etichetta_scadenza(date(2026, 9, 3), ORA) == "giovedì"


def test_senza_scadenza() -> None:
    assert etichetta_scadenza(None, ORA) is None


def test_intestazioni() -> None:
    assert etichetta_data_lunga(ORA) == "lunedì 31 agosto"
    assert etichetta_data_ora(ORA) == "lunedì 31 agosto, 08:41"
    assert etichetta_ora(ORA) == "08:41"


def test_plurale() -> None:
    assert plurale(1, "voce", "voci") == "1 voce"
    assert plurale(3, "voce", "voci") == "3 voci"
    assert plurale(0, "voce", "voci") == "0 voci"


@pytest.mark.parametrize(
    ("giorno", "atteso"),
    [
        (date(2026, 8, 31), date(2026, 8, 31)),  # è già lunedì
        (date(2026, 9, 6), date(2026, 8, 31)),  # domenica -> lunedì precedente
        (date(2026, 9, 7), date(2026, 9, 7)),
    ],
)
def test_inizio_settimana(giorno: date, atteso: date) -> None:
    assert inizio_settimana(giorno) == atteso
