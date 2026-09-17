"""Il job che ti propone una regola (ARCHITECTURE.md §6, §8.10).

Mette in fila tre pezzi che esistono già: il rilevatore di pattern
(`custode_core.dominio.pattern`, puro e gratis), il giudizio di Claude
(`custode_router.regole`) e l'archivio delle regole. Qui in mezzo non c'è
nessuna decisione su *quali* pattern reggono — quella è una funzione pura nel
dominio, e si prova senza aspettare otto settimane.

**Quattro valvole, e servono tutte a non farti smettere di guardare la pagina.**
In ordine di quanto costano:

1. la **scadenza**: le proposte che aspettano da più di due settimane passano
   fra le scartate, perché due settimane di silenzio sono una risposta;
2. il **tetto**: se ne hai già `MAX_PROPOSTE_IN_ATTESA` in coda il job si ferma
   qui, **senza chiamare nessuno** — se non decidi, Custode smette di chiedere
   invece di accumulare;
3. la **soglia** del rilevatore, che quasi tutte le notti non lascia passare
   niente e quindi non fa partire nessuna chiamata;
4. il **giudizio** di Claude, che è l'unico pezzo che costa, e arriva per ultimo
   apposta.

**Una proposta per giro.** Claude ne vede fino a cinque per poter scegliere, ma
in tabella ne finisce una: una proposta è una domanda che aspetta una decisione,
e una alla volta è una decisione mentre tre insieme sono un elenco da smaltire.
Il candidato secondo non scappa — lo storico da cui è uscito c'è ancora domani.

**Il controllo dei doppioni si fa due volte**, prima e dopo la chiamata. Prima
sul nome dell'abitudine, per non pagare una chiamata su un pattern che avevi già
scartato; dopo sul messaggio vero, perché quello lo scrive Claude e può
somigliare a una regola che hai già più di quanto somigliasse il nome.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime

from custode_bot.risposte import proposta_regola
from custode_core.dominio import pattern as dom_pattern
from custode_core.dominio import regole as dom
from custode_router import regole as router_regole
from custode_router.compiti import Compito
from custode_router.errori import (
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)
from custode_router.router import Router
from custode_worker.telegram import InvioNonRiuscito, Spedizioniere

log = logging.getLogger("custode.worker")

_ORDINE_CONFIDENZA: dict[dom.Confidenza, int] = {
    dom.Confidenza.ALTA: 0,
    dom.Confidenza.MEDIA: 1,
    dom.Confidenza.BASSA: 2,
}
"""Con quale si comincia, quando Claude ne propone più d'una.

La confidenza del modello viene **prima** della forza del rilevatore: la forza è
un ordinamento grezzo che sa solo quante volte una cosa è successa, mentre la
confidenza è il giudizio su quanto quella regola ti servirà — che è la domanda
per cui §6 chiama Claude.
"""


@dataclass(frozen=True)
class Esito:
    """Com'è andato un giro, in una forma su cui chi chiama possa decidere."""

    spento: bool = False
    """Nessuna chiave per Claude: il modulo è spento, non rotto."""

    scadute: int = 0
    """Proposte passate fra le scartate perché aspettavano da troppo."""

    in_coda: int = 0
    """Quante aspettano una tua risposta, dopo questo giro."""

    candidati: int = 0
    """Pattern che hanno passato le soglie del rilevatore."""

    gia_visti: int = 0
    """Candidati buttati perché quella regola ce l'hai già, o l'avevi scartata."""

    proposta: dom.Regola | None = None
    """Quella scritta, se ce n'è una."""

    scartate_dal_modello: int = 0
    """Candidati che Claude ha giudicato non meritevoli di un'interruzione."""

    errore: str | None = None
    """Perché il giro non è arrivato in fondo. Chi chiama non segna il giorno."""

    @property
    def qualcosa_da_dire(self) -> bool:
        return bool(self.proposta or self.scadute or self.errore)


def _nuovi(
    conn: sqlite3.Connection, candidati: list[dom_pattern.Candidato]
) -> tuple[list[dom_pattern.Candidato], int]:
    """I candidati su cui vale la pena spendere una chiamata.

    Butta quelli che corrispondono a una regola che hai già — attiva, in pausa,
    in coda o scartata — confrontando sul **nome dell'abitudine**, che è tutto
    quello che c'è prima che Claude scriva il messaggio. È il controllo che
    risparmia la chiamata; quello vero si rifà dopo, sul messaggio.
    """
    nuovi: list[dom_pattern.Candidato] = []
    scartati = 0
    for candidato in candidati:
        gia = dom.gia_vista(conn, candidato.abbozzo())
        if gia is None:
            nuovi.append(candidato)
            continue
        scartati += 1
        log.debug(
            "pattern su «%s» già coperto dalla regola %d (%s)",
            candidato.soggetto,
            gia.id,
            gia.stato,
        )
    return nuovi, scartati


