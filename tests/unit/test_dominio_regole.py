"""Le regole di contesto dettate da te (§8.10).

La parte che conta è `dovute()`: è pura, quindi «scatta alle 19» si prova in un
millesimo di secondo invece che aspettando le 19. Le due cose che si sbagliano
sono gli **estremi della finestra** — un promemoria mandato due volte o mai — e
lo **scavalco della mezzanotte**, che perde una regola serale una notte su due.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custode_core.db import connessione
from custode_core.dominio import regole as dom
from custode_core.migrazioni import migra
from custode_core.registro_job import conteggi_da, segna_eseguito

# Un mercoledì, per avere un giorno della settimana che non sia un estremo.
MERCOLEDI = datetime(2026, 9, 16, 19, 0)


def _regola(
    *,
    id: int = 1,
    trigger: dom.Trigger = dom.Trigger.ORARIO,
    ora: str | None = "19:00",
    giorni: tuple[int, ...] = dom.TUTTI_I_GIORNI,
    tipo_evento: str | None = None,
    minuti: int | None = None,
    stato: dom.Stato = dom.Stato.ATTIVA,
) -> dom.Regola:
    return dom.Regola(
        id=id,
        origine=dom.Origine.UTENTE,
        trigger=trigger,
        messaggio="prendi la creatina",
        stato=stato,
        creata_il=MERCOLEDI,
        ora=ora,
        giorni=giorni,
        tipo_evento=tipo_evento,
        minuti=minuti,
    )


def _evento(
    *,
    id: int = 1,
    tipo: str = "lezione",
    inizio: datetime = MERCOLEDI,
    durata_minuti: int = 120,
    tutto_il_giorno: bool = False,
) -> dom.EventoInCalendario:
    return dom.EventoInCalendario(
        id=id,
        tipo=tipo,
        inizio=inizio,
        fine=inizio + timedelta(minutes=durata_minuti),
        tutto_il_giorno=tutto_il_giorno,
    )


# — gli estremi della finestra —


def test_scatta_nell_istante_esatto() -> None:
    (scatto,) = dom.dovute([_regola()], MERCOLEDI)
    assert scatto.momento == MERCOLEDI
    assert scatto.evento_id is None


def test_scatta_se_il_worker_passa_con_qualche_minuto_di_ritardo() -> None:
    """Il caso normale: il worker si sveglia ogni cinque minuti, non alle 19:00."""
    assert dom.dovute([_regola()], MERCOLEDI + timedelta(minutes=4, seconds=59))


def test_non_scatta_due_volte_sullo_stesso_istante() -> None:
    """L'estremo sinistro è **aperto**, o due giri consecutivi prenderebbero lo
    stesso istante: quello di cinque minuti fa è già stato il «adesso» di prima."""
    assert dom.dovute([_regola()], MERCOLEDI + dom.FINESTRA) == []


def test_non_scatta_prima_del_momento() -> None:
    assert dom.dovute([_regola()], MERCOLEDI - timedelta(minutes=1)) == []


def test_niente_recupero_dopo_un_pi_spento() -> None:
    """Un promemoria delle 19 non arriva alle 23:30: non è un recupero, è rumore."""
    assert dom.dovute([_regola()], MERCOLEDI.replace(hour=23, minute=30)) == []


# — lo scavalco della mezzanotte —


def test_una_regola_serale_scatta_anche_se_il_giro_cade_dopo_mezzanotte() -> None:
    """Le 23:58 valutate alle 00:01: l'istante previsto è nel giorno **prima**."""
    tardi = _regola(ora="23:58")
    dopo_mezzanotte = datetime(2026, 9, 17, 0, 1)

    (scatto,) = dom.dovute([tardi], dopo_mezzanotte)

    assert scatto.momento == datetime(2026, 9, 16, 23, 58)


def test_il_giorno_della_settimana_e_quello_dell_occorrenza_non_di_adesso() -> None:
    """Una regola del mercoledì non deve scattare il giovedì all'una di notte.

    Se il controllo guardasse `adesso.isoweekday()` invece del giorno
    dell'occorrenza, questa passerebbe — e il promemoria arriverebbe un giorno
    dopo quello che hai chiesto.
    """
    del_mercoledi = _regola(ora="23:58", giorni=(3,))
    giovedi_notte = datetime(2026, 9, 17, 0, 1)

    (scatto,) = dom.dovute([del_mercoledi], giovedi_notte)
    assert scatto.momento.isoweekday() == 3

    del_giovedi = _regola(ora="23:58", giorni=(4,))
    assert dom.dovute([del_giovedi], giovedi_notte) == []


