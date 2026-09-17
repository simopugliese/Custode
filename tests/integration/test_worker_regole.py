"""Il job che fa scattare le regole di contesto (§8.10).

Il dominio prova *quando* una regola è dovuta, e lo fa senza database. Qui si
prova quello che il dominio non può sapere: che il promemoria parta davvero,
che **non parta due volte** se il worker ripassa nella stessa finestra, e che un
invio fallito non venga segnato come fatto — la regola che tutto il worker
difende da quando esiste il riepilogo settimanale.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custode_bot.risposte import Risposta
from custode_core.db import connessione
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import regole as dom
from custode_core.migrazioni import migra
from custode_core.registro_job import conteggi_da, gia_eseguito
from custode_worker import regole as job
from custode_worker.telegram import InvioNonRiuscito

pytestmark = pytest.mark.integration

# Un mercoledì alle 19:00 in punto.
ORA = datetime(2026, 9, 16, 19, 0)


class TelegramFinto:
    def __init__(self, errore: Exception | None = None) -> None:
        self.errore = errore
        self.mandati: list[Risposta] = []

    def manda(self, risposta: Risposta) -> None:
        if self.errore is not None:
            raise self.errore
        self.mandati.append(risposta)


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    with connessione(db_path) as aperta:
        migra(aperta)
        yield aperta


class EventoFinto:
    """Un evento come lo consegna una sorgente, per riempire l'archivio.

    Passa da `dom_calendario.sincronizza` invece di scrivere la riga a mano: è
    la stessa strada che fa il worker, quindi il test esercita anche il tipo di
    default e il timbro di sincronizzazione invece di inventarli.
    """

    def __init__(self, id: str, inizio: datetime, minuti: int = 120) -> None:
        self.id = id
        self.titolo = "Analisi II"
        self.inizio = inizio
        self.fine = inizio + timedelta(minutes=minuti)
        self.tutto_il_giorno = False
        self.luogo = ""
        self.serie_id = ""


def _lezione(
    conn: sqlite3.Connection,
    inizio: datetime,
    tipo: str = "lezione",
    durata_minuti: int = 120,
) -> int:
    giorno = inizio.date()
    dom_calendario.sincronizza(
        conn, [EventoFinto("ev-1", inizio, durata_minuti)], da=giorno, a=giorno, ora=ORA
    )
    (evento,) = dom_calendario.del_giorno(conn, giorno)
    dom_calendario.correggi_tag(conn, evento.id, tipo, ORA)
    return evento.id


# — il caso normale —


def test_una_regola_a_orario_manda_il_promemoria(conn: sqlite3.Connection) -> None:
    dom.crea_a_orario(conn, ora="19:00", messaggio="prendi la creatina", creata_il=ORA)
    telegram = TelegramFinto()

    esito = job.esegui(conn, ORA, telegram=telegram)

    assert esito.scattate == 1
    (mandato,) = telegram.mandati
    assert "prendi la creatina" in mandato.testo
    # La riga che dice da dove arriva: senza, non si capisce quale regola
    # mettere in pausa se ha rotto le scatole.
    assert "tutti i giorni alle 19:00" in mandato.testo


def test_senza_regole_non_succede_niente(conn: sqlite3.Connection) -> None:
    telegram = TelegramFinto()

    esito = job.esegui(conn, ORA, telegram=telegram)

    assert esito == job.Esito()
    assert telegram.mandati == []


def test_una_regola_in_pausa_non_scatta(conn: sqlite3.Connection) -> None:
    regola = dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=ORA)
    dom.imposta_stato(conn, regola.id, dom.Stato.PAUSA)
    telegram = TelegramFinto()

    assert job.esegui(conn, ORA, telegram=telegram).scattate == 0
    assert telegram.mandati == []


# — non ripetersi, che è la ragione del registro —


def test_due_giri_nella_stessa_finestra_mandano_un_messaggio_solo(
    conn: sqlite3.Connection,
) -> None:
    """Un riavvio del worker fa ripassare dentro gli stessi cinque minuti: senza
    il registro, lo stesso promemoria arriverebbe due volte a due minuti."""
    dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=ORA)
    telegram = TelegramFinto()

    job.esegui(conn, ORA, telegram=telegram)
    esito = job.esegui(conn, ORA + timedelta(minutes=2), telegram=telegram)

    assert esito.scattate == 0
    assert esito.gia_fatte == 1
    assert len(telegram.mandati) == 1


def test_lo_scatto_si_segna_col_nome_della_sua_regola(conn: sqlite3.Connection) -> None:
    regola = dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=ORA)

    job.esegui(conn, ORA, telegram=TelegramFinto())

    assert gia_eseguito(conn, dom.nome_job(regola.id), "2026-09-16T19:00")
    assert conteggi_da(conn, "regola:", ORA - timedelta(days=7)) == {dom.nome_job(regola.id): 1}


# — quando Telegram non risponde —


def test_un_invio_fallito_non_si_segna_come_fatto(conn: sqlite3.Connection) -> None:
    """La regola che il worker difende da sempre: al giro dopo si riprova."""
    dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=ORA)

    esito = job.esegui(conn, ORA, telegram=TelegramFinto(InvioNonRiuscito("niente rete")))

    assert esito.non_spedite == 1
    assert esito.scattate == 0
    assert conteggi_da(conn, "regola:", ORA - timedelta(days=7)) == {}


def test_al_giro_dopo_si_riprova_finche_si_e_dentro_la_finestra(
    conn: sqlite3.Connection,
) -> None:
    dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=ORA)
    job.esegui(conn, ORA, telegram=TelegramFinto(InvioNonRiuscito("niente rete")))

    buono = TelegramFinto()
    esito = job.esegui(conn, ORA + timedelta(minutes=3), telegram=buono)

    assert esito.scattate == 1
    assert len(buono.mandati) == 1


def test_un_guasto_non_ferma_le_altre_regole(conn: sqlite3.Connection) -> None:
    """`esegui` non solleva: un'eccezione qui fermerebbe anche il backup."""
    dom.crea_a_orario(conn, ora="19:00", messaggio="prima", creata_il=ORA)
    dom.crea_a_orario(conn, ora="19:00", messaggio="seconda", creata_il=ORA)

    esito = job.esegui(conn, ORA, telegram=TelegramFinto(InvioNonRiuscito("niente rete")))

    assert esito.non_spedite == 2


