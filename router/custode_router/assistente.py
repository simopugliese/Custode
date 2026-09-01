"""Dal testo libero all'azione: «aggiungi il latte» → una voce sulla lista.

È il pezzo che rende utile il router (§8.1): il messaggio arriva da Telegram
(scritto o dettato) o dalla barra «A Custode» della dashboard, il modello lo
interpreta, e l'azione viene eseguita sui moduli che esistono davvero.

Il modello **non tocca il database**: produce solo un'intenzione strutturata,
che questo modulo traduce in chiamate ai servizi di dominio. Un modello che
sbaglia può quindi far fare a Custode una cosa sbagliata fra quelle previste,
mai una cosa non prevista.

Oggi i moduli disponibili sono task e lista della spesa, e §6 instrada
entrambi su DeepSeek. Diario, spese e abitudini si aggiungono qui man mano.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import task as dom_task
from custode_core.formato import etichetta_scadenza
from custode_router.compiti import Compito
from custode_router.errori import ErroreRouter
from custode_router.router import Router


class Azione(StrEnum):
    AGGIUNGI_TASK = "aggiungi_task"
    COMPLETA_TASK = "completa_task"
    RINVIA_TASK = "rinvia_task"
    AGGIUNGI_SPESA = "aggiungi_voce_spesa"
    SEGNA_PRESO = "segna_voce_presa"
    NESSUNA = "nessuna"


SCHEMA_INTENZIONE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "azione": {"type": "string", "enum": [a.value for a in Azione]},
        "titolo": {
            "type": "string",
            "description": "Titolo del task da creare, o nome della voce della spesa.",
        },
        "riferimento": {
            "type": "string",
            "description": (
                "Per completare o rinviare: il titolo del task già esistente a cui"
                " si riferisce il messaggio, copiato dall'elenco fornito."
            ),
        },
        "scadenza": {
            "type": "string",
            "description": (
                "Scadenza in formato AAAA-MM-GG, oppure AAAA-MM-GGTHH:MM se il"
                " messaggio indica un'ora. Stringa vuota se non è indicata."
            ),
        },
        "quantita": {"type": "string", "description": "Quantità della voce, se indicata."},
        "reparto": {
            "type": "string",
            "description": (
                "Reparto di supermercato della voce, fra quelli già in uso se uno"
                " calza, altrimenti uno nuovo sensato. Stringa vuota se incerto."
            ),
        },
        "giorni": {"type": "integer", "description": "Giorni di rinvio, se l'azione è rinvia."},
    },
    "required": ["azione"],
    "additionalProperties": False,
}

SISTEMA = """Sei l'interprete di Custode, un assistente personale.
Ricevi un messaggio scritto o dettato dal proprietario e lo traduci in UNA sola
azione fra quelle previste. Non inventare azioni diverse da quelle elencate.

Regole:
- «ricordami di X», «devo X», «segnati X» → aggiungi_task.
- «sto finendo X», «compra X», «aggiungi X alla lista» → aggiungi_voce_spesa.
- «ho fatto X», «fatto X», «segna fatto X» → completa_task, con `riferimento`
  copiato esattamente dal titolo del task esistente più vicino.
- «ho preso X», «comprato X» → segna_voce_presa, con `riferimento` copiato dal
  nome della voce esistente.
- «rimanda X», «sposta X di N giorni» → rinvia_task.
- Se il messaggio non chiede nessuna di queste cose (un saluto, una domanda,
  uno sfogo), rispondi con azione «nessuna»: è una risposta corretta, non un
  fallimento.
- Non inventare mai un riferimento che non compare nell'elenco fornito."""


@dataclass(frozen=True)
class Intenzione:
    azione: Azione
    titolo: str = ""
    riferimento: str = ""
    scadenza: str = ""
    quantita: str = ""
    reparto: str = ""
    giorni: int = 1


@dataclass(frozen=True)
class Esito:
    """Cosa è stato fatto, in una frase che il bot o la dashboard può mostrare."""

    testo: str
    azione: Azione = Azione.NESSUNA
    task_id: int | None = None
    voce_id: int | None = None
    giorni: int = 1
    """Giorni di rinvio applicati, per poterli togliere se si annulla."""

    @property
    def ha_cambiato_qualcosa(self) -> bool:
        return self.azione is not Azione.NESSUNA


