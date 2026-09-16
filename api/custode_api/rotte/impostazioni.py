"""Impostazioni — `GET /api/impostazioni`, `PATCH /api/impostazioni` (§8).

**Solo le manopole che girano qualcosa.** Il contratto della dashboard ha da
sempre più campi di quanti moduli esistano: il digest mattutino (§8.13), l'ora
della voce di diario, le ore di silenzio, le quattro approvazioni, il primo
giorno della settimana. Nessuno di quelli è cablato a niente, e mandarli
vorrebbe dire un interruttore che non interrompe — lo giri, non succede nulla,
e da lì in poi non ti fidi più nemmeno di quelli che funzionano. Si omettono,
che è la regola già scritta in cima al contratto: un campo il cui modulo non è
ancora attivo si **omette**, non si mette a zero.

L'unica eccezione è `checkInMinutiDopo`, il margine di «sei probabilmente a
casa»: §8.10 lo vuole esplicitamente configurabile, e salvarlo adesso è la
stessa scelta di `calendar_events.tipo`, che esisteva prima del tagging.

**Questa pagina è anche l'unico posto da cui si vede che il worker è fermo.**
`sistema.ultimoSyncCalendarioLabel` è il caso che §8.10 lascia scoperto: a
worker morto la pagina Calendario dice «niente in programma», che rispetto
all'archivio è pure vero — solo che l'archivio è di tre giorni fa.

**I segreti non escono di qui** (§9). Le connessioni si vedono, si vede se
hanno una chiave dietro, e la chiave non si legge né si scrive: sta nel `.env`,
come ogni altra credenziale del progetto.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, HTTPException

from custode_api import schemi
from custode_api.dipendenze import (
    BotDip,
    CalendarioDip,
    ConnDip,
    ImpostazioniDip,
    OraDip,
    RouterDip,
)
from custode_bot.config import ImpostazioniBot
from custode_calendario.config import ImpostazioniCalendario
from custode_core.config import Settings, versione
from custode_core.dominio import impostazioni as dom
from custode_core.formato import etichetta_da_quando
from custode_core.registro_job import BACKUP, SYNC_CALENDARIO, ultima_esecuzione
from custode_router import Router
from custode_router.compiti import Compito

router = APIRouter(prefix="/api/impostazioni", tags=["impostazioni"])

MAI_SINCRONIZZATO = "mai"
NESSUN_BACKUP = "mai"


def _connessioni(
    calendario: ImpostazioniCalendario,
    instradatore: Router,
    bot: ImpostazioniBot,
) -> list[schemi.Connessione]:
    """Cosa è collegato, e cosa smette di funzionare se non lo è.

    `dettaglio` non descrive la connessione, dice **cosa ci perdi**: «Telegram:
    collegato» non aiuta nessuno, «senza, niente vocali» sì. È la stessa idea
    di `daGuardareLabel` nella pagina Calendario — il posto dove si vede un
    sintomo è il posto dove va spiegata la causa.
    """
    voci = [
        (
            "Telegram",
            "Il canale principale: comandi, testo libero, vocali e foto (§8.1).",
            bot.configurato(),
            "manca TELEGRAM_BOT_TOKEN o TELEGRAM_ALLOWED_USER_ID",
        ),
        (
            "Google Calendar",
            "Sola lettura, sincronizzato ogni cinque minuti (§8.10).",
            calendario.configurato(),
            "manca CALENDARIO_CLIENT_ID e compagnia — vedi DEPLOY.md § 3-bis",
        ),
        (
            "DeepSeek",
            "Testo libero, lista della spesa, tipo degli impegni (§6).",
            instradatore.configurato_per(Compito.TAG_CALENDARIO),
            "manca ROUTER_DEEPSEEK_API_KEY",
        ),
        (
            "Claude",
            "Riassunto del diario, scontrini, report delle abitudini (§6).",
            instradatore.configurato_per(Compito.RIASSUNTO_DIARIO),
            "manca ROUTER_ANTHROPIC_API_KEY",
        ),
    ]
    return [
        schemi.Connessione(
            nome=nome,
            dettaglio=dettaglio if acceso else f"{dettaglio} Adesso è spento: {perche}.",
            stato="collegato" if acceso else "non_collegato",
        )
        for nome, dettaglio, acceso, perche in voci
    ]


def _da_quando(momento: datetime | None, ora: datetime, *, mai: str) -> str:
    return mai if momento is None else etichetta_da_quando(momento, ora)


def _conta(conn: sqlite3.Connection, tabella: str) -> int:
    quante: int = conn.execute(f"SELECT count(*) AS n FROM {tabella}").fetchone()["n"]
    return quante


def _bot_stato(bot: ImpostazioniBot) -> str:
    """Se il bot è **configurato**, non se è vivo — e la frase lo dice.

    Vivo non si può sapere da qui: il bot non lascia una traccia periodica come
    fa il worker con `job_runs`, e i messaggi che riceve li scrive solo quando
    sono materiale da diario. Scrivere «ultimo messaggio 22 minuti fa» contando
    i frammenti di diario darebbe un numero che sembra una risposta e non lo è —
    una giornata in cui non hai raccontato niente si leggerebbe come un bot
    morto.
    """
    if not bot.configurato():
        return "Bot non configurato: manca TELEGRAM_BOT_TOKEN o TELEGRAM_ALLOWED_USER_ID."
    return "Bot configurato · se risponde si vede solo scrivendogli"


def _nota(salvate: dict[str, datetime]) -> str | None:
    """Cosa vale ancora dal `.env` perché non l'hai mai deciso da qui.

    È la differenza che il `.env` da solo non sa dire: un valore che vedi in
    pagina può essere quello con cui l'installazione è nata o quello che hai
    scelto tu, e la prima volta che ne cambi uno conta sapere quale delle due.
    """
    mancanti = [voce for voce in dom.REGISTRO if voce.chiave not in salvate]
    if not mancanti:
        return None
    if len(mancanti) == len(dom.REGISTRO):
        return "Non hai ancora cambiato niente da qui: quello che vedi viene dal .env del Pi."
    quante = len(mancanti)
    return (
        f"{quante} di queste {'viene' if quante == 1 else 'vengono'} ancora dal .env del Pi:"
        " dal primo salvataggio vale quello che scegli qui."
    )


def _leggi(
    conn: sqlite3.Connection,
    ora: datetime,
    settings: Settings,
    calendario: ImpostazioniCalendario,
    instradatore: Router,
    bot: ImpostazioniBot,
) -> schemi.ImpostazioniData:
    sync = ultima_esecuzione(conn, SYNC_CALENDARIO)
    return schemi.ImpostazioniData(
        botStatoLabel=_bot_stato(bot),
        apiStatoLabel=f"API online · {ora.strftime('%H:%M')}",
        orari=schemi.OrariImpostazioni(
            # Il default non è una costante di questo modulo: è il valore del
            # `.env`, cioè la configurazione con cui l'installazione è nata.
            # Dal primo salvataggio vince la riga in tabella.
            riepilogoSettimanaleGiorno=dom.RIEPILOGO_GIORNO.leggi(conn),
            riepilogoSettimanaleOra=dom.RIEPILOGO_ORA.leggi(conn),
            checkInMinutiDopo=dom.CHECK_IN_MINUTI_DOPO.leggi(conn),
        ),
        budget=schemi.BudgetImpostazioni(
            settimanale=dom.BUDGET_SETTIMANALE.leggi(conn, default=settings.budget_settimanale),
        ),
        connessioni=_connessioni(calendario, instradatore, bot),
        dati=schemi.DatiImpostazioni(
            vociDiario=_conta(conn, "diary_entries"),
            speseRegistrate=_conta(conn, "expenses"),
            ultimoBackupLabel=_da_quando(ultima_esecuzione(conn, BACKUP), ora, mai=NESSUN_BACKUP),
        ),
        sistema=schemi.SistemaImpostazioni(
            apiOnline=True,
            ultimoSyncCalendarioLabel=_da_quando(sync, ora, mai=MAI_SINCRONIZZATO),
            versione=versione(),
        ),
        notaLabel=_nota(dom.salvate(conn)),
    )


@router.get("", response_model=schemi.ImpostazioniData, response_model_exclude_none=True)
def pagina_impostazioni(
    conn: ConnDip,
    ora: OraDip,
    settings: ImpostazioniDip,
    calendario: CalendarioDip,
    instradatore: RouterDip,
    bot: BotDip,
) -> schemi.ImpostazioniData:
    return _leggi(conn, ora, settings, calendario, instradatore, bot)


@router.patch("", response_model=schemi.ImpostazioniData, response_model_exclude_none=True)
def aggiorna(
    corpo: schemi.ModificaImpostazioni,
    conn: ConnDip,
    ora: OraDip,
    settings: ImpostazioniDip,
    calendario: CalendarioDip,
    instradatore: RouterDip,
    bot: BotDip,
) -> schemi.ImpostazioniData:
    """Cambia solo i campi che arrivano, e risponde con la pagina intera.

    **Si guarda `model_fields_set` e non il valore**, perché per il budget
    `null` e «assente» sono due cose diverse: `null` **cancella** il budget e
    riporta la Home a non disegnare il blocco delle spese, mentre un campo che
    non arriva è un campo che non volevi toccare. Distinguere i due casi dal
    solo valore è impossibile, e confonderli vorrebbe dire che ogni modifica a
    un orario cancella il budget.

    Il cambio è attivo **subito**, senza riavviare niente: l'API apre una
    connessione per richiesta e il worker rilegge in cima a ogni giro, quindi al
    più tardi fra cinque minuti.
    """
    # Tutto o niente. La connessione dell'API è in autocommit (`db.py`), quindi
    # senza questa transazione una `PATCH` con due campi di cui il secondo è
    # storto salverebbe il primo e rifiuterebbe la richiesta: il riepilogo
    # resterebbe spostato a un giorno che non hai scelto, e la risposta direbbe
    # che non è cambiato niente. È lo stesso ragionamento del runner delle
    # migrazioni, e qui costa due righe.
    conn.execute("BEGIN IMMEDIATE")
    try:
        if corpo.orari is not None:
            _scrivi_orari(conn, corpo.orari, ora)
        if corpo.budget is not None:
            _scrivi_budget(conn, corpo.budget, ora)
    except dom.ValoreNonValido as errore:
        conn.execute("ROLLBACK")
        raise HTTPException(status_code=422, detail=f"{errore}.") from errore
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")

    return _leggi(conn, ora, settings, calendario, instradatore, bot)


def _scrivi_orari(conn: sqlite3.Connection, orari: schemi.ModificaOrari, ora: datetime) -> None:
    dati = orari.model_dump(exclude_unset=True)
    for campo, voce in (
        ("riepilogoSettimanaleGiorno", dom.RIEPILOGO_GIORNO),
        ("riepilogoSettimanaleOra", dom.RIEPILOGO_ORA),
        ("checkInMinutiDopo", dom.CHECK_IN_MINUTI_DOPO),
    ):
        if campo in dati:
            voce.scrivi(conn, dati[campo], ora)


def _scrivi_budget(conn: sqlite3.Connection, budget: schemi.ModificaBudget, ora: datetime) -> None:
    if "settimanale" not in budget.model_fields_set:
        return
    # Un `null` esplicito si **salva** come `null`, non cancella la riga. Sono
    # due cose diverse: senza riga vale ancora il `.env`, e se lì c'è un budget
    # svuotare il campo in pagina te lo farebbe ricomparire al ricaricamento
    # successivo — cioè la pagina rifiuterebbe la cosa che le hai appena
    # chiesto, senza dire niente. Con la riga a `null` la scelta è tua e resta.
    dom.BUDGET_SETTIMANALE.scrivi(conn, budget.settimanale, ora)
