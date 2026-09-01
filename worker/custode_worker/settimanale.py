"""Il job settimanale del diario (ARCHITECTURE.md §8.4 punto 7).

Una volta a settimana: Claude legge le voci **approvate** dei sette giorni e ne
scrive un riepilogo, poi il bot ti mostra i segnali raccolti perché tu butti
quelli sbagliati prima che entrino nel profilo.

**Perché il job non riscrive il profilo da solo.** §8.4 chiede una revisione dei
candidati prima della rifusione, e una revisione senza di te non è una
revisione: il job arriva fino a mettertela davanti, e il profilo si riscrive
quando premi «Aggiorna il profilo». Se non lo premi non si perde niente — i
candidati restano in attesa e ricompaiono nella revisione della settimana dopo.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape

from custode_bot import risposte
from custode_core.dominio import diario as dom_diario
from custode_core.dominio import profilo as dom_profilo
from custode_core.formato import etichetta_giorno_voce
from custode_router import Router
from custode_router import diario as router_diario
from custode_router.errori import ErroreRouter

log = logging.getLogger("custode.worker")


@dataclass(frozen=True)
class Esito:
    """Cosa ha fatto il giro, per i log e per i test."""

    settimana_inizio: date
    voci_lette: int
    riepilogo_scritto: bool
    candidati_da_rivedere: int
    messaggio: risposte.Risposta | None
    """Cosa mandare su Telegram. `None` = non c'è niente da dire, e non si manda."""

    errore: str | None = None


def _etichetta_settimana(lunedi: date) -> str:
    domenica = lunedi + timedelta(days=6)
    return f"{etichetta_giorno_voce(lunedi)} – {etichetta_giorno_voce(domenica)}"


def _messaggio(
    lunedi: date, riepilogo: str | None, candidati: int, conn: sqlite3.Connection
) -> risposte.Risposta | None:
    """Compone il messaggio settimanale: prima il riepilogo, poi la revisione.

    Se non c'è né l'uno né l'altra non si manda niente: un messaggio
    automatico che dice «non ho niente da dirti» è solo una notifica sprecata.
    """
    if riepilogo is None and candidati == 0:
        return None

    pezzi: list[str] = []
    bottoni: list[list[risposte.Bottone]] = []

    if riepilogo is not None:
        pezzi.append(
            f"<b>La tua settimana</b>\n<i>{escape(_etichetta_settimana(lunedi))}</i>\n\n"
            + escape(riepilogo)
        )

    if candidati:
        revisione = risposte.revisione_settimanale(conn)
        pezzi.append(revisione.testo)
        bottoni = revisione.bottoni

    return risposte.Risposta(testo="\n\n———\n\n".join(pezzi), bottoni=bottoni)


def esegui(
    conn: sqlite3.Connection,
    ora: datetime,
    *,
    lunedi: date,
    router: Router,
) -> Esito:
    """Il giro settimanale per la settimana che comincia il `lunedi` indicato.

    Non manda niente e non tocca Telegram: prepara il messaggio e lo restituisce,
    così tutto il ragionamento si prova senza rete.
    """
    voci = dom_diario.approvate(conn, da=lunedi, a=lunedi + timedelta(days=6))
    riepilogo: str | None = None
    errore: str | None = None

    if voci:
        # Se esiste già (il job è stato rifatto a mano) non si richiama Claude:
        # il riepilogo di una settimana chiusa non cambia.
        esistente = dom_diario.riepilogo(conn, lunedi)
        if esistente is not None:
            riepilogo = esistente.testo
        else:
            try:
                riepilogo = router_diario.riepilogo_settimanale(
                    router,
                    lunedi=lunedi,
                    voci=[(v.giorno, v.riassunto_approvato or "") for v in voci],
                )
                dom_diario.salva_riepilogo(conn, settimana_inizio=lunedi, testo=riepilogo, ora=ora)
            except ErroreRouter as guasto:
                # Il riepilogo salta ma la revisione dei candidati no: sono due
                # cose indipendenti, e perderle entrambe per un timeout sarebbe
                # sproporzionato.
                errore = router_diario.messaggio_errore(guasto)
                log.warning("riepilogo settimanale non riuscito: %s", guasto)

    candidati = dom_profilo.da_rivedere(conn)
    return Esito(
        settimana_inizio=lunedi,
        voci_lette=len(voci),
        riepilogo_scritto=riepilogo is not None,
        candidati_da_rivedere=len(candidati),
        messaggio=_messaggio(lunedi, riepilogo, len(candidati), conn),
        errore=errore,
    )
