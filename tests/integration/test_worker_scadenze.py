"""Gli avvisi di scadenza dei task (§8.2).

La regola che questi test difendono è quella che si scoprirebbe solo a furia di
messaggi doppi: **una scadenza si avvisa una volta sola**, e un invio fallito
non conta come avviso.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from custode_bot.risposte import Risposta
from custode_core.dominio import task as dom_task
from custode_core.registro_job import SCADENZE_TASK
from custode_worker import scadenze
from custode_worker.telegram import InvioNonRiuscito

pytestmark = pytest.mark.integration

SERA = datetime(2026, 9, 7, 20, 0)
CREATO = datetime(2026, 9, 1, 9, 0)


class TelegramFinto:
    def __init__(self, errore: Exception | None = None) -> None:
        self.errore = errore
        self.mandati: list[Risposta] = []

    def manda(self, risposta: Risposta) -> None:
        if self.errore is not None:
            raise self.errore
        self.mandati.append(risposta)


def _giro(conn: sqlite3.Connection, quando: datetime, telegram: TelegramFinto) -> scadenze.Esito:
    return scadenze.esegui(conn, quando, ore=20, minuti=0, telegram=telegram)


def _task(conn: sqlite3.Connection, titolo: str, scadenza: date | datetime) -> dom_task.Task:
    return dom_task.crea(conn, titolo=titolo, ora=CREATO, scadenza=scadenza)


def test_avvisa_una_volta_sola(conn: sqlite3.Connection) -> None:
    _task(conn, "Bolletta", date(2026, 9, 7))
    telegram = TelegramFinto()

    primo = _giro(conn, SERA, telegram)
    secondo = _giro(conn, SERA + timedelta(minutes=5), telegram)

    assert (primo.avvisate, secondo.avvisate, secondo.gia_fatte) == (1, 0, 1)
    assert len(telegram.mandati) == 1
    assert "Bolletta" in telegram.mandati[0].testo


def test_piu_task_nello_stesso_giro_sono_un_messaggio_solo(conn: sqlite3.Connection) -> None:
    _task(conn, "Bolletta", date(2026, 9, 7))
    _task(conn, "Officina", datetime(2026, 9, 7, 18, 0))
    telegram = TelegramFinto()

    _giro(conn, SERA, telegram)

    (messaggio,) = telegram.mandati
    assert "Bolletta" in messaggio.testo and "Officina" in messaggio.testo
    assert len(messaggio.bottoni) == 2


def test_rinviare_il_task_permette_di_riavvisare_per_la_nuova_scadenza(
    conn: sqlite3.Connection,
) -> None:
    task = _task(conn, "Bolletta", date(2026, 9, 7))
    telegram = TelegramFinto()
    _giro(conn, SERA, telegram)

    dom_task.rinvia(conn, task.id, 1, SERA)
    _giro(conn, SERA + timedelta(days=1), telegram)

    assert len(telegram.mandati) == 2


def test_un_invio_fallito_non_segna_e_si_riprova(conn: sqlite3.Connection) -> None:
    _task(conn, "Bolletta", date(2026, 9, 7))

    rotto = _giro(conn, SERA, TelegramFinto(InvioNonRiuscito("rete")))
    buono = TelegramFinto()
    riuscito = _giro(conn, SERA + timedelta(minutes=5), buono)

    assert rotto.non_spedite == 1 and rotto.avvisate == 0
    assert riuscito.avvisate == 1
    assert len(buono.mandati) == 1


def test_un_task_segnato_fatto_prima_del_controllo_non_avvisa(conn: sqlite3.Connection) -> None:
    task = _task(conn, "Bolletta", date(2026, 9, 7))
    dom_task.imposta_fatto(conn, task.id, True, SERA - timedelta(hours=2))
    telegram = TelegramFinto()

    _giro(conn, SERA, telegram)

    assert telegram.mandati == []


def test_le_righe_vecchie_si_potano(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO job_runs (nome, chiave, eseguito_il) VALUES (?, '2026-01-01#9', 'x')",
        (SCADENZE_TASK,),
    )
    _giro(conn, SERA, TelegramFinto())
    quante = conn.execute("SELECT count(*) AS n FROM job_runs").fetchone()["n"]
    assert quante == 0