# — agganciate al calendario —


def test_trenta_minuti_prima_di_una_lezione(conn: sqlite3.Connection) -> None:
    _lezione(conn, ORA + timedelta(minutes=30))
    dom.crea_da_evento(
        conn,
        trigger=dom.Trigger.PRIMA_EVENTO,
        tipo_evento="lezione",
        minuti=30,
        messaggio="porta il portatile",
        creata_il=ORA,
    )
    telegram = TelegramFinto()

    esito = job.esegui(conn, ORA, telegram=telegram)

    assert esito.scattate == 1
    assert "porta il portatile" in telegram.mandati[0].testo
    assert "30 minuti prima di un impegno di tipo «lezione»" in telegram.mandati[0].testo


def test_un_impegno_di_un_altro_tipo_non_la_fa_scattare(conn: sqlite3.Connection) -> None:
    _lezione(conn, ORA + timedelta(minutes=30), tipo="palestra")
    dom.crea_da_evento(
        conn,
        trigger=dom.Trigger.PRIMA_EVENTO,
        tipo_evento="lezione",
        minuti=30,
        messaggio="x",
        creata_il=ORA,
    )

    assert job.esegui(conn, ORA, telegram=TelegramFinto()).scattate == 0


def test_dopo_la_palestra(conn: sqlite3.Connection) -> None:
    """Un'ora di palestra finita adesso: «dopo» guarda la **fine**, non l'inizio."""
    _lezione(conn, ORA - timedelta(hours=1), tipo="palestra", durata_minuti=60)
    dom.crea_da_evento(
        conn,
        trigger=dom.Trigger.DOPO_EVENTO,
        tipo_evento="palestra",
        minuti=0,
        messaggio="bevi",
        creata_il=ORA,
    )

    assert job.esegui(conn, ORA, telegram=TelegramFinto()).scattate == 1


def test_una_regola_a_orario_non_fa_leggere_il_calendario(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chi ha solo promemoria a orario non deve pagare una query sul calendario
    ogni cinque minuti per sempre, per una risposta che nessuno guarda."""
    dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=ORA)

    def _esplodi(*_: object, **__: object) -> list[dom_calendario.Evento]:
        raise AssertionError("il calendario non andava letto")

    monkeypatch.setattr(dom_calendario, "fra", _esplodi)

    assert job.esegui(conn, ORA, telegram=TelegramFinto()).scattate == 1
