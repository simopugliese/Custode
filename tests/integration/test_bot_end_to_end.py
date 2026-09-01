"""Il bot per intero: aggiornamento → whitelist → handler → database → risposta.

Non serve un token: al posto della rete c'è un bot finto che registra cosa
verrebbe spedito, e il resto della catena (filtri, handler, dominio, SQLite) è
esattamente quello che gira in produzione.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from telegram import Bot, CallbackQuery, Chat, Message, MessageEntity, Update, User, Voice
from telegram.ext import Application

from custode_bot import azioni
from custode_bot.applicazione import crea_applicazione
from custode_bot.config import ImpostazioniBot
from custode_bot.trascrizione import ClientWhisper, TrascrizioneNonRiuscita
from custode_core.config import Settings
from custode_core.db import connessione
from custode_core.dominio import diario as dom_diario
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import task as dom_task
from custode_core.formato import adesso
from custode_router.compiti import Compito
from custode_router.errori import ProviderNonConfigurato

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

    async def send_chat_action(self, *_: Any, **__: Any) -> None:
        """«sta scrivendo…»: il bot lo manda prima delle attese lunghe."""

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


class RouterFinto:
    """Al posto del modello: risponde l'intenzione che gli si dice."""

    def __init__(self) -> None:
        self.risposta: dict[str, Any] = {"azione": "nessuna"}
        # Per compito, quando un test ne esercita più d'uno nello stesso giro:
        # l'interpretazione del messaggio e il riassunto del diario tornano
        # forme diverse (§6 li manda anche a provider diversi).
        self.per_compito: dict[Any, dict[str, Any]] = {}
        self.errore: Exception | None = None
        self.messaggi_visti: list[str] = []
        self.compiti_visti: list[Any] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.messaggi_visti.append(kwargs.get("utente", ""))
        self.compiti_visti.append(compito)
        if self.errore is not None:
            raise self.errore
        return self.per_compito.get(compito, self.risposta)


class WhisperFinto(ClientWhisper):
    """Al posto del servizio di trascrizione."""

    def __init__(self) -> None:
        super().__init__("http://whisper-finto")
        self.testo = "sto finendo il latte"
        self.errore: Exception | None = None
        self.audio_ricevuto: list[bytes] = []

    def trascrivi(self, audio: bytes, nome_file: str = "vocale.ogg") -> str:
        self.audio_ricevuto.append(audio)
        if self.errore is not None:
            raise self.errore
        return self.testo


@pytest.fixture
def modello() -> RouterFinto:
    return RouterFinto()


@pytest.fixture
def whisper() -> WhisperFinto:
    return WhisperFinto()