# — i giorni della settimana —


def test_senza_giorni_vale_tutti_i_giorni() -> None:
    for giorno in range(14, 21):
        quando = MERCOLEDI.replace(day=giorno)
        assert dom.dovute([_regola()], quando), f"{quando:%A} non ha fatto scattare"


def test_solo_nei_giorni_scelti() -> None:
    domenicale = _regola(giorni=(7,))
    domenica = datetime(2026, 9, 20, 19, 0)

    assert dom.dovute([domenicale], domenica)
    assert dom.dovute([domenicale], MERCOLEDI) == []


# — gli stati —


@pytest.mark.parametrize("stato", [dom.Stato.PAUSA, dom.Stato.SCARTATA, dom.Stato.PROPOSTA])
def test_solo_le_attive_si_valutano(stato: dom.Stato) -> None:
    assert dom.dovute([_regola(stato=stato)], MERCOLEDI) == []


# — agganciate a un tipo di evento —


def test_prima_di_ogni_lezione_scatta_una_volta_per_lezione() -> None:
    """Tre lezioni, tre messaggi: uno solo al mattino non aiuta per quella delle 16."""
    regola = _regola(trigger=dom.Trigger.PRIMA_EVENTO, ora=None, tipo_evento="lezione", minuti=30)
    # Tutte e tre cominciano fra trenta minuti da tre «adesso» diversi: qui si
    # guarda un istante solo, quindi se ne prepara una che comincia adesso+30.
    eventi = [
        _evento(id=1, inizio=MERCOLEDI + timedelta(minutes=30)),
        _evento(id=2, inizio=MERCOLEDI + timedelta(minutes=30)),
        _evento(id=3, inizio=MERCOLEDI + timedelta(hours=5)),
    ]

    scatti = dom.dovute([regola], MERCOLEDI, eventi=eventi)

    assert [s.evento_id for s in scatti] == [1, 2]


def test_due_eventi_alla_stessa_ora_non_si_coprono_a_vicenda() -> None:
    """Due corsi in due aule alla stessa ora: senza l'id nella chiave, il
    secondo risulterebbe già fatto e il messaggio non arriverebbe."""
    regola = _regola(trigger=dom.Trigger.PRIMA_EVENTO, ora=None, tipo_evento="lezione", minuti=30)
    eventi = [
        _evento(id=7, inizio=MERCOLEDI + timedelta(minutes=30)),
        _evento(id=9, inizio=MERCOLEDI + timedelta(minutes=30)),
    ]

    chiavi = {s.chiave for s in dom.dovute([regola], MERCOLEDI, eventi=eventi)}

    assert len(chiavi) == 2


def test_dopo_evento_guarda_la_fine() -> None:
    regola = _regola(trigger=dom.Trigger.DOPO_EVENTO, ora=None, tipo_evento="palestra", minuti=0)
    finita_adesso = _evento(
        tipo="palestra", inizio=MERCOLEDI - timedelta(hours=1), durata_minuti=60
    )

    (scatto,) = dom.dovute([regola], MERCOLEDI, eventi=[finita_adesso])

    assert scatto.momento == MERCOLEDI


def test_un_altro_tipo_non_la_fa_scattare() -> None:
    regola = _regola(trigger=dom.Trigger.PRIMA_EVENTO, ora=None, tipo_evento="lezione", minuti=30)
    palestra = _evento(tipo="palestra", inizio=MERCOLEDI + timedelta(minutes=30))

    assert dom.dovute([regola], MERCOLEDI, eventi=[palestra]) == []


def test_gli_eventi_di_giornata_restano_fuori() -> None:
    """`custode_calendario.Evento` lo diceva prima che le regole esistessero: un
    evento senza un'ora non ha un «prima». La sua fine in tabella è 23:59:59, e
    un «dopo» a mezzanotte non vorrebbe dire niente."""
    regola = _regola(trigger=dom.Trigger.PRIMA_EVENTO, ora=None, tipo_evento="lezione", minuti=30)
    compleanno = _evento(inizio=MERCOLEDI + timedelta(minutes=30), tutto_il_giorno=True)

    assert dom.dovute([regola], MERCOLEDI, eventi=[compleanno]) == []