def _contesto(conn: sqlite3.Connection, ora: datetime) -> str:
    """Cosa c'è già, perché il modello possa riferirsi a cose esistenti.

    Senza questo, «ho fatto la spesa» non potrebbe essere collegato al task
    giusto e il modello inventerebbe un titolo simile ma non uguale.
    """
    task = dom_task.elenco(conn, fatto=False)
    voci = dom_lista.elenco(conn, preso=False)
    righe = [f"Oggi è {ora.date().isoformat()} ({ora.strftime('%H:%M')})."]
    righe.append("Task aperti: " + ("; ".join(t.titolo for t in task) if task else "nessuno"))
    righe.append(
        "Voci sulla lista della spesa: " + ("; ".join(v.nome for v in voci) if voci else "nessuna")
    )
    righe.append(
        "Reparti già in uso: "
        + ("; ".join(sorted({v.reparto for v in voci})) if voci else "nessuno")
    )
    return "\n".join(righe)


def interpreta(conn: sqlite3.Connection, ora: datetime, testo: str, router: Router) -> Intenzione:
    """Chiede al modello che azione corrisponde al messaggio."""
    dati = router.chiedi_json(
        # §6: parsing della lista e CRUD dei task sono entrambi "task semplice,
        # alto volume" e vanno a DeepSeek. Si nomina il compito, non il modello.
        Compito.PARSING_LISTA_SPESA,
        sistema=SISTEMA,
        utente=f"{_contesto(conn, ora)}\n\nMessaggio: {testo.strip()}",
        schema=SCHEMA_INTENZIONE,
    )
    return _leggi_intenzione(dati)


def _leggi_intenzione(dati: dict[str, Any]) -> Intenzione:
    grezza = str(dati.get("azione", "")).strip()
    try:
        azione = Azione(grezza)
    except ValueError:
        # Un'azione che non esiste è come nessuna azione: meglio non fare nulla
        # che indovinare quale intendesse.
        return Intenzione(azione=Azione.NESSUNA)

    giorni = dati.get("giorni", 1)
    return Intenzione(
        azione=azione,
        titolo=str(dati.get("titolo") or "").strip(),
        riferimento=str(dati.get("riferimento") or "").strip(),
        scadenza=str(dati.get("scadenza") or "").strip(),
        quantita=str(dati.get("quantita") or "").strip(),
        reparto=str(dati.get("reparto") or "").strip(),
        giorni=giorni if isinstance(giorni, int) and giorni >= 1 else 1,
    )


def _leggi_scadenza(testo: str) -> date | datetime | None:
    if not testo:
        return None
    try:
        return dom_task.leggi_scadenza(testo)
    except ValueError:
        # Una data malformata non deve far fallire tutta l'azione: il task si
        # crea comunque, senza scadenza, invece di perdersi.
        return None


def _trova_task(conn: sqlite3.Connection, riferimento: str) -> dom_task.Task | None:
    if not riferimento:
        return None
    aperti = dom_task.elenco(conn, fatto=False)
    obiettivo = riferimento.casefold()
    for task in aperti:
        if task.titolo.casefold() == obiettivo:
            return task
    # Il modello copia dall'elenco, ma può abbreviare: si accetta un
    # contenimento solo se identifica una riga sola, mai se è ambiguo.
    parziali = [t for t in aperti if obiettivo in t.titolo.casefold()]
    return parziali[0] if len(parziali) == 1 else None


def _trova_voce(conn: sqlite3.Connection, riferimento: str) -> dom_lista.Voce | None:
    if not riferimento:
        return None
    da_prendere = dom_lista.elenco(conn, preso=False)
    obiettivo = riferimento.casefold()
    for voce in da_prendere:
        if voce.nome.casefold() == obiettivo:
            return voce
    parziali = [v for v in da_prendere if obiettivo in v.nome.casefold()]
    return parziali[0] if len(parziali) == 1 else None