def _scrivi(
    conn: sqlite3.Connection, proposta: router_regole.Proposta, ora: datetime
) -> dom.Regola:
    """La proposta in tabella, come regola `proposta` di origine `ia`.

    Passa dai creatori di sempre e non da una `INSERT` scritta qui: sono loro a
    normalizzare l'orario e a rifiutare una forma che il valutatore non saprebbe
    far scattare, ed è il motivo per cui una proposta approvata è eseguibile per
    costruzione.
    """
    candidato = proposta.candidato
    if candidato.genere is dom_pattern.Genere.A_ORARIO:
        assert candidato.ora is not None  # lo garantisce il rilevatore
        return dom.crea_a_orario(
            conn,
            ora=candidato.ora,
            giorni=candidato.giorni,
            messaggio=proposta.messaggio,
            creata_il=ora,
            origine=dom.Origine.IA,
            stato=dom.Stato.PROPOSTA,
            confidenza=proposta.confidenza,
            motivazione=proposta.motivazione,
        )
    assert candidato.tipo_evento is not None
    return dom.crea_da_evento(
        conn,
        trigger=proposta.trigger,
        tipo_evento=candidato.tipo_evento,
        minuti=proposta.minuti,
        messaggio=proposta.messaggio,
        creata_il=ora,
        origine=dom.Origine.IA,
        stato=dom.Stato.PROPOSTA,
        confidenza=proposta.confidenza,
        motivazione=proposta.motivazione,
    )


def esegui(
    conn: sqlite3.Connection, ora: datetime, *, router: Router, telegram: Spedizioniere
) -> Esito:
    """Un giro. Non solleva: i guasti tornano nell'esito.

    Un'eccezione che sfugge da qui fermerebbe anche i job che vengono dopo nello
    stesso giro del worker, e una proposta non è più importante del backup.
    """
    scadute = dom.scadi_proposte(conn, ora)
    in_coda = len(dom.in_attesa(conn))

    if not router.configurato_per(Compito.PROPOSTA_REGOLE):
        return Esito(spento=True, scadute=len(scadute), in_coda=in_coda)

    if in_coda >= dom.MAX_PROPOSTE_IN_ATTESA:
        # La valvola: se non decidi, Custode smette di chiedere. Niente
        # rilevatore e nessuna chiamata, che è anche il giro più economico.
        return Esito(scadute=len(scadute), in_coda=in_coda)

    candidati = dom_pattern.candidati(conn, ora.date())
    nuovi, gia_visti = _nuovi(conn, candidati)
    base = Esito(
        scadute=len(scadute), in_coda=in_coda, candidati=len(candidati), gia_visti=gia_visti
    )
    if not nuovi:
        return base

    try:
        giudicate = router_regole.giudica(router, nuovi)
    except (ProviderNonConfigurato, ProviderNonRaggiungibile, RispostaNonValida) as errore:
        # Non si segna il giorno: al prossimo giro si riprova. Un pattern non
        # scade come un promemoria — lo storico da cui esce c'è ancora domani.
        return replace(base, errore=str(errore))

    volute = [p for p in giudicate if p.proponi]
    scartate_dal_modello = len(giudicate) - len(volute)
    volute.sort(key=lambda p: (_ORDINE_CONFIDENZA[p.confidenza], -p.candidato.forza))

    for proposta in volute:
        # Il secondo controllo, sul messaggio vero: quello lo ha scritto Claude,
        # e può somigliare a una regola che hai già più di quanto somigliasse il
        # nome dell'abitudine da cui il candidato è nato.
        abbozzo = dom.Abbozzo(
            trigger=proposta.trigger,
            testo=proposta.messaggio,
            ora=proposta.candidato.ora,
            tipo_evento=proposta.candidato.tipo_evento,
        )
        if dom.gia_vista(conn, abbozzo) is not None:
            gia_visti += 1
            continue
        scritta = _scrivi(conn, proposta, ora)
        try:
            telegram.manda(proposta_regola(scritta))
        except InvioNonRiuscito as errore:
            # La riga resta: la proposta esiste e la pagina la mostra. A saltare
            # è solo l'annuncio, e riproporla domani vorrebbe dire due righe
            # uguali in coda per un guasto di rete di trenta secondi.
            log.warning("proposta %d non annunciata su Telegram: %s", scritta.id, errore)
        return replace(
            base,
            gia_visti=gia_visti,
            in_coda=in_coda + 1,
            proposta=scritta,
            scartate_dal_modello=scartate_dal_modello,
        )

    return replace(base, gia_visti=gia_visti, scartate_dal_modello=scartate_dal_modello)