@pytest.fixture
def app(db_path: Path, modello: RouterFinto, whisper: WhisperFinto) -> Application:
    applicazione = crea_applicazione(
        Settings(ambiente="test", db_path=db_path),
        ImpostazioniBot(bot_token="123456:FINTO", allowed_user_id=IO),
        router=modello,  # type: ignore[arg-type]
        whisper=whisper,
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
    messaggio.chat.set_bot(cast(Bot, finto))
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


class _FileFinto:
    def __init__(self, contenuto: bytes):
        self._contenuto = contenuto

    async def download_as_bytearray(self) -> bytearray:
        return bytearray(self._contenuto)


class _VoceFinta:
    def __init__(self, contenuto: bytes, durata: int):
        self.duration = durata
        self._contenuto = contenuto

    async def get_file(self) -> _FileFinto:
        return _FileFinto(self._contenuto)


def _manda_vocale(
    app: Application, finto: BotFinto, audio: bytes, da: int = IO, durata: int = 5
) -> None:
    messaggio = Message(
        message_id=1,
        date=datetime.now(tz=UTC),
        chat=Chat(id=da, type=Chat.PRIVATE),
        from_user=User(id=da, first_name="Tizio", is_bot=False),
        voice=Voice(file_id="f", file_unique_id="u", duration=durata),
    )
    messaggio.set_bot(cast(Bot, finto))
    messaggio.chat.set_bot(cast(Bot, finto))
    # Il download passa per l'oggetto Voice: qui lo si sostituisce con uno che
    # restituisce i byte senza rete.
    object.__setattr__(messaggio, "voice", _VoceFinta(audio, durata))
    asyncio.run(app.process_update(Update(update_id=3, message=messaggio)))


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


def test_il_testo_libero_passa_dal_modello_ed_esegue(
    app: Application, finto: BotFinto, modello: RouterFinto, db_path: Path
) -> None:
    modello.risposta = {"azione": "aggiungi_voce_spesa", "titolo": "latte"}

    _manda(app, finto, "sto finendo il latte")

    assert "Aggiunto alla lista: latte" in finto.ultimo
    with connessione(db_path) as conn:
        assert [v.nome for v in dom_lista.elenco(conn)] == ["latte"]
    # Il modello ha visto il messaggio e il contesto di ciò che esiste già.
    assert "sto finendo il latte" in modello.messaggi_visti[0]


def test_il_testo_libero_lascia_un_bottone_per_annullare(
    app: Application, finto: BotFinto, modello: RouterFinto, db_path: Path
) -> None:
    """L'interpretazione è automatica: disfare deve costare un tap."""
    modello.risposta = {"azione": "aggiungi_task", "titolo": "Cosa sbagliata"}
    _manda(app, finto, "ricordami una cosa sbagliata")

    with connessione(db_path) as conn:
        task_id = dom_task.elenco(conn)[0].id

    _tap(app, finto, f"x:annulla:aggiungi_task-{task_id}-1:t")

    with connessione(db_path) as conn:
        assert dom_task.elenco(conn) == []
    assert "Annullato" in finto.ultimo


def test_un_vocale_passa_da_whisper_e_poi_dallo_stesso_percorso(
    app: Application,
    finto: BotFinto,
    modello: RouterFinto,
    whisper: WhisperFinto,
    db_path: Path,
) -> None:
    """§8.1: via voce non cambia niente, cambia solo l'ingresso."""
    whisper.testo = "sto finendo il latte"
    modello.risposta = {"azione": "aggiungi_voce_spesa", "titolo": "latte"}

    _manda_vocale(app, finto, b"OggS-finto")

    assert whisper.audio_ricevuto == [b"OggS-finto"]
    # Si rimanda anche la trascrizione, per capire di chi è la colpa se sbaglia.
    assert "sto finendo il latte" in finto.ultimo
    assert "Aggiunto alla lista: latte" in finto.ultimo
    with connessione(db_path) as conn:
        assert [v.nome for v in dom_lista.elenco(conn)] == ["latte"]


def test_un_vocale_che_non_si_capisce(
    app: Application, finto: BotFinto, whisper: WhisperFinto, db_path: Path
) -> None:
    whisper.errore = TrascrizioneNonRiuscita("audio incomprensibile")
    _manda_vocale(app, finto, b"rumore")
    assert "Non sono riuscito a trascrivere" in finto.ultimo
    with connessione(db_path) as conn:
        assert dom_lista.elenco(conn) == []


def test_un_vocale_troppo_lungo_non_viene_nemmeno_scaricato(
    app: Application, finto: BotFinto, whisper: WhisperFinto
) -> None:
    _manda_vocale(app, finto, b"lunghissimo", durata=9999)
    assert "troppo lungo" in finto.ultimo
    assert whisper.audio_ricevuto == []


def test_senza_chiave_del_modello_lo_dice(
    app: Application, finto: BotFinto, modello: RouterFinto
) -> None:
    modello.errore = ProviderNonConfigurato("manca la chiave")
    _manda(app, finto, "aggiungi il latte")
    assert "non è ancora configurato" in finto.ultimo


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


# — diario (§8.4): il giro completo da Telegram —


def _adesso() -> datetime:
    """L'ora con cui ragiona il bot: quella vera nel fuso configurato.

    A differenza dell'API il bot non riceve "adesso" iniettato, quindi la voce
    di diario finisce sul giorno di calendario corrente — ed è su quello che i
    test devono guardare.
    """
    return adesso(Settings(ambiente="test").timezone)


def _oggi() -> date:
    return _adesso().date()


def test_giro_completo_del_diario(
    app: Application, finto: BotFinto, modello: RouterFinto, db_path: Path
) -> None:
    """Racconto → /diario → bozza → approvo. Nel diario entra solo l'approvato."""
    modello.per_compito[Compito.PARSING_LISTA_SPESA] = {
        "azione": "annota_diario",
        "titolo": "mattina in biblioteca, pomeriggio buttato",
    }
    modello.per_compito[Compito.RIASSUNTO_DIARIO] = {
        "riassunto": "Hai studiato la mattina, il pomeriggio è andato perso.",
        "tag": ["studio", "umore"],
    }

    _manda(app, finto, "stamattina biblioteca, poi pomeriggio buttato")
    assert "Annotato nel diario" in finto.ultimo

    # Finché non si chiude la giornata, nel diario non c'è ancora niente.
    with connessione(db_path) as conn:
        voce = dom_diario.leggi_giorno(conn, _oggi())
        assert voce is not None and voce.riassunto_approvato is None

    _manda(app, finto, "/diario")
    assert "Hai studiato la mattina" in finto.ultimo
    assert "solo se lo approvi" in finto.ultimo

    with connessione(db_path) as conn:
        voce = dom_diario.leggi_giorno(conn, _oggi())
        assert voce is not None
        assert voce.riassunto_approvato is None  # ancora solo una bozza

    _tap(app, finto, azioni.diario("approva", voce.id))
    assert "già nel diario" in finto.ultimo

    with connessione(db_path) as conn:
        approvata = dom_diario.leggi(conn, voce.id)
    assert approvata.riassunto_approvato == "Hai studiato la mattina, il pomeriggio è andato perso."
    assert approvata.tag == ["studio", "umore"]


def test_il_diario_si_puo_riscrivere_a_parole_proprie(
    app: Application, finto: BotFinto, modello: RouterFinto, db_path: Path
) -> None:
    """§8.4 punto 5: «approvi così com'è o lo modifichi»."""
    modello.per_compito[Compito.PARSING_LISTA_SPESA] = {
        "azione": "annota_diario",
        "titolo": "giornata storta",
    }
    modello.per_compito[Compito.RIASSUNTO_DIARIO] = {
        "riassunto": "Versione del modello.",
        "tag": ["umore"],
    }

    _manda(app, finto, "che giornata storta")
    _manda(app, finto, "/diario")

    with connessione(db_path) as conn:
        voce = dom_diario.leggi_giorno(conn, _oggi())
    assert voce is not None

    _tap(app, finto, azioni.diario("modifica", voce.id))
    assert "parola per parola" in finto.ultimo

    prima = len(modello.messaggi_visti)
    _manda(app, finto, "Giornata storta, ma almeno ho chiuso il capitolo 3.")

    # La riscrittura non passa dal modello: entra nel diario com'è stata scritta.
    assert len(modello.messaggi_visti) == prima
    with connessione(db_path) as conn:
        approvata = dom_diario.leggi(conn, voce.id)
    assert approvata.riassunto_approvato == "Giornata storta, ma almeno ho chiuso il capitolo 3."


def test_un_vocale_raccontato_entra_nel_diario(
    app: Application,
    finto: BotFinto,
    modello: RouterFinto,
    whisper: WhisperFinto,
    db_path: Path,
) -> None:
    """§8.1: dettare e scrivere sono la stessa cosa, anche per il diario."""
    whisper.testo = "oggi mi sono sentito addosso tutta la settimana"
    modello.per_compito[Compito.PARSING_LISTA_SPESA] = {
        "azione": "annota_diario",
        "titolo": "mi sono sentito addosso tutta la settimana",
    }

    _manda_vocale(app, finto, b"audio")

    assert "Annotato nel diario" in finto.ultimo
    with connessione(db_path) as conn:
        voce = dom_diario.leggi_giorno(conn, _oggi())
    assert voce is not None
    assert (voce.n_vocali, voce.n_messaggi) == (1, 0)


def test_senza_chiave_di_claude_il_materiale_non_si_perde(
    app: Application, finto: BotFinto, modello: RouterFinto, db_path: Path
) -> None:
    """Il guasto del modello non deve costare quello che hai già raccontato."""
    with connessione(db_path) as conn:
        dom_diario.aggiungi_materiale(conn, giorno=_oggi(), testo="giornata piena", ora=_adesso())

    modello.errore = ProviderNonConfigurato("manca la chiave")
    _manda(app, finto, "/diario")

    assert "chiave di Claude" in finto.ultimo
    with connessione(db_path) as conn:
        voce = dom_diario.leggi_giorno(conn, _oggi())
    assert voce is not None and voce.grezzo == "giornata piena"
