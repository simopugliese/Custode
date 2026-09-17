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


def test_la_domenica_e_femminile() -> None:
    """«il domenica» non lo prende nessun test di logica, e si legge ogni volta
    che quella regola scatta."""
    assert dom.etichetta_giorni((7,)) == "la domenica"


# — «questa te l'ho già proposta», senza chiamare nessuno (§8.10) —


def _abbozzo(
    testo: str,
    *,
    trigger: dom.Trigger = dom.Trigger.ORARIO,
    ora: str | None = "19:00",
    tipo_evento: str | None = None,
) -> dom.Abbozzo:
    return dom.Abbozzo(trigger=trigger, testo=testo, ora=ora, tipo_evento=tipo_evento)


def test_la_stessa_proposta_scritta_uguale() -> None:
    assert dom.stessa_proposta(_abbozzo("prendi la creatina"), _abbozzo("prendi la creatina"))


def test_gli_stessi_minuti_diversi_sono_la_stessa_proposta() -> None:
    """Il caso che l'uguaglianza esatta lascia passare, ed è quello che conta.

    «Trenta minuti prima di palestra» e «quarantacinque prima» sono la stessa
    idea con una manopola girata: riproporre la seconda il giorno dopo che hai
    scartato la prima è il modo di far smettere di guardare la pagina.
    """
    trenta = _abbozzo(
        "prendi la creatina", trigger=dom.Trigger.PRIMA_EVENTO, ora=None, tipo_evento="palestra"
    )
    quarantacinque = _abbozzo(
        "prendi la creatina", trigger=dom.Trigger.DOPO_EVENTO, ora=None, tipo_evento="palestra"
    )
    # Cambiano i minuti (che l'abbozzo non guarda) e pure la direzione.
    assert dom.stessa_proposta(trenta, quarantacinque)


def test_mezz_ora_di_differenza_e_ancora_lo_stesso_momento() -> None:
    assert dom.stessa_proposta(
        _abbozzo("prendi la creatina", ora="19:00"), _abbozzo("prendi la creatina", ora="19:30")
    )


def test_il_mattino_e_la_sera_non_sono_la_stessa_proposta() -> None:
    """Le sole parole aggancerebbero due promemoria che dicono la stessa cosa in
    momenti che non c'entrano niente: «pesati» alle 7 e «pesati» alle 22."""
    assert not dom.stessa_proposta(_abbozzo("pesati", ora="07:00"), _abbozzo("pesati", ora="22:00"))


def test_la_mezzanotte_si_scavalca_anche_qui() -> None:
    """Le 23:50 e le 00:10 distano venti minuti, non ventitré ore e quaranta."""
    assert dom.stessa_proposta(
        _abbozzo("metti la sveglia", ora="23:50"), _abbozzo("metti la sveglia", ora="00:10")
    )


def test_due_cose_diverse_sullo_stesso_impegno_restano_due_proposte() -> None:
    """L'aggancio da solo zittirebbe per sempre qualunque altra proposta sulla
    palestra dopo che ne hai scartata una: la borraccia non è la creatina."""
    creatina = _abbozzo(
        "prendi la creatina", trigger=dom.Trigger.DOPO_EVENTO, ora=None, tipo_evento="palestra"
    )
    borraccia = _abbozzo(
        "riempi la borraccia", trigger=dom.Trigger.PRIMA_EVENTO, ora=None, tipo_evento="palestra"
    )
    assert not dom.stessa_proposta(creatina, borraccia)


def test_due_impegni_diversi_restano_due_proposte() -> None:
    palestra = _abbozzo(
        "prendi la creatina", trigger=dom.Trigger.DOPO_EVENTO, ora=None, tipo_evento="palestra"
    )
    lezione = _abbozzo(
        "prendi la creatina", trigger=dom.Trigger.DOPO_EVENTO, ora=None, tipo_evento="lezione"
    )
    assert not dom.stessa_proposta(palestra, lezione)


def test_un_orario_e_un_evento_non_si_confrontano() -> None:
    a_orario = _abbozzo("prendi la creatina", ora="19:00")
    da_evento = _abbozzo(
        "prendi la creatina", trigger=dom.Trigger.DOPO_EVENTO, ora=None, tipo_evento="palestra"
    )
    assert not dom.stessa_proposta(a_orario, da_evento)


def test_la_frase_piu_lunga_dice_ancora_la_stessa_cosa() -> None:
    """Contenimento e non Jaccard: allungare una delle due non la rende nuova."""
    assert dom.stessa_proposta(
        _abbozzo("prendi la creatina"),
        _abbozzo("prendi la creatina prima di uscire di casa"),
    )


def test_gli_accenti_e_le_maiuscole_non_fanno_una_proposta_nuova() -> None:
    """I due testi arrivano da due tastiere diverse: la tua e quella di un modello."""
    assert dom.stessa_proposta(_abbozzo("Ripassa Analisi"), _abbozzo("ripassa analisi"))


def test_le_parole_di_servizio_non_bastano_a_far_somigliare_due_promemoria() -> None:
    """Il caso in cui l'elenco delle parole vuote è l'unica cosa che decide.

    Con «ricordami» e «sempre» ancora dentro, questi due hanno due parole in
    comune su tre — sopra la soglia — e Custode smetterebbe di proporti il
    portatile perché una volta hai scartato la creatina. Tolte, non hanno più
    niente in comune, che è la verità.

    La versione corta di questa prova («ricordami la creatina» contro
    «ricordami il portatile») **non** provava niente: una parola in comune su
    due sta sotto la soglia comunque, e il test passava anche a filtro spento.
    """
    assert not dom.stessa_proposta(
        _abbozzo("ricordami sempre la creatina"),
        _abbozzo("ricordami sempre il portatile"),
    )


