"""Il job che avvisa dei task scaduti e non segnati (ARCHITECTURE.md §8.2).

Mette insieme tre pezzi che esistono già: i task (`custode_core.dominio.task`),
la funzione pura che dice quali scadenze sono passate da poco
(`pianificazione.scadenze_dovute`) e il modo di scriverti su Telegram.

**Nessun modello, nessuna chiave**: è un confronto fra date. È anche il motivo
per cui non ha un «modulo spento».

**Non avvisa due volte per la stessa scadenza.** Ogni avviso si segna in
`job_runs` con la scadenza del task e il suo id come chiave: se il worker
ripassa dopo un riavvio, o per un secondo giro, la riga c'è già. Rinviare il
task cambia la scadenza e quindi la chiave — si riavvisa per la nuova, che è
una scadenza nuova. Non c'è una tabella di avvisi: il passato di questo registro
non serve a niente e si pota (`SCADENZE_TASK`).

**Un messaggio per giro**, non uno per task: due task scaduti alla stessa ora
sono una interruzione, non due.

**Un guasto di Telegram non si segna**, quindi al giro dopo si riprova, finché
la scadenza resta dentro `ORE_UTILI_SCADENZE`. Oltre, ci pensa il digest, che
mette in testa i task in ritardo.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from custode_bot.risposte import task_scaduti
from custode_core.dominio import task as dom_task
from custode_core.registro_job import (
    SCADENZE_TASK,
    dimentica_prima_di,
    gia_eseguito,
    segna_eseguito,
)
from custode_worker.pianificazione import scadenze_dovute
from custode_worker.telegram import InvioNonRiuscito, Spedizioniere

log = logging.getLogger("custode.worker")

GIORNI_DI_MEMORIA = 60
"""Per quanto si tiene la riga di un avviso. Ben oltre le 12 ore in cui un avviso
può ancora partire: serve solo a poterla rileggere se qualcosa non torna."""


@dataclass(frozen=True)
class Esito:
    avvisate: int = 0
    """Quante scadenze sono finite nel messaggio partito."""

    gia_fatte: int = 0
    """Quante erano già segnate: il worker è ripassato, ed è ciò che il registro intercetta."""

    non_spedite: int = 0
    """Quante non sono partite perché Telegram non ha risposto."""

    @property
    def qualcosa_da_dire(self) -> bool:
        return bool(self.avvisate or self.non_spedite)


def esegui(
    conn: sqlite3.Connection,
    ora: datetime,
    *,
    ore: int,
    minuti: int,
    telegram: Spedizioniere,
) -> Esito:
    """Un giro. Non solleva: i guasti tornano nell'esito."""
    dovute = scadenze_dovute(dom_task.elenco(conn, fatto=False), ora, ore=ore, minuti=minuti)
    nuove = [s for s in dovute if not gia_eseguito(conn, SCADENZE_TASK, s.chiave)]
    gia_fatte = len(dovute) - len(nuove)
    dimentica_prima_di(conn, SCADENZE_TASK, ora.date() - timedelta(days=GIORNI_DI_MEMORIA))
    if not nuove:
        return Esito(gia_fatte=gia_fatte)

    try:
        telegram.manda(task_scaduti([s.task for s in nuove], ora))
    except InvioNonRiuscito as errore:
        # Non si segna: al giro dopo si riprova, finché resta dentro la finestra.
        log.warning("avviso di scadenza non spedito (%d task): %s", len(nuove), errore)
        return Esito(gia_fatte=gia_fatte, non_spedite=len(nuove))

    for scadenza in nuove:
        segna_eseguito(conn, SCADENZE_TASK, scadenza.chiave, ora)
    return Esito(avvisate=len(nuove), gia_fatte=gia_fatte)
