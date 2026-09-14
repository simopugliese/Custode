"""Il job che tiene il calendario in pari (ARCHITECTURE.md §8.10).

Mette insieme due pezzi che finora non si parlavano: la sorgente, che legge gli
eventi da Google (`custode_calendario`), e l'archivio, che li conserva
(`custode_core.dominio.calendario`). Qui in mezzo non c'è nessuna decisione su
*come* leggere né su *come* salvare: c'è la finestra da chiedere e la
distinzione fra i modi di fallire, che è l'unica cosa che riguarda il job.

**I tre modi di fallire vogliono tre cose diverse**, ed è la ragione per cui
`custode_calendario.errori` li tiene distinti:

- *non configurato* — non è un guasto, è un modulo spento. Non si tenta e non
  si segna niente: il giorno che metti le credenziali il job parte da solo.
- *non raggiungibile* — Google non risponde adesso. La fascia **non** si segna,
  così si riprova al prossimo risveglio del worker.
- *autorizzazione non valida* — nessun tentativo la farà tornare: va rifatta a
  mano. La fascia **si segna**, perché un permesso morto non torna buono
  aspettando; si riprova alla fascia dopo comunque, che è quanto basta ad
  accorgersi che nel frattempo hai riautorizzato. E si chiede di avvisarti,
  perché un calendario fermo in silenzio è esattamente la trappola che §8.10
  descrive: in «Testing» il refresh token scade dopo sette giorni.

**La riconciliazione arriva qui solo dopo una lettura completa.** `eventi()`
segue tutte le pagine e solleva se una non arriva: quando ritorna, quello che
ha in mano è tutto ciò che la sorgente ha da dire sulla finestra, ed è l'unica
condizione in cui l'assenza di un evento significa «disdetto».
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from custode_bot.risposte import Risposta
from custode_calendario.errori import (
    AutorizzazioneNonValida,
    CalendarioNonConfigurato,
    CalendarioNonRaggiungibile,
)
from custode_calendario.evento import SorgenteCalendario
from custode_core.dominio import calendario as dom

AVVISO_FERMO = (
    "⚠️ <b>Il calendario non si aggiorna più.</b>\n"
    "L'autorizzazione a Google non vale più: gli impegni che vedi sono fermi "
    "all'ultima sincronizzazione riuscita.\n\n"
    "Le cause possibili sono tre: il progetto su Google Cloud è rimasto in "
    "«Testing» (lì il permesso scade dopo 7 giorni), hai revocato l'accesso, "
    "o hai cambiato la password dell'account.\n\n"
    "Si rimette con <code>custode-autorizza-calendario</code> — il runbook è "
    "in DEPLOY.md § 3-bis."
)
"""Un messaggio solo, e dice cosa fare.

Non ha un bottone «Annulla» come le azioni decise da un modello (§8.1): non c'è
niente da disfare, c'è una cosa da rifare a mano. Ed è l'unica notifica del
worker che parla di un guasto — il backup riuscito tace apposta, perché una
notifica quotidiana smetterebbe di voler dire qualcosa; questa arriva una volta
e poi tace finché il calendario non riparte.
"""


@dataclass(frozen=True)
class Esito:
    """Com'è andato un giro, in una forma su cui chi chiama possa decidere."""

    spento: bool = False
    """Mancano le credenziali: non si è nemmeno provato."""

    autorizzazione_scaduta: bool = False
    """Il permesso è morto. Non si ripara da solo: va rifatto a mano."""

    errore: str | None = None
    """Un guasto passeggero, da riprovare. `None` se è andata."""

    sincronizzato: dom.Esito | None = None
    """Cos'è cambiato in archivio. `None` se non si è arrivati a scrivere."""

    @property
    def riuscito(self) -> bool:
        return self.sincronizzato is not None

    def avviso(self) -> Risposta | None:
        """Cosa mandare su Telegram, se c'è qualcosa da mandare."""
        if not self.autorizzazione_scaduta:
            return None
        return Risposta(testo=AVVISO_FERMO)


def finestra(oggi: date, *, giorni_indietro: int, giorni_avanti: int) -> tuple[date, date]:
    """I due estremi da chiedere alla sorgente, compresi.

    La stessa coppia va poi a `sincronizza`, e non è una comodità: è
    l'invariante su cui poggia la riconciliazione. Chiedere una finestra e
    riconciliarne una più larga cancellerebbe eventi vivi soltanto perché di
    loro non è stato chiesto niente.
    """
    return oggi - timedelta(days=giorni_indietro), oggi + timedelta(days=giorni_avanti)


def esegui(
    conn: sqlite3.Connection,
    ora: datetime,
    *,
    sorgente: SorgenteCalendario,
    giorni_indietro: int,
    giorni_avanti: int,
) -> Esito:
    """Un giro di sincronizzazione. Non solleva: i guasti tornano nell'esito.

    Un'eccezione che sfugge da qui fermerebbe anche i job che vengono dopo nello
    stesso giro del worker, e il calendario non è più importante del backup.
    """
    if not sorgente.configurata():
        return Esito(spento=True)

    da, a = finestra(ora.date(), giorni_indietro=giorni_indietro, giorni_avanti=giorni_avanti)

    try:
        letti = sorgente.eventi(da, a)
    except AutorizzazioneNonValida as errore:
        return Esito(autorizzazione_scaduta=True, errore=str(errore))
    except CalendarioNonConfigurato:
        # `configurata()` ha già detto di sì: se arriviamo qui le credenziali
        # sono sparite fra una riga e l'altra. Vale come modulo spento.
        return Esito(spento=True)
    except CalendarioNonRaggiungibile as errore:
        return Esito(errore=str(errore))

    return Esito(sincronizzato=dom.sincronizza(conn, letti, da=da, a=a, ora=ora))