def test_un_messaggio_di_sole_parole_corte_si_confronta_per_intero() -> None:
    """Niente su cui calcolare una frazione: si torna all'uguaglianza del testo."""
    assert dom.stessa_proposta(_abbozzo("bevi"), _abbozzo("Bevi"))
    assert not dom.stessa_proposta(_abbozzo("bevi"), _abbozzo("esci"))


# — le proposte in archivio (§8.10) —


def _proposta(
    conn: sqlite3.Connection,
    *,
    messaggio: str = "prendi la creatina",
    ora: str = "19:00",
    creata_il: datetime = MERCOLEDI,
    confidenza: dom.Confidenza = dom.Confidenza.ALTA,
) -> dom.Regola:
    return dom.crea_a_orario(
        conn,
        ora=ora,
        messaggio=messaggio,
        creata_il=creata_il,
        origine=dom.Origine.IA,
        stato=dom.Stato.PROPOSTA,
        confidenza=confidenza,
        motivazione="lo segni quasi sempre verso quest'ora.",
    )


def test_una_proposta_nasce_in_attesa_e_si_ricorda_perche(conn: sqlite3.Connection) -> None:
    proposta = _proposta(conn)

    assert proposta.stato is dom.Stato.PROPOSTA
    assert proposta.origine is dom.Origine.IA
    assert proposta.confidenza is dom.Confidenza.ALTA
    assert proposta.motivazione == "lo segni quasi sempre verso quest'ora."
    assert dom.in_attesa(conn) == [proposta]


def test_il_perche_resta_addosso_anche_dopo_che_l_hai_approvata(conn: sqlite3.Connection) -> None:
    """«E questa da dove salta fuori?», sei mesi dopo."""
    proposta = _proposta(conn)

    approvata = dom.imposta_stato(conn, proposta.id, dom.Stato.ATTIVA)

    assert approvata.stato is dom.Stato.ATTIVA
    assert approvata.confidenza is dom.Confidenza.ALTA
    assert approvata.motivazione == "lo segni quasi sempre verso quest'ora."


def test_una_regola_dettata_da_te_non_puo_avere_una_confidenza(conn: sqlite3.Connection) -> None:
    """Nessuno l'ha stimata: l'hai scritta, quindi la vuoi."""
    with pytest.raises(ValueError, match="origine"):
        dom.crea_a_orario(
            conn,
            ora="19:00",
            messaggio="prendi la creatina",
            creata_il=MERCOLEDI,
            confidenza=dom.Confidenza.ALTA,
            motivazione="me la sono inventata.",
        )


def test_una_proposta_senza_il_perche_non_si_scrive(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        dom.crea_a_orario(
            conn,
            ora="19:00",
            messaggio="prendi la creatina",
            creata_il=MERCOLEDI,
            origine=dom.Origine.IA,
            stato=dom.Stato.PROPOSTA,
            confidenza=dom.Confidenza.ALTA,
            motivazione="   ",
        )


def test_una_proposta_scade_dopo_due_settimane(conn: sqlite3.Connection) -> None:
    """E scade **fra le scartate**, che è la memoria che impedisce di riproporla."""
    proposta = _proposta(conn)
    limite = MERCOLEDI + timedelta(days=dom.GIORNI_SCADENZA_PROPOSTA)

    # Il giorno prima aspetta ancora.
    assert dom.scadi_proposte(conn, limite - timedelta(seconds=1)) == []
    assert dom.in_attesa(conn) != []

    scadute = dom.scadi_proposte(conn, limite)

    assert [r.id for r in scadute] == [proposta.id]
    assert dom.in_attesa(conn) == []
    assert dom.per_id(conn, proposta.id).stato is dom.Stato.SCARTATA


def test_una_proposta_scaduta_non_torna_a_proporsi(conn: sqlite3.Connection) -> None:
    """È il punto della scadenza-fra-le-scartate invece della cancellazione: se
    sparisse, la notte dopo il pattern la rifarebbe nascere identica."""
    _proposta(conn)
    dom.scadi_proposte(conn, MERCOLEDI + timedelta(days=dom.GIORNI_SCADENZA_PROPOSTA))

    gia = dom.gia_vista(
        conn, dom.Abbozzo(trigger=dom.Trigger.ORARIO, testo="prendi la creatina", ora="19:00")
    )

    assert gia is not None
    assert gia.stato is dom.Stato.SCARTATA


def test_gia_vista_guarda_le_regole_in_ogni_stato(conn: sqlite3.Connection) -> None:
    """Una attiva che dice già questa cosa rende la proposta un doppione da
    approvare per ricevere due volte lo stesso promemoria."""
    dom.crea_a_orario(conn, ora="19:00", messaggio="prendi la creatina", creata_il=MERCOLEDI)

    gia = dom.gia_vista(
        conn, dom.Abbozzo(trigger=dom.Trigger.ORARIO, testo="prendi la creatina", ora="19:15")
    )

    assert gia is not None and gia.stato is dom.Stato.ATTIVA


def test_gia_vista_lascia_passare_una_proposta_davvero_nuova(conn: sqlite3.Connection) -> None:
    dom.crea_a_orario(conn, ora="19:00", messaggio="prendi la creatina", creata_il=MERCOLEDI)

    nuova = dom.Abbozzo(
        trigger=dom.Trigger.DOPO_EVENTO,
        testo="riempi la borraccia",
        ora=None,
        tipo_evento="palestra",
    )

    assert dom.gia_vista(conn, nuova) is None
