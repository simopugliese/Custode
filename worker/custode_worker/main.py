"""Il worker: si sveglia, chiede cosa è dovuto, lo fa, torna a dormire.

Nessuna libreria di scheduling: la domanda «cosa è dovuto adesso?» è una
funzione pura in `pianificazione.py`, e un ciclo che la interroga ogni pochi
minuti basta per i tempi in gioco — un riepilogo serale, più avanti un backup
notturno e il digest del mattino (§8.13, §9).

Il vantaggio non è risparmiare una dipendenza: è che l'unica cosa che può
sbagliare — *quando* — si prova in un millesimo di secondo invece che
aspettando domenica sera.
"""

from __future__ import annotations

import logging
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from types import FrameType

from custode_bot.config import ImpostazioniBot, get_impostazioni_bot
from custode_calendario.config import ImpostazioniCalendario, get_impostazioni_calendario
from custode_calendario.evento import SorgenteCalendario
from custode_calendario.google import ClientGoogle
from custode_core.config import Settings, get_settings
from custode_core.db import connessione
from custode_core.dominio import abitudini as dom_abitudini
from custode_core.formato import adesso
from custode_core.migrazioni import migra
from custode_router import Router
from custode_worker import abitudini as worker_abitudini
from custode_worker import backup, settimanale
from custode_worker import calendario as worker_calendario
from custode_worker.config import ImpostazioniWorker, get_impostazioni_worker
from custode_worker.pianificazione import (
    AVVISO_CALENDARIO_FERMO,
    BACKUP,
    MINUTI_SYNC_CALENDARIO,
    REPORT_MENSILE_ABITUDINI,
    RIEPILOGO_SETTIMANALE,
    SENZA_PERIODO,
    SYNC_CALENDARIO,
    dimentica,
    dimentica_prima_di,
    fascia_dovuta,
    gia_eseguito,
    giorno_dovuto,
    mese_dovuto,
    segna_eseguito,
    settimana_dovuta,
)
from custode_worker.telegram import ClientTelegram, InvioNonRiuscito

log = logging.getLogger("custode.worker")

_fermati = False


def _chiedi_arresto(_segnale: int, _frame: FrameType | None) -> None:
    """Docker manda SIGTERM: si finisce il giro in corso e si esce pulito."""
    global _fermati
    _fermati = True


def giro(
    impostazioni: Settings,
    worker: ImpostazioniWorker,
    *,
    router: Router,
    telegram: ClientTelegram,
    calendario: ImpostazioniCalendario,
    sorgente_calendario: SorgenteCalendario,
) -> None:
    """Un singolo passaggio: guarda cosa è dovuto e, se c'è, lo fa."""
    ora = adesso(impostazioni.timezone)
    _giro_backup(impostazioni, worker, ora)
    _giro_calendario(impostazioni, calendario, ora, sorgente=sorgente_calendario, telegram=telegram)
    _giro_settimanale(impostazioni, worker, ora, router=router, telegram=telegram)
    _giro_mensile_abitudini(impostazioni, worker, ora, router=router, telegram=telegram)


def _giro_backup(impostazioni: Settings, worker: ImpostazioniWorker, ora: datetime) -> None:
    """Il backup giornaliero (§9). Non manda niente su Telegram.

    Un backup riuscito è la cosa meno interessante che possa succedere: se
    notificasse ogni giorno, la notifica smetterebbe di voler dire qualcosa. Un
    backup *fallito* finisce nei log come warning e il giorno non si segna, così
    al giro dopo si riprova.
    """
    ore, minuti = worker.ora_e_minuto_backup()
    giorno = giorno_dovuto(ora, ore=ore, minuti=minuti)

    with connessione(impostazioni.db_path) as conn:
        if gia_eseguito(conn, BACKUP, giorno):
            return
        try:
            esito = backup.esegui(
                impostazioni.db_path,
                worker.backup_cartella,
                ora,
                chiave=worker.backup_chiave or None,
            )
        except (backup.BackupNonRiuscito, OSError) as errore:
            log.warning("backup del %s non riuscito, riproverò: %s", giorno, errore)
            return

        segna_eseguito(conn, BACKUP, giorno, ora)

    log.info(
        "backup %s (%s, %.1f kB)%s",
        esito.percorso.name,
        "cifrato" if esito.cifrato else "IN CHIARO: manca WORKER_BACKUP_CHIAVE",
        esito.byte / 1024,
        f", rimossi {len(esito.rimossi)} vecchi" if esito.rimossi else "",
    )


