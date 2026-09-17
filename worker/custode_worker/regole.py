"""Il job che fa scattare le regole di contesto (ARCHITECTURE.md §8.10).

Mette insieme tre pezzi che esistono già: le regole (`custode_core.dominio.regole`),
il calendario da cui alcune dipendono (`custode_core.dominio.calendario`) e il
modo di scriverti su Telegram (`custode_worker.telegram`). Qui in mezzo non c'è
nessuna decisione su *quando* — quella è una funzione pura nel dominio, e si
prova senza aspettare le 19.

**Nessun modello, mai.** §8.10 lo dice per esteso: una regola già approvata si
valuta con logica pura, costo zero. È anche il motivo per cui questo job non ha
un «modulo spento» come il tagging: non c'è nessuna chiave da avere: se ci sono
regole attive, funziona.

**Un registro per non ripetersi.** Ogni scatto si segna in `job_runs` col nome
della sua regola e l'istante previsto come periodo — la stessa tabella che
tiene il conto del riepilogo settimanale e del backup. Serve perché il worker
può ripassare dentro la stessa finestra (un riavvio, un giro più corto del
previsto) e un promemoria che arriva due volte a distanza di due minuti è
peggio di uno che non arriva.

**Un guasto di rete non si recupera**, ed è coerente col resto: se Telegram non
risponde la riga non si segna, quindi al giro dopo si riprova — ma solo se
l'istante è ancora dentro la finestra di cinque minuti. Passata quella, quel
promemoria è perso, esattamente come sarebbe perso se il Pi fosse stato spento.
Un promemoria delle 19 consegnato alle 19:40 non è un recupero.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from custode_bot.risposte import promemoria_regola
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import regole as dom
from custode_core.registro_job import gia_eseguito, segna_eseguito
from custode_worker.telegram import InvioNonRiuscito, Spedizioniere

log = logging.getLogger("custode.worker")


@dataclass(frozen=True)
class Esito:
    """Com'è andato un giro, in una forma su cui chi chiama possa decidere."""

    scattate: int = 0
    """Quanti promemoria sono partiti davvero."""

    gia_fatte: int = 0
    """Quanti scatti erano già segnati: il worker è ripassato nella stessa
    finestra, ed è proprio ciò che il registro serve a intercettare."""

    non_spedite: int = 0
    """Quanti non sono partiti perché Telegram non ha risposto."""

    @property
    def qualcosa_da_dire(self) -> bool:
        return bool(self.scattate or self.non_spedite)


def _eventi_per(
    conn: sqlite3.Connection, regole: list[dom.Regola], ora: datetime
) -> list[dom.EventoInCalendario]:
    """Gli eventi che servono a valutare queste regole, e solo se servono.

    Se nessuna regola è agganciata a un tipo di evento — il caso di chi ha solo
    promemoria a orario — il calendario non si legge affatto: sarebbe una query
    ogni cinque minuti per sempre, per una risposta che nessuno guarda.
    """
    if not any(r.trigger is not dom.Trigger.ORARIO for r in regole):
        return []
    da, a = dom.finestra_eventi(ora)
    return [
        dom.EventoInCalendario(
            id=evento.id,
            tipo=evento.tipo,
            inizio=evento.inizio,
            fine=evento.fine,
            tutto_il_giorno=evento.tutto_il_giorno,
        )
        for evento in dom_calendario.fra(conn, da, a)
    ]


def esegui(conn: sqlite3.Connection, ora: datetime, *, telegram: Spedizioniere) -> Esito:
    """Un giro di valutazione. Non solleva: i guasti tornano nell'esito.

    Un'eccezione che sfugge da qui fermerebbe anche i job che vengono dopo nello
    stesso giro del worker, e un promemoria non è più importante del backup.
    """
    attive = dom.attive(conn)
    if not attive:
        # Il caso normale finché non ne scrivi una: una `SELECT` sull'indice
        # parziale e via, senza nemmeno guardare il calendario.
        return Esito()

    scatti = dom.dovute(attive, ora, eventi=_eventi_per(conn, attive, ora))

    scattate = gia_fatte = non_spedite = 0
    for scatto in scatti:
        if gia_eseguito(conn, scatto.nome_job, scatto.chiave):
            gia_fatte += 1
            continue
        try:
            telegram.manda(promemoria_regola(scatto.regola))
        except InvioNonRiuscito as errore:
            # Non si segna: al giro dopo si riprova, finché l'istante resta
            # dentro la finestra. Dopo, è perso — come sarebbe perso se il Pi
            # fosse stato spento, e per la stessa ragione.
            log.warning("promemoria della regola %d non spedito: %s", scatto.regola.id, errore)
            non_spedite += 1
            continue
        segna_eseguito(conn, scatto.nome_job, scatto.chiave, ora)
        scattate += 1

    return Esito(scattate=scattate, gia_fatte=gia_fatte, non_spedite=non_spedite)
