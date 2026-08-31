"""La whitelist di §9: risponde solo al mittente autorizzato, nessun altro.

L'applicazione si costruisce senza contattare Telegram, quindi si può
controllare davvero quali handler accettano quale aggiornamento, invece di
fidarsi della lettura del codice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from telegram import Bot, CallbackQuery, Chat, Message, MessageEntity, Update, User
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler

from custode_bot.applicazione import crea_applicazione
from custode_bot.config import ImpostazioniBot
from custode_bot.main import _mancanti
from custode_core.config import Settings

IO = 424242
ESTRANEO = 999999


class _BotFinto:
    """Il minimo che serve a `CommandHandler.check_update`: il proprio username.

    Un `Bot` vero lo saprebbe solo dopo una chiamata a Telegram; qui i test
    devono restare offline.
    """

    username = "custode_bot"


@pytest.fixture
def app(db_path: Path) -> Application:
    return crea_applicazione(
        Settings(ambiente="test", db_path=db_path),
        ImpostazioniBot(bot_token="123456:FINTO", allowed_user_id=IO),
    )


def _messaggio(user_id: int, testo: str) -> Update:
    utente = User(id=user_id, first_name="Tizio", is_bot=False)
    entita = (
        [MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=len(testo.split()[0]))]
        if testo.startswith("/")
        else []
    )
    messaggio = Message(
        message_id=1,
        date=datetime.now(tz=UTC),
        chat=Chat(id=user_id, type=Chat.PRIVATE),
        from_user=utente,
        text=testo,
        entities=entita,
    )
    messaggio.set_bot(cast(Bot, _BotFinto()))
    return Update(update_id=1, message=messaggio)


def _handler_che_accettano(app: Application, update: Update) -> list[object]:
    """Gli handler, in tutti i gruppi, che prenderebbero in carico l'aggiornamento.

    `check_update` non torna un booleano: `None` quando non applica, e un
    risultato utile (per i comandi, la tupla degli argomenti) quando applica —
    quindi si guarda la verità del valore, non l'identità con `False`.
    """
    accettati: list[object] = []
    for handlers in app.handlers.values():
        accettati.extend(h for h in handlers if h.check_update(update))
    return accettati


@pytest.mark.parametrize(
    "comando",
    ["/oggi", "/task", "/lista", "/aiuto", "/start", "/nuovo x", "/aggiungi x", "/svuota"],
)
def test_i_comandi_rispondono_al_mittente_autorizzato(app: Application, comando: str) -> None:
    accettati = _handler_che_accettano(app, _messaggio(IO, comando))
    assert any(isinstance(h, CommandHandler) for h in accettati), comando


@pytest.mark.parametrize("comando", ["/oggi", "/task", "/lista", "/aiuto", "/nuovo x", "/svuota"])
def test_nessun_comando_risponde_a_un_estraneo(app: Application, comando: str) -> None:
    accettati = _handler_che_accettano(app, _messaggio(ESTRANEO, comando))
    assert not any(isinstance(h, CommandHandler) for h in accettati), comando


def test_a_un_estraneo_non_risponde_nemmeno_il_fallback(app: Application) -> None:
    """Anche il messaggio libero: solo l'handler che logga, che non risponde."""
    accettati = _handler_che_accettano(app, _messaggio(ESTRANEO, "ciao"))
    assert all(isinstance(h, MessageHandler) for h in accettati)
    # L'unico che accetta è quello di logging, nel gruppo 1.
    assert [h for h in app.handlers[1] if h.check_update(_messaggio(ESTRANEO, "ciao"))]
    assert not [h for h in app.handlers[0] if h.check_update(_messaggio(ESTRANEO, "ciao"))]


def test_al_mittente_autorizzato_il_testo_libero_risponde(app: Application) -> None:
    accettati = [h for h in app.handlers[0] if h.check_update(_messaggio(IO, "ciao"))]
    assert len(accettati) == 1
    assert isinstance(accettati[0], MessageHandler)


def test_i_bottoni_sono_gestiti(app: Application) -> None:
    utente = User(id=IO, first_name="Tizio", is_bot=False)
    query = CallbackQuery(id="1", from_user=utente, chat_instance="1", data="t:fatto:1:t")
    update = Update(update_id=1, callback_query=query)
    assert any(isinstance(h, CallbackQueryHandler) for h in _handler_che_accettano(app, update))


def test_una_configurazione_incompleta_viene_segnalata() -> None:
    assert _mancanti(ImpostazioniBot(bot_token="", allowed_user_id=0)) == [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_ID",
    ]
    assert _mancanti(ImpostazioniBot(bot_token="x", allowed_user_id=0)) == [
        "TELEGRAM_ALLOWED_USER_ID"
    ]
    assert _mancanti(ImpostazioniBot(bot_token="x", allowed_user_id=1)) == []


def test_senza_user_id_la_whitelist_e_vuota_non_aperta(db_path: Path) -> None:
    """Il default `allowed_user_id=0` non deve significare "chiunque"."""
    app = crea_applicazione(
        Settings(ambiente="test", db_path=db_path),
        ImpostazioniBot(bot_token="123456:FINTO", allowed_user_id=0),
    )
    for user_id in (IO, ESTRANEO, 1):
        accettati = _handler_che_accettano(app, _messaggio(user_id, "/task"))
        assert not any(isinstance(h, CommandHandler) for h in accettati)