def _giro_calendario(
    impostazioni: Settings,
    calendario: ImpostazioniCalendario,
    ora: datetime,
    *,
    sorgente: SorgenteCalendario,
    telegram: ClientTelegram,
) -> None:
    """La sincronizzazione del calendario (§8.10), ogni quarto d'ora.

    È l'unico job del worker che non ha un'ora del giorno: il suo periodo è la
    fascia di quindici minuti in cui cade adesso. Il worker si sveglia ogni
    cinque, quindi la stessa fascia viene interrogata tre volte e coperta una —
    che è anche il margine su cui si appoggia il tentativo dopo un guasto di
    rete.
    """
    fascia = fascia_dovuta(ora, ogni_minuti=MINUTI_SYNC_CALENDARIO)

    with connessione(impostazioni.db_path) as conn:
        if gia_eseguito(conn, SYNC_CALENDARIO, fascia):
            return

        esito = worker_calendario.esegui(
            conn,
            ora,
            sorgente=sorgente,
            giorni_indietro=calendario.giorni_indietro,
            giorni_avanti=calendario.giorni_avanti,
        )

        if esito.spento:
            # Nessuna credenziale: il modulo è spento, non rotto. Non si segna
            # la fascia, così il giorno che le metti il job parte da solo senza
            # aspettare il quarto d'ora successivo.
            return

        if esito.autorizzazione_scaduta:
            log.error("calendario fermo: %s", esito.errore)
            if not _avvisa_calendario_fermo(conn, esito, ora, telegram=telegram):
                # L'avviso non è partito: non si segna la fascia, così al giro
                # dopo si riprova invece di restare zitti per sempre.
                return
            # La fascia sì: riprovare fra cinque minuti un permesso morto non
            # serve a niente, e fra un quarto d'ora basta ad accorgersi che nel
            # frattempo hai rifatto l'autorizzazione.
            segna_eseguito(conn, SYNC_CALENDARIO, fascia, ora)
            return

        if esito.errore is not None:
            log.warning("sincronizzazione del calendario non riuscita, riproverò: %s", esito.errore)
            return

        # Il calendario risponde di nuovo: l'avviso si dimentica, così un
        # guasto futuro potrà tornare a farsi sentire.
        dimentica(conn, AVVISO_CALENDARIO_FERMO, SENZA_PERIODO)
        segna_eseguito(conn, SYNC_CALENDARIO, fascia, ora)
        dimentica_prima_di(conn, SYNC_CALENDARIO, fascia - timedelta(days=1))

        cambiato = esito.sincronizzato
        assert cambiato is not None  # riuscito ⇒ c'è un esito
        if cambiato.nuovi or cambiato.aggiornati or cambiato.rimossi:
            log.info(
                "calendario: %d eventi, %d nuovi, %d aggiornati, %d rimossi",
                cambiato.totale_visti,
                cambiato.nuovi,
                cambiato.aggiornati,
                cambiato.rimossi,
            )


def _avvisa_calendario_fermo(
    conn: sqlite3.Connection,
    esito: worker_calendario.Esito,
    ora: datetime,
    *,
    telegram: ClientTelegram,
) -> bool:
    """Ti scrive che il calendario è fermo, una volta sola. True se può proseguire.

    Una volta sola perché con un permesso scaduto il guasto si ripete ad ogni
    giro: ripeterlo trecento volte al giorno renderebbe illeggibile anche il
    canale che serve alle cose che contano. La riga in `job_runs` sparisce al
    primo sync riuscito, quindi un guasto successivo tornerà a farsi sentire.
    """
    avviso = esito.avviso()
    if avviso is None or gia_eseguito(conn, AVVISO_CALENDARIO_FERMO, SENZA_PERIODO):
        return True
    try:
        telegram.manda(avviso)
    except InvioNonRiuscito as errore:
        log.warning("avviso del calendario non spedito, riproverò: %s", errore)
        return False
    segna_eseguito(conn, AVVISO_CALENDARIO_FERMO, SENZA_PERIODO, ora)
    return True


def _giro_settimanale(
    impostazioni: Settings,
    worker: ImpostazioniWorker,
    ora: datetime,
    *,
    router: Router,
    telegram: ClientTelegram,
) -> None:
    ore, minuti = worker.ora_e_minuto()
    lunedi = settimana_dovuta(ora, giorno=worker.giorno_riepilogo, ore=ore, minuti=minuti)
    if lunedi is None:
        return

    with connessione(impostazioni.db_path) as conn:
        if gia_eseguito(conn, RIEPILOGO_SETTIMANALE, lunedi):
            return

        log.info("riepilogo settimanale della settimana del %s", lunedi.isoformat())
        esito = settimanale.esegui(conn, ora, lunedi=lunedi, router=router)

        if esito.messaggio is not None:
            try:
                telegram.manda(esito.messaggio)
            except InvioNonRiuscito as errore:
                # Non si segna come fatto: al prossimo giro si riprova, invece
                # di perdere la settimana per un guasto di rete di trenta secondi.
                log.warning("invio del riepilogo non riuscito, riproverò: %s", errore)
                return

        segna_eseguito(conn, RIEPILOGO_SETTIMANALE, lunedi, ora)
        log.info(
            "settimana %s: %d voci, riepilogo=%s, %d candidati da rivedere",
            lunedi.isoformat(),
            esito.voci_lette,
            "sì" if esito.riepilogo_scritto else "no",
            esito.candidati_da_rivedere,
        )


