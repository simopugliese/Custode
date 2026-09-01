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
import sys
import time
from types import FrameType

from custode_bot.config import ImpostazioniBot, get_impostazioni_bot
from custode_core.config import Settings, get_settings
from custode_core.db import connessione
from custode_core.formato import adesso
from custode_core.migrazioni import migra
from custode_router import Router
from custode_worker import settimanale
from custode_worker.config import ImpostazioniWorker, get_impostazioni_worker
from custode_worker.pianificazione import (
    RIEPILOGO_SETTIMANALE,
    gia_eseguito,
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
) -> None:
    """Un singolo passaggio: guarda cosa è dovuto e, se c'è, lo fa."""
    ora = adesso(impostazioni.timezone)
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


def main() -> int:
    impostazioni = get_settings()
    worker = get_impostazioni_worker()
    bot: ImpostazioniBot = get_impostazioni_bot()
    logging.basicConfig(level=impostazioni.log_level.upper())

    try:
        worker.ora_e_minuto()
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
    log.info(
        "worker avviato: riepilogo di %s alle %s, controllo ogni %d s",
        worker.giorno_riepilogo,
        worker.ora_riepilogo,
        worker.intervallo_secondi,
    )

    while not _fermati:
        try:
            giro(impostazioni, worker, router=router, telegram=telegram)
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