def test_gli_scatti_escono_in_ordine_di_quando_dovevano_succedere() -> None:
    presto = _regola(id=9, ora="18:58")
    tardi = _regola(id=2, ora="19:00")

    scatti = dom.dovute([presto, tardi], MERCOLEDI + timedelta(minutes=1))

    assert [s.regola.id for s in scatti] == [9, 2]


# — la chiave con cui uno scatto si registra —


def test_la_chiave_non_dipende_dal_momento_in_cui_si_valuta() -> None:
    """È ciò che rende `job_runs` capace di dire «questa l'ho già mandata»: due
    giri ravvicinati dopo un riavvio devono produrre la stessa chiave."""
    regola = _regola()
    prima = dom.dovute([regola], MERCOLEDI)[0]
    poi = dom.dovute([regola], MERCOLEDI + timedelta(minutes=3))[0]

    assert prima.chiave == poi.chiave
    assert prima.nome_job == "regola:1"


# — le forme che una regola può avere —


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    with connessione(db_path) as aperta:
        migra(aperta)
        yield aperta


def test_una_regola_dettata_nasce_attiva(conn: sqlite3.Connection) -> None:
    """§8.10: scrivendola l'hai già approvata, non serve confermarla di nuovo."""
    regola = dom.crea_a_orario(
        conn, ora="19:00", messaggio="prendi la creatina", creata_il=MERCOLEDI
    )

    assert regola.stato is dom.Stato.ATTIVA
    assert regola.origine is dom.Origine.UTENTE
    assert regola.giorni == dom.TUTTI_I_GIORNI


def test_l_orario_si_normalizza(conn: sqlite3.Connection) -> None:
    regola = dom.crea_a_orario(conn, ora="9:5", messaggio="sveglia", creata_il=MERCOLEDI)
    assert regola.ora == "09:05"


def test_sette_giorni_valgono_come_nessuno(conn: sqlite3.Connection) -> None:
    """Sono la stessa regola scritta in due modi; tenerli distinti darebbe due
    righe che si comportano uguale e si leggono diverse."""
    regola = dom.crea_a_orario(
        conn, ora="19:00", messaggio="x", creata_il=MERCOLEDI, giorni=[1, 2, 3, 4, 5, 6, 7]
    )
    assert regola.giorni == dom.TUTTI_I_GIORNI


def test_i_giorni_si_ordinano_e_si_deduplicano(conn: sqlite3.Connection) -> None:
    regola = dom.crea_a_orario(
        conn, ora="19:00", messaggio="x", creata_il=MERCOLEDI, giorni=[4, 1, 4]
    )
    assert regola.giorni == (1, 4)


@pytest.mark.parametrize("giorno", [0, 8, -1])
def test_un_giorno_che_non_esiste_e_un_errore(conn: sqlite3.Connection, giorno: int) -> None:
    with pytest.raises(ValueError):
        dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=MERCOLEDI, giorni=[giorno])