def esegui(conn: sqlite3.Connection, ora: datetime, intenzione: Intenzione) -> Esito:
    """Applica l'intenzione ai moduli di dominio."""
    if intenzione.azione is Azione.AGGIUNGI_TASK:
        if not intenzione.titolo:
            return Esito(testo="Non ho capito cosa segnare.")
        task = dom_task.crea(
            conn,
            titolo=intenzione.titolo,
            ora=ora,
            scadenza=_leggi_scadenza(intenzione.scadenza),
            origine="telegram",
        )
        etichetta = etichetta_scadenza(task.scadenza, ora)
        coda = f" — {etichetta}" if etichetta else ""
        return Esito(
            testo=f"Segnato: {task.titolo}{coda}",
            azione=intenzione.azione,
            task_id=task.id,
        )

    if intenzione.azione is Azione.COMPLETA_TASK:
        trovato = _trova_task(conn, intenzione.riferimento or intenzione.titolo)
        if trovato is None:
            return Esito(testo="Non ho trovato quel task fra quelli aperti.")
        dom_task.imposta_fatto(conn, trovato.id, True, ora)
        return Esito(testo=f"Fatto: {trovato.titolo}", azione=intenzione.azione, task_id=trovato.id)

    if intenzione.azione is Azione.RINVIA_TASK:
        trovato = _trova_task(conn, intenzione.riferimento or intenzione.titolo)
        if trovato is None:
            return Esito(testo="Non ho trovato quel task fra quelli aperti.")
        aggiornato = dom_task.rinvia(conn, trovato.id, intenzione.giorni, ora)
        etichetta = etichetta_scadenza(aggiornato.scadenza, ora) or ""
        return Esito(
            testo=f"Rinviato: {trovato.titolo} — {etichetta}",
            azione=intenzione.azione,
            task_id=trovato.id,
            giorni=intenzione.giorni,
        )

    if intenzione.azione is Azione.AGGIUNGI_SPESA:
        if not intenzione.titolo:
            return Esito(testo="Non ho capito cosa aggiungere alla lista.")
        prima = len(dom_lista.elenco(conn, preso=False))
        voce = dom_lista.aggiungi(
            conn,
            nome=intenzione.titolo,
            ora=ora,
            quantita=intenzione.quantita or None,
            reparto=intenzione.reparto or None,
        )
        if len(dom_lista.elenco(conn, preso=False)) == prima:
            return Esito(testo=f"{voce.nome} era già in lista.", voce_id=voce.id)
        return Esito(
            testo=f"Aggiunto alla lista: {voce.nome}",
            azione=intenzione.azione,
            voce_id=voce.id,
        )

    if intenzione.azione is Azione.SEGNA_PRESO:
        trovata = _trova_voce(conn, intenzione.riferimento or intenzione.titolo)
        if trovata is None:
            return Esito(testo="Non ho trovato quella voce sulla lista.")
        dom_lista.imposta_preso(conn, trovata.id, True, ora)
        return Esito(testo=f"Preso: {trovata.nome}", azione=intenzione.azione, voce_id=trovata.id)

    return Esito(testo="Non ho capito cosa vuoi che faccia.")


def interpreta_ed_esegui(
    conn: sqlite3.Connection, ora: datetime, testo: str, router: Router
) -> Esito:
    """Il giro completo, con gli errori del router tradotti in frasi leggibili."""
    if not testo.strip():
        return Esito(testo="Non ho ricevuto niente da interpretare.")
    try:
        intenzione = interpreta(conn, ora, testo, router)
    except ErroreRouter as errore:
        return Esito(testo=_messaggio_errore(errore))
    return esegui(conn, ora, intenzione)


def _messaggio_errore(errore: ErroreRouter) -> str:
    from custode_router.errori import ProviderNonConfigurato, ProviderNonRaggiungibile

    if isinstance(errore, ProviderNonConfigurato):
        return "Il linguaggio libero non è ancora configurato: manca la chiave del modello."
    if isinstance(errore, ProviderNonRaggiungibile):
        return "Non riesco a contattare il modello adesso. Riprova fra poco."
    return "Non sono riuscito a interpretare il messaggio."


def annulla(
    conn: sqlite3.Connection,
    ora: datetime,
    azione: Azione,
    *,
    identificatore: int,
    giorni: int = 1,
) -> str:
    """Disfà l'ultima azione dell'assistente. Ritorna cosa dire all'utente.

    Serve perché l'interpretazione è automatica: se il modello sbaglia, tornare
    indietro dev'essere un tap, non una caccia al task creato per errore.
    """
    try:
        if azione is Azione.AGGIUNGI_TASK:
            titolo = dom_task.leggi(conn, identificatore).titolo
            dom_task.elimina(conn, identificatore)
            return f"Annullato: «{titolo}» non è più fra i task."
        if azione is Azione.COMPLETA_TASK:
            task = dom_task.imposta_fatto(conn, identificatore, False, ora)
            return f"Riaperto: {task.titolo}"
        if azione is Azione.RINVIA_TASK:
            task = dom_task.annulla_rinvio(conn, identificatore, giorni)
            etichetta = etichetta_scadenza(task.scadenza, ora) or "senza scadenza"
            return f"Rinvio annullato: {task.titolo} — {etichetta}"
        if azione is Azione.AGGIUNGI_SPESA:
            nome = dom_lista.leggi(conn, identificatore).nome
            dom_lista.elimina(conn, identificatore)
            return f"Annullato: «{nome}» non è più sulla lista."
        if azione is Azione.SEGNA_PRESO:
            voce = dom_lista.imposta_preso(conn, identificatore, False, ora)
            return f"Rimesso sulla lista: {voce.nome}"
    except (dom_task.TaskInesistente, dom_lista.VoceInesistente):
        return "Quella voce non esiste più: niente da annullare."
    return "Non c'è niente da annullare."
