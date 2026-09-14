"""Il registro di cosa i job hanno già fatto (`job_runs`, §5).

Serve perché un job può legittimamente non produrre niente — una settimana
senza voci approvate non scrive nessuna riga — e senza registro ripartirebbe ad
ogni giro. Le chiavi hanno tre forme (un giorno, una fascia oraria, niente) e i
test che contano sono quelli che le vedono convivere senza pestarsi.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from custode_core import registro_job as registro

LUNEDI = date(2026, 8, 31)


def test_un_job_fatto_non_si_rifa(conn: sqlite3.Connection, ora: datetime) -> None:
    nome = registro.RIEPILOGO_SETTIMANALE
    assert registro.gia_eseguito(conn, nome, LUNEDI) is False

    registro.segna_eseguito(conn, nome, LUNEDI, ora)

    assert registro.gia_eseguito(conn, nome, LUNEDI) is True
    # Un'altra settimana è un'altra cosa.
    assert registro.gia_eseguito(conn, nome, LUNEDI - timedelta(days=7)) is False


def test_segnarlo_due_volte_non_esplode(conn: sqlite3.Connection, ora: datetime) -> None:
    """Capita se il worker riparte nel mezzo: la chiave è unica, non deve alzare."""
    nome = registro.RIEPILOGO_SETTIMANALE
    registro.segna_eseguito(conn, nome, LUNEDI, ora)
    registro.segna_eseguito(conn, nome, LUNEDI, ora)

    quante = conn.execute("SELECT count(*) AS n FROM job_runs").fetchone()["n"]
    assert quante == 1


def test_una_fascia_e_un_giorno_non_si_confondono_nel_registro(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Chiavi di forma diversa nella stessa tabella, senza pestarsi."""
    fascia = datetime(2026, 9, 14, 10, 15)
    registro.segna_eseguito(conn, "un_job", fascia, ora)

    assert registro.gia_eseguito(conn, "un_job", fascia) is True
    assert registro.gia_eseguito(conn, "un_job", fascia.date()) is False
    assert registro.gia_eseguito(conn, "un_job", datetime(2026, 9, 14, 10, 30)) is False


def test_i_secondi_non_fanno_una_fascia_nuova(conn: sqlite3.Connection, ora: datetime) -> None:
    """La chiave si scrive al minuto: altrimenti sarebbe diversa ad ogni giro."""
    registro.segna_eseguito(conn, "un_job", datetime(2026, 9, 14, 10, 15), ora)
    assert registro.gia_eseguito(conn, "un_job", datetime(2026, 9, 14, 10, 15, 42)) is True


# — le cose senza periodo, e la potatura —


def test_una_segnalazione_senza_periodo_si_mette_e_si_toglie(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """«Ti ho già avvisato» vale finché non si ripara, non per un periodo."""
    nome = "avviso_qualcosa"
    assert registro.gia_eseguito(conn, nome, registro.SENZA_PERIODO) is False

    registro.segna_eseguito(conn, nome, registro.SENZA_PERIODO, ora)
    assert registro.gia_eseguito(conn, nome, registro.SENZA_PERIODO) is True

    registro.dimentica(conn, nome, registro.SENZA_PERIODO)
    assert registro.gia_eseguito(conn, nome, registro.SENZA_PERIODO) is False


def test_la_potatura_tiene_la_finestra_e_butta_il_resto(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Senza, un job a fascia lascerebbe trentacinquemila righe all'anno."""
    base = datetime(2026, 9, 14, 12, 0)
    for scarto in range(0, 60 * 48, 15):  # due giorni di fasce da un quarto d'ora
        registro.segna_eseguito(conn, "a_fascia", base - timedelta(minutes=scarto), ora)
    prima = conn.execute("SELECT count(*) AS n FROM job_runs").fetchone()["n"]

    tolte = registro.dimentica_prima_di(conn, "a_fascia", base - timedelta(days=1))

    rimaste = conn.execute("SELECT count(*) AS n FROM job_runs").fetchone()["n"]
    assert prima == 192
    # «Prima di» è stretto: la fascia esattamente sul limite resta, quindi il
    # giorno tenuto è di novantasette fasce e non di novantasei.
    assert tolte == 95
    assert rimaste == 97
    # La fascia corrente non si pota mai: sarebbe il modo di rifare subito il
    # lavoro appena fatto.
    assert registro.gia_eseguito(conn, "a_fascia", base) is True


def test_la_potatura_non_tocca_gli_altri_job(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il riepilogo settimanale deve restare per sempre: cinquantadue righe all'anno."""
    vecchio_lunedi = date(2020, 1, 6)
    registro.segna_eseguito(conn, registro.RIEPILOGO_SETTIMANALE, vecchio_lunedi, ora)

    registro.dimentica_prima_di(conn, registro.SYNC_CALENDARIO, datetime(2026, 9, 14, 12, 0))

    assert registro.gia_eseguito(conn, registro.RIEPILOGO_SETTIMANALE, vecchio_lunedi) is True
