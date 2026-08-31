"""Regole di dominio dei task: valgono identiche per dashboard e bot (§8.2)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from custode_core.dominio import task as dom


def test_crea_e_rileggi(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom.crea(conn, titolo="  Chiamare l'officina  ", ora=ora)
    assert task.titolo == "Chiamare l'officina"  # gli spazi ai bordi si perdono
    assert task.fatto is False
    assert task.rinvii == 0
    assert task.origine == "dashboard"
    assert dom.leggi(conn, task.id) == task


def test_task_inesistente(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.TaskInesistente):
        dom.leggi(conn, 999)


def test_scadenza_per_tutto_il_giorno_e_a_un_ora(conn: sqlite3.Connection, ora: datetime) -> None:
    giorno = dom.crea(conn, titolo="bolletta", ora=ora, scadenza=date(2026, 9, 4))
    preciso = dom.crea(conn, titolo="officina", ora=ora, scadenza=datetime(2026, 9, 4, 18, 0))
    assert dom.leggi(conn, giorno.id).scadenza == date(2026, 9, 4)
    assert dom.leggi(conn, preciso.id).scadenza == datetime(2026, 9, 4, 18, 0)


def test_segna_fatto_e_riapri(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom.crea(conn, titolo="paper", ora=ora)

    fatto = dom.imposta_fatto(conn, task.id, True, ora)
    assert fatto.fatto is True
    assert fatto.completato_il is not None

    # Riaprendo, `completato_il` va azzerato: altrimenti continuerebbe a
    # contare fra i "chiusi questa settimana".
    riaperto = dom.imposta_fatto(conn, task.id, False, ora)
    assert riaperto.fatto is False
    assert riaperto.completato_il is None


def test_rinvia_sposta_la_scadenza_e_conta(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom.crea(conn, titolo="bolletta", ora=ora, scadenza=date(2026, 8, 28))

    dopo = dom.rinvia(conn, task.id, 2, ora)
    assert dopo.scadenza == date(2026, 8, 30)
    assert dopo.rinvii == 1

    ancora = dom.rinvia(conn, task.id, 1, ora)
    assert ancora.scadenza == date(2026, 8, 31)
    assert ancora.rinvii == 2


def test_rinvia_un_task_senza_scadenza_gliene_da_una(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    task = dom.crea(conn, titolo="paper", ora=ora)
    dopo = dom.rinvia(conn, task.id, 3, ora)
    assert dopo.scadenza == ora.date() + timedelta(days=3)


def test_rinvia_conserva_l_ora(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom.crea(conn, titolo="officina", ora=ora, scadenza=datetime(2026, 8, 31, 18, 0))
    assert dom.rinvia(conn, task.id, 1, ora).scadenza == datetime(2026, 9, 1, 18, 0)


def test_rinvio_non_positivo_rifiutato(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom.crea(conn, titolo="x", ora=ora)
    with pytest.raises(ValueError):
        dom.rinvia(conn, task.id, 0, ora)


def test_classificazione_per_scadenza(conn: sqlite3.Connection, ora: datetime) -> None:
    oggi = ora.date()
    scaduto = dom.crea(conn, titolo="scaduto", ora=ora, scadenza=oggi - timedelta(days=1))
    di_oggi = dom.crea(conn, titolo="oggi", ora=ora, scadenza=oggi)
    fra_tre = dom.crea(conn, titolo="fra tre", ora=ora, scadenza=oggi + timedelta(days=3))
    lontano = dom.crea(conn, titolo="lontano", ora=ora, scadenza=oggi + timedelta(days=30))

    assert dom.in_ritardo(scaduto, oggi) is True
    assert dom.in_ritardo(di_oggi, oggi) is False  # oggi non è ancora in ritardo
    assert dom.per_oggi(di_oggi, oggi) is True
    assert dom.entro_giorni(fra_tre, oggi, 7) is True
    assert dom.entro_giorni(di_oggi, oggi, 7) is False  # oggi ha già la sua sezione
    assert dom.entro_giorni(lontano, oggi, 7) is False


def test_un_task_chiuso_non_e_mai_in_ritardo(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom.crea(conn, titolo="fatto", ora=ora, scadenza=ora.date() - timedelta(days=5))
    chiuso = dom.imposta_fatto(conn, task.id, True, ora)
    assert dom.in_ritardo(chiuso, ora.date()) is False


def test_chiusi_per_giorno(conn: sqlite3.Connection, ora: datetime) -> None:
    lunedi = ora.date()  # il 31 agosto 2026 è lunedì
    for giorno, quanti in ((lunedi, 2), (lunedi + timedelta(days=2), 1)):
        for n in range(quanti):
            task = dom.crea(conn, titolo=f"{giorno} {n}", ora=ora)
            dom.imposta_fatto(conn, task.id, True, datetime.combine(giorno, ora.time()))

    assert dom.chiusi_per_giorno(conn, lunedi) == [2, 0, 1, 0, 0, 0, 0]


def test_conteggio_per_origine_solo_sugli_aperti(conn: sqlite3.Connection, ora: datetime) -> None:
    dom.crea(conn, titolo="a", ora=ora, origine="telegram")
    dom.crea(conn, titolo="b", ora=ora, origine="telegram")
    chiuso = dom.crea(conn, titolo="c", ora=ora, origine="dashboard")
    dom.imposta_fatto(conn, chiuso.id, True, ora)

    assert dom.conteggio_per_origine(conn) == [("Telegram", 2)]