def test_un_messaggio_vuoto_e_un_errore(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        dom.crea_a_orario(conn, ora="19:00", messaggio="   ", creata_il=MERCOLEDI)


def test_un_orario_storto_e_un_errore(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        dom.crea_a_orario(conn, ora="venticinque", messaggio="x", creata_il=MERCOLEDI)


def test_un_anticipo_oltre_un_giorno_e_un_errore(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        dom.crea_da_evento(
            conn,
            trigger=dom.Trigger.PRIMA_EVENTO,
            tipo_evento="lezione",
            minuti=dom.MAX_MINUTI + 1,
            messaggio="x",
            creata_il=MERCOLEDI,
        )


def test_un_tipo_che_non_esiste_non_entra(conn: sqlite3.Connection) -> None:
    """La chiave esterna della 011: meglio un errore adesso che una regola che
    non scatterà mai perché punta a un tipo cancellato."""
    with pytest.raises(sqlite3.IntegrityError):
        dom.crea_da_evento(
            conn,
            trigger=dom.Trigger.PRIMA_EVENTO,
            tipo_evento="inventato",
            minuti=30,
            messaggio="x",
            creata_il=MERCOLEDI,
        )


def test_i_quattro_tipi_di_partenza_si_possono_usare_subito(conn: sqlite3.Connection) -> None:
    regola = dom.crea_da_evento(
        conn,
        trigger=dom.Trigger.PRIMA_EVENTO,
        tipo_evento="lezione",
        minuti=30,
        messaggio="fra poco lezione",
        creata_il=MERCOLEDI,
    )
    assert regola.tipo_evento == "lezione"
    assert regola.ora is None


# — gli stati, e cosa non si può fare —


def test_pausa_e_ritorno(conn: sqlite3.Connection) -> None:
    regola = dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=MERCOLEDI)

    assert dom.imposta_stato(conn, regola.id, dom.Stato.PAUSA).stato is dom.Stato.PAUSA
    assert dom.imposta_stato(conn, regola.id, dom.Stato.ATTIVA).stato is dom.Stato.ATTIVA


def test_una_scartata_non_torna_attiva(conn: sqlite3.Connection) -> None:
    """§8.10 promette che Custode non riproponga una regola scartata."""
    regola = dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=MERCOLEDI)
    dom.imposta_stato(conn, regola.id, dom.Stato.SCARTATA)

    with pytest.raises(dom.TransizioneNonValida):
        dom.imposta_stato(conn, regola.id, dom.Stato.ATTIVA)


def test_rimettere_lo_stato_che_ha_gia_non_e_un_errore(conn: sqlite3.Connection) -> None:
    """Due tap sullo stesso segmento della pagina non devono dare un 409."""
    regola = dom.crea_a_orario(conn, ora="19:00", messaggio="x", creata_il=MERCOLEDI)
    assert dom.imposta_stato(conn, regola.id, dom.Stato.ATTIVA).stato is dom.Stato.ATTIVA


def test_una_regola_che_non_esiste(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.RegolaInesistente):
        dom.per_id(conn, 999)


def test_attive_non_porta_le_altre(conn: sqlite3.Connection) -> None:
    viva = dom.crea_a_orario(conn, ora="19:00", messaggio="viva", creata_il=MERCOLEDI)
    ferma = dom.crea_a_orario(conn, ora="20:00", messaggio="ferma", creata_il=MERCOLEDI)
    dom.imposta_stato(conn, ferma.id, dom.Stato.PAUSA)

    assert [r.id for r in dom.attive(conn)] == [viva.id]
    assert len(dom.elenco(conn)) == 2


# — il conto degli scatti, che la pagina mostra —


def test_conta_gli_scatti_per_regola(conn: sqlite3.Connection) -> None:
    segna_eseguito(conn, dom.nome_job(1), "2026-09-16T19:00", MERCOLEDI)
    segna_eseguito(conn, dom.nome_job(1), "2026-09-15T19:00", MERCOLEDI)
    segna_eseguito(conn, dom.nome_job(2), "2026-09-16T08:00", MERCOLEDI)
    segna_eseguito(conn, "backup", "2026-09-16", MERCOLEDI)

    conteggi = conteggi_da(conn, "regola:", MERCOLEDI - timedelta(days=7))

    assert conteggi == {"regola:1": 2, "regola:2": 1}


def test_il_conto_guarda_solo_da_quando_gli_si_dice(conn: sqlite3.Connection) -> None:
    vecchio = MERCOLEDI - timedelta(days=30)
    segna_eseguito(conn, dom.nome_job(1), "vecchio", vecchio)
    segna_eseguito(conn, dom.nome_job(1), "nuovo", MERCOLEDI)

    assert conteggi_da(conn, "regola:", MERCOLEDI - timedelta(days=7)) == {"regola:1": 1}


# — etichette —


def test_etichetta_dei_giorni() -> None:
    assert dom.etichetta_giorni(()) == "tutti i giorni"
    assert dom.etichetta_giorni((1,)) == "il lunedì"
    assert dom.etichetta_giorni((1, 4)) == "lunedì e giovedì"
    assert dom.etichetta_giorni((1, 3, 5)) == "lunedì, mercoledì e venerdì"