def _giro_mensile_abitudini(
    impostazioni: Settings,
    worker: ImpostazioniWorker,
    ora: datetime,
    *,
    router: Router,
    telegram: ClientTelegram,
) -> None:
    """Il resoconto mensile delle abitudini (§8.6).

    Ha un job suo e non viaggia col settimanale perché guarda un periodo
    diverso: §8.6 lo vuole «per i trend più lenti», ed è l'unico che può
    proporre di adeguare un target. Gira il primo del mese, alla stessa ora del
    riepilogo settimanale.
    """
    ore, minuti = worker.ora_e_minuto()
    primo = mese_dovuto(ora, ore=ore, minuti=minuti)
    if primo is None:
        return

    with connessione(impostazioni.db_path) as conn:
        if gia_eseguito(conn, REPORT_MENSILE_ABITUDINI, primo):
            return

        log.info("resoconto mensile delle abitudini per %s", primo.isoformat())
        esito = worker_abitudini.esegui(
            conn, ora, periodo=dom_abitudini.Periodo.MESE, chiave=primo, router=router
        )

        if esito.errore is not None:
            # Non si segna come fatto: al prossimo giro si riprova, invece di
            # perdere il mese per un timeout.
            log.warning("resoconto mensile non riuscito, riproverò: %s", esito.errore)
            return

        if esito.messaggio is not None:
            try:
                telegram.manda(esito.messaggio)
            except InvioNonRiuscito as errore:
                log.warning("invio del resoconto mensile non riuscito, riproverò: %s", errore)
                return

        segna_eseguito(conn, REPORT_MENSILE_ABITUDINI, primo, ora)
        log.info(
            "mese %s: %d abitudini, report=%s, proposta=%s",
            primo.isoformat(),
            esito.abitudini_lette,
            "sì" if esito.report_scritto else "no",
            "sì" if esito.proposta_creata else "no",
        )


def main() -> int:
    impostazioni = get_settings()
    worker = get_impostazioni_worker()
    bot: ImpostazioniBot = get_impostazioni_bot()
    logging.basicConfig(level=impostazioni.log_level.upper())

    try:
        worker.ora_e_minuto()
        worker.ora_e_minuto_backup()
    except ValueError as errore:
        log.error("configurazione del worker non valida: %s", errore)
        return 1

    if not bot.configurato():
        # Senza destinatario il riepilogo non arriverebbe da nessuna parte, e
        # un worker che gira in silenzio è peggio di uno che non parte.
        log.error(
            "il worker manda i suoi messaggi su Telegram: servono"
            " TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID"
        )
        return 1

    # Come API e bot: lo schema si porta in pari all'avvio, dentro la stessa
    # transazione con lock che impedisce ai tre processi di pestarsi (§5).
    with connessione(impostazioni.db_path) as conn:
        applicate = migra(conn)
    if applicate:
        log.info("migrazioni applicate: %s", ", ".join(applicate))

    signal.signal(signal.SIGTERM, _chiedi_arresto)
    signal.signal(signal.SIGINT, _chiedi_arresto)

    router = Router()
    telegram = ClientTelegram(bot.bot_token, bot.allowed_user_id)
    calendario = get_impostazioni_calendario()
    sorgente_calendario = ClientGoogle(calendario, impostazioni.timezone)
    log.info(
        "worker avviato: riepilogo di %s alle %s, backup alle %s in %s, controllo ogni %d s",
        worker.giorno_riepilogo,
        worker.ora_riepilogo,
        worker.ora_backup,
        worker.backup_cartella,
        worker.intervallo_secondi,
    )
    if sorgente_calendario.configurata():
        log.info(
            "calendario: %s, da %d giorni fa a %d avanti, ogni %d minuti",
            calendario.calendario_id,
            calendario.giorni_indietro,
            calendario.giorni_avanti,
            MINUTI_SYNC_CALENDARIO,
        )
    else:
        # Detto all'avvio e non ad ogni giro: un modulo spento non è un guasto,
        # ma scoprire dopo un mese che il calendario non si è mai sincronizzato
        # perché mancava una variabile è peggio di una riga di log in più.
        log.info(
            "calendario spento: senza CALENDARIO_CLIENT_ID, CALENDARIO_CLIENT_SECRET e"
            " CALENDARIO_REFRESH_TOKEN non si sincronizza niente (DEPLOY.md § 3-bis)"
        )
    if not worker.backup_chiave:
        # Ripetuto ad ogni avvio apposta: è la differenza fra sapere di avere un
        # backup in chiaro e crederlo cifrato.
        log.warning("WORKER_BACKUP_CHIAVE non impostata: i backup del database NON sono cifrati")

    while not _fermati:
        try:
            giro(
                impostazioni,
                worker,
                router=router,
                telegram=telegram,
                calendario=calendario,
                sorgente_calendario=sorgente_calendario,
            )
        except Exception:
            # Un giro andato male non deve far morire il worker: il prossimo
            # riprova, e nel frattempo l'errore è nei log.
            log.exception("giro del worker fallito")
        for _ in range(worker.intervallo_secondi):
            if _fermati:
                break
            time.sleep(1)

    log.info("worker fermato")
    return 0


if __name__ == "__main__":
    sys.exit(main())
