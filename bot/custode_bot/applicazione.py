"""Adattatore verso `python-telegram-bot`.

Qui sta solo il collegamento: prendere l'aggiornamento, aprire una connessione,
chiamare la funzione pura corrispondente in `risposte.py`, spedire il
risultato. Tutto ciò che decide *cosa* dire vive lì, ed è testabile senza
Telegram.

Il bot lavora in **long polling**: è lui a chiamare Telegram, quindi non serve
alcuna porta in ingresso né un tunnel già configurato (§2, §9).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from datetime import datetime
from html import escape
from typing import Any

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from custode_bot import risposte
from custode_bot.config import ImpostazioniBot
from custode_bot.risposte import Risposta
from custode_bot.trascrizione import ClientWhisper, TrascrizioneNonRiuscita
from custode_core.config import Settings
from custode_core.db import connect
from custode_core.formato import adesso
from custode_core.migrazioni import migra
from custode_router import Router

log = logging.getLogger("custode.bot")

COMANDI = [
    BotCommand("oggi", "Cosa c'è oggi"),
    BotCommand("task", "I task aperti"),
    BotCommand("nuovo", "Aggiungi un task"),
    BotCommand("lista", "La lista della spesa"),
    BotCommand("aggiungi", "Aggiungi alla lista della spesa"),
    BotCommand("svuota", "Togli dalla lista le voci già prese"),
    BotCommand("diario", "Chiudi la giornata e leggi il riassunto"),
    BotCommand("profilo", "Cosa ho capito di te"),
    BotCommand("aiuto", "Cosa so fare"),
]


def _tastiera(risposta: Risposta) -> InlineKeyboardMarkup | None:
    if not risposta.bottoni:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(b.testo, callback_data=b.dato) for b in riga]
            for riga in risposta.bottoni
        ]
    )


def crea_applicazione(
    impostazioni: Settings,
    bot: ImpostazioniBot,
    *,
    router: Router | None = None,
    whisper: ClientWhisper | None = None,
) -> Application:
    """Costruisce l'applicazione Telegram con la whitelist già applicata.

    `router` e `whisper` sono iniettabili per i test: in esercizio si
    costruiscono da soli dalle impostazioni.
    """
    instradatore = router or Router()
    trascrittore = whisper or ClientWhisper(bot.whisper_url)

    @contextmanager
    def connessione() -> Iterator[sqlite3.Connection]:
        conn = connect(impostazioni.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def ora() -> datetime:
        return adesso(impostazioni.timezone)

    async def _rispondi(update: Update, risposta: Risposta) -> None:
        messaggio = update.effective_message
        if messaggio is None:
            return
        await messaggio.reply_text(
            risposta.testo, parse_mode=ParseMode.HTML, reply_markup=_tastiera(risposta)
        )

    def comando(
        costruisci: Callable[[sqlite3.Connection, datetime, str], Risposta],
    ) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]:
        """Adatta una funzione di `risposte` a un handler di comando."""

        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            argomento = " ".join(context.args or [])
            with connessione() as conn:
                risposta = costruisci(conn, ora(), argomento)
            await _rispondi(update, risposta)

        return handler

    async def cmd_aiuto(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await _rispondi(update, risposte.aiuto())

    async def cmd_svuota(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        with connessione() as conn:
            risposta = risposte.chiedi_svuota(conn)
        await _rispondi(update, risposta)

    async def cmd_diario(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Chiude la giornata (§8.4). Può volerci qualche secondo: è Claude."""
        messaggio = update.effective_message
        if messaggio is not None:
            # Il riassunto passa da Claude e non è istantaneo: senza un segnale
            # sembra che il comando sia caduto nel vuoto.
            await messaggio.reply_chat_action(ChatAction.TYPING)
        with connessione() as conn:
            risposta = risposte.diario_oggi(conn, ora(), instradatore)
        await _rispondi(update, risposta)

    async def cmd_profilo(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        with connessione() as conn:
            risposta = risposte.profilo(conn)
        await _rispondi(update, risposta)

    async def su_bottone(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        # `CallbackQueryHandler` non accetta un filtro sul mittente come gli
        # altri handler, quindi la whitelist va applicata qui a mano: senza,
        # i bottoni sarebbero l'unica via d'accesso non protetta (§9).
        utente = update.effective_user
        if utente is None or utente.id != bot.allowed_user_id:
            log.warning(
                "tap su un bottone ignorato, mittente non autorizzato (id=%s)",
                utente.id if utente else "sconosciuto",
            )
            return
        # Telegram vuole comunque una risposta al tap, altrimenti il bottone
        # resta a girare sul telefono.
        await query.answer()

        # «Aggiorna il profilo» chiama Claude e non è istantaneo: senza un
        # segnale il tap sembra non aver fatto niente.
        messaggio_query = query.message
        if messaggio_query is not None and (query.data or "").startswith("p:rifondi"):
            await messaggio_query.chat.send_action(ChatAction.TYPING)

        with connessione() as conn:
            risposta = risposte.esegui_azione(conn, ora(), query.data or "", instradatore)

        try:
            await query.edit_message_text(
                risposta.testo, parse_mode=ParseMode.HTML, reply_markup=_tastiera(risposta)
            )
        except BadRequest as errore:
            # L'unico caso atteso: Telegram rifiuta la modifica quando il testo
            # è identico a quello già mostrato. Il messaggio è già giusto, non
            # c'è niente da dire all'utente. Qualunque altro errore deve
            # risalire, invece di sparire in un log di debug.
            if "not modified" not in str(errore).lower():
                raise
            log.debug("messaggio identico, nessuna modifica necessaria")

    async def testo_libero(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        messaggio = update.effective_message
        if messaggio is None or not messaggio.text:
            return
        with connessione() as conn:
            risposta = risposte.messaggio_libero(conn, ora(), messaggio.text, instradatore)
        await _rispondi(update, risposta)

    async def vocale(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Un vocale è un messaggio come gli altri: cambia solo l'ingresso (§8.1)."""
        messaggio = update.effective_message
        voce = messaggio.voice or messaggio.audio if messaggio else None
        if messaggio is None or voce is None:
            return

        durata = getattr(voce, "duration", 0) or 0
        if durata > bot.max_secondi_vocale:
            await _rispondi(
                update, Risposta(testo="Quel vocale è troppo lungo: mandamene uno più corto.")
            )
            return

        try:
            file = await voce.get_file()
            audio = bytes(await file.download_as_bytearray())
            testo = trascrittore.trascrivi(audio)
        except TrascrizioneNonRiuscita as errore:
            log.warning("trascrizione fallita: %s", errore)
            await _rispondi(
                update,
                Risposta(testo="Non sono riuscito a trascrivere il vocale. Riprova o scrivilo."),
            )
            return

        with connessione() as conn:
            risposta = risposte.messaggio_libero(conn, ora(), testo, instradatore, da_vocale=True)
        # Si rimanda anche la trascrizione: se il modello ha capito male, si
        # vede subito se la colpa è di whisper o dell'interpretazione.
        await _rispondi(
            update,
            Risposta(
                testo=f"<i>«{escape(testo)}»</i>\n\n{risposta.testo}", bottoni=risposta.bottoni
            ),
        )

    async def non_autorizzato(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        # Nessuna risposta: a un mittente non autorizzato non si conferma
        # nemmeno che il bot esista (§9). Resta solo la traccia nei log.
        utente = update.effective_user
        log.warning(
            "messaggio ignorato da un mittente non autorizzato (id=%s)",
            utente.id if utente else "sconosciuto",
        )

    # Lo schema si porta in pari qui, prima ancora di parlare con Telegram: se
    # il database non è a posto è meglio saperlo all'avvio che al primo comando.
    # A differenza dell'API il bot non ha un health check con cui dire di essere
    # degradato, quindi l'errore risale e il container riparte (`restart:
    # unless-stopped`) invece di restare in ascolto senza poter fare nulla.
    with connessione() as conn:
        applicate = migra(conn)
    if applicate:
        log.info("migrazioni applicate: %s", ", ".join(applicate))

    async def post_avvio(app: Application) -> None:
        if bot.comandi_pubblici:
            await app.bot.set_my_commands(COMANDI)

    applicazione = ApplicationBuilder().token(bot.bot_token).post_init(post_avvio).build()

    solo_io = filters.User(user_id=bot.allowed_user_id)
    applicazione.add_handler(CommandHandler(["start", "aiuto"], cmd_aiuto, filters=solo_io))
    applicazione.add_handler(
        CommandHandler(
            "oggi",
            comando(lambda conn, ora_, _: risposte.riepilogo_oggi(conn, ora_)),
            filters=solo_io,
        )
    )
    applicazione.add_handler(
        CommandHandler(
            "task", comando(lambda conn, ora_, _: risposte.elenco_task(conn, ora_)), filters=solo_io
        )
    )
    applicazione.add_handler(CommandHandler("nuovo", comando(risposte.nuovo_task), filters=solo_io))
    applicazione.add_handler(
        CommandHandler(
            "lista", comando(lambda conn, _o, _a: risposte.elenco_lista(conn)), filters=solo_io
        )
    )
    applicazione.add_handler(
        CommandHandler("aggiungi", comando(risposte.aggiungi_voce), filters=solo_io)
    )
    applicazione.add_handler(CommandHandler("svuota", cmd_svuota, filters=solo_io))
    applicazione.add_handler(CommandHandler("diario", cmd_diario, filters=solo_io))
    applicazione.add_handler(CommandHandler("profilo", cmd_profilo, filters=solo_io))

    async def su_errore(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("errore non gestito", exc_info=context.error)
        if isinstance(update, Update):
            messaggio = update.effective_message
            if messaggio is not None:
                await messaggio.reply_text("Qualcosa è andato storto. Riprova fra poco.")

    applicazione.add_error_handler(su_errore)
    applicazione.add_handler(CallbackQueryHandler(su_bottone))
    applicazione.add_handler(
        MessageHandler(solo_io & filters.TEXT & ~filters.COMMAND, testo_libero)
    )
    applicazione.add_handler(MessageHandler(solo_io & (filters.VOICE | filters.AUDIO), vocale))

    # Gruppo a parte: gli altri gruppi vengono comunque valutati, così ogni
    # messaggio non autorizzato finisce nei log anche se nessun handler lo serve.
    applicazione.add_handler(MessageHandler(~solo_io, non_autorizzato), group=1)

    return applicazione
