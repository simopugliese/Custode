"""Il bot per intero: aggiornamento → whitelist → handler → database → risposta.

Non serve un token: al posto della rete c'è un bot finto che registra cosa
verrebbe spedito, e il resto della catena (filtri, handler, dominio, SQLite) è
esattamente quello che gira in produzione.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from telegram import Bot, CallbackQuery, Chat, Message, MessageEntity, Update, User
from telegram.ext import Application

from custode_bot.applicazione import crea_applicazione
from custode_bot.config import ImpostazioniBot
from custode_core.config import Settings
from custode_core.db import connessione
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import task as dom_task

pytestmark = pytest.mark.integration

IO = 424242
ESTRANEO = 999999


@dataclass
class BotFinto:
    """Al posto della rete: tiene traccia di cosa il bot avrebbe spedito.

    I messaggi nuovi e le modifiche finiscono nella stessa lista, in ordine:
    dal punto di vista di chi guarda il telefono sono la stessa sequenza.
    """

    username: str = "custode_bot"
    messaggi: list[tuple[str, str]] = field(default_factory=list)
    risposte_ai_tap: int = 0

    async def send_message(self, *_: Any, **kwargs: Any) -> None:
        self.messaggi.append(("nuovo", kwargs.get("text", "")))

    async def edit_message_text(self, *_: Any, **kwargs: Any) -> None:
        self.messaggi.append(("modifica", kwargs.get("text", "")))

    async def answer_callback_query(self, *_: Any, **__: Any) -> None:
        self.risposte_ai_tap += 1

    @property
    def ultimo(self) -> str:
        return self.messaggi[-1][1]

    @property
    def inviati(self) -> list[str]:
        return [testo for tipo, testo in self.messaggi if tipo == "nuovo"]

    @property
    def modificati(self) -> list[str]:
        return [testo for tipo, testo in self.messaggi if tipo == "modifica"]


@pytest.fixture
def finto() -> BotFinto:
    return BotFinto()


@pytest.fixture
def app(db_path: Path) -> Application:
    applicazione = crea_applicazione(
        Settings(ambiente="test", db_path=db_path),
        ImpostazioniBot(bot_token="123456:FINTO", allowed_user_id=IO),
    )
    # `Application.initialize()` chiamerebbe Telegram (getMe) e avvierebbe
    # l'updater: qui serve solo lo smistamento degli aggiornamenti, quindi si
    # dichiara inizializzata senza rete. È l'unico appiglio che
    # python-telegram-bot lascia per provare gli handler offline.
    applicazione._initialized = True
    return applicazione


def _manda(app: Application, finto: BotFinto, testo: str, da: int = IO) -> None:
    entita = (
        [MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=len(testo.split()[0]))]
        if testo.startswith("/")
        else []
    )
    messaggio = Message(
        message_id=1,
        date=datetime.now(tz=UTC),
        chat=Chat(id=da, type=Chat.PRIVATE),
        from_user=User(id=da, first_name="Tizio", is_bot=False),
        text=testo,
        entities=entita,
    )
    messaggio.set_bot(cast(Bot, finto))
    asyncio.run(app.process_update(Update(update_id=1, message=messaggio)))


def _tap(app: Application, finto: BotFinto, dato: str, da: int = IO) -> None:
    query = CallbackQuery(
        id="1",
        from_user=User(id=da, first_name="Tizio", is_bot=False),
        chat_instance="1",
        data=dato,
        message=Message(
            message_id=1,
            date=datetime.now(tz=UTC),
            chat=Chat(id=da, type=Chat.PRIVATE),
        ),
    )
    query.set_bot(cast(Bot, finto))
    # `edit_message_text` passa per il messaggio interno, che ha bisogno del
    # suo riferimento al bot come lo avrebbe arrivando da Telegram.
    if query.message is not None:
        query.message.set_bot(cast(Bot, finto))
    asyncio.run(app.process_update(Update(update_id=2, callback_query=query)))


def test_aiuto(app: Application, finto: BotFinto) -> None:
    _manda(app, finto, "/aiuto")
    assert "/task" in finto.ultimo


def test_un_task_creato_dal_bot_finisce_sul_database(
    app: Application, finto: BotFinto, db_path: Path
) -> None:
    _manda(app, finto, "/nuovo Chiamare l'officina")

    assert "Quando scade?" in finto.ultimo
    with connessione(db_path) as conn:
        creati = dom_task.elenco(conn)
    assert [t.titolo for t in creati] == ["Chiamare l'officina"]
    assert creati[0].origine == "telegram"


def test_giro_completo_creazione_scadenza_elenco_spunta(
    app: Application, finto: BotFinto, db_path: Path
) -> None:
    _manda(app, finto, "/nuovo Pagare la bolletta")
    with connessione(db_path) as conn:
        task_id = dom_task.elenco(conn)[0].id

    # I bottoni della scadenza, poi l'elenco, poi la spunta: come dal telefono.
    _tap(app, finto, f"t:sc-oggi:{task_id}:t")
    _manda(app, finto, "/task")
    assert "Pagare la bolletta" in finto.ultimo

    _tap(app, finto, f"t:fatto:{task_id}:t")
    with connessione(db_path) as conn:
        assert dom_task.leggi(conn, task_id).fatto is True
    assert "Nessun task aperto" in finto.ultimo
    assert finto.risposte_ai_tap == 2  # ogni tap riceve la sua conferma


def test_lista_della_spesa_dal_bot(app: Application, finto: BotFinto, db_path: Path) -> None:
    _manda(app, finto, "/aggiungi latte")
    _manda(app, finto, "/aggiungi mele")
    _manda(app, finto, "/lista")
    assert "latte" in finto.ultimo and "mele" in finto.ultimo

    with connessione(db_path) as conn:
        voce_id = dom_lista.elenco(conn)[0].id
    _tap(app, finto, f"s:preso:{voce_id}:l")
    with connessione(db_path) as conn:
        assert dom_lista.leggi(conn, voce_id).preso is True


def test_svuota_chiede_conferma_prima_di_cancellare(
    app: Application, finto: BotFinto, db_path: Path
) -> None:
    _manda(app, finto, "/aggiungi latte")
    with connessione(db_path) as conn:
        voce_id = dom_lista.elenco(conn)[0].id
    _tap(app, finto, f"s:preso:{voce_id}:l")

    _manda(app, finto, "/svuota")
    assert "Tolgo" in finto.ultimo
    with connessione(db_path) as conn:
        assert len(dom_lista.elenco(conn)) == 1  # non ha ancora cancellato niente

    _tap(app, finto, "x:svuota:si:l")
    with connessione(db_path) as conn:
        assert dom_lista.elenco(conn) == []


def test_al_testo_libero_spiega_che_servono_i_comandi(app: Application, finto: BotFinto) -> None:
    _manda(app, finto, "aggiungi il latte per favore")
    assert "solo i comandi" in finto.ultimo


def test_a_un_estraneo_il_bot_non_risponde(
    app: Application, finto: BotFinto, db_path: Path
) -> None:
    """§9: ogni altro mittente viene ignorato, senza nemmeno una risposta."""
    _manda(app, finto, "/nuovo task di un estraneo", da=ESTRANEO)
    _manda(app, finto, "/task", da=ESTRANEO)
    _manda(app, finto, "ciao", da=ESTRANEO)

    assert finto.inviati == []
    assert finto.modificati == []
    with connessione(db_path) as conn:
        assert dom_task.elenco(conn) == []


def test_un_estraneo_non_puo_nemmeno_premere_un_bottone(
    app: Application, finto: BotFinto, db_path: Path
) -> None:
    _manda(app, finto, "/nuovo mio task")
    with connessione(db_path) as conn:
        task_id = dom_task.elenco(conn)[0].id
    finto.messaggi.clear()

    _tap(app, finto, f"t:fatto:{task_id}:t", da=ESTRANEO)

    with connessione(db_path) as conn:
        assert dom_task.leggi(conn, task_id).fatto is False
    assert finto.modificati == []
