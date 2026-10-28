"""Client HTTP che parla con l'API vera, su un database vero su disco."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import SettingsConfigDict

from custode_api.dipendenze import prendi_ora
from custode_api.main import crea_app
from custode_bot.config import ImpostazioniBot
from custode_calendario.config import ImpostazioniCalendario
from custode_core.config import Settings
from custode_meteo import Previsione
from custode_meteo.config import ImpostazioniMeteo
from custode_worker.config import ImpostazioniWorker

CAMPI_MESSAGGIO = frozenset({"segnale", "segnale_estratto", "segnale_domanda"})


class RouterFinto:
    """Al posto del modello: risponde l'intenzione che gli si dice."""

    def __init__(self) -> None:
        self.risposta: dict[str, Any] = {"azioni": [{"azione": "nessuna"}]}
        self.errore: Exception | None = None
        self.messaggi_visti: list[str] = []
        self.verifica: Exception | None = None
        """L'errore che `verifica_per` alza: la chiave c'è ma il provider la respinge."""
        self.compiti_accesi = True
        """Se i compiti di §6 hanno una chiave dietro. Un test che vuole vedere
        la pagina col modello spento lo mette a `False`."""

    def interpreta_come(self, *azioni: dict[str, Any]) -> None:
        """Fa rispondere all'interprete queste azioni, nella forma vera.

        I test descrivono un'azione come un dizionario piatto — che si legge
        meglio — e qui finisce nella lista `azioni` dello schema, coi campi che
        riguardano il messaggio intero (il segnale) lasciati fuori. Chi invece
        deve fingere una risposta di **Claude** (una categoria di spesa, un
        riassunto) continua a scrivere `risposta` a mano: ha un'altra forma.
        """
        self.risposta = {
            "azioni": [{k: v for k, v in a.items() if k not in CAMPI_MESSAGGIO} for a in azioni],
            **{k: v for a in azioni for k, v in a.items() if k in CAMPI_MESSAGGIO},
        }

    def configurato_per(self, compito: Any) -> bool:
        return self.compiti_accesi

    def verifica_per(self, compito: Any) -> None:
        if self.verifica is not None:
            raise self.verifica

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.messaggi_visti.append(kwargs.get("utente", ""))
        if self.errore is not None:
            raise self.errore
        return self.risposta


@pytest.fixture
def modello() -> RouterFinto:
    return RouterFinto()


@pytest.fixture
def budget() -> float | None:
    """Nessun budget: è come nasce un'installazione (§8.5).

    Un test che vuole il blocco spese della Home ridefinisce questa fixture.
    """
    return None


class _CalendarioDiTest(ImpostazioniCalendario):
    """Ignora il `.env` dello sviluppatore, come `_SettingsDiTest`.

    Senza, un `.env` locale con le credenziali vere farebbe comparire il blocco
    calendario della Home in macchina e sparire in CI — cioè un test che dipende
    da cosa c'è sul computer di chi lo lancia.
    """

    model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")


@pytest.fixture
def calendario() -> ImpostazioniCalendario:
    """Calendario non collegato: è come nasce un'installazione (§8.10).

    Un test che vuole il blocco calendario della Home ridefinisce questa fixture.
    """
    return _CalendarioDiTest()


class _BotDiTest(ImpostazioniBot):
    """Ignora il `.env` dello sviluppatore, come `_CalendarioDiTest`.

    Senza, un `.env` locale con `TELEGRAM_BOT_TOKEN` farebbe risultare il bot
    collegato in macchina e scollegato in CI — cioè un test che dipende da cosa
    c'è sul computer di chi lo lancia.
    """

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", env_file=None, extra="ignore")


@pytest.fixture
def bot() -> ImpostazioniBot:
    """Bot non configurato: è come nasce un'installazione.

    Un test che vuole vederlo collegato ridefinisce questa fixture.
    """
    return _BotDiTest()


class _WorkerDiTest(ImpostazioniWorker):
    """Ignora il `.env` dello sviluppatore, come `_CalendarioDiTest` e `_BotDiTest`.

    L'API legge da qui il valore di partenza di giorno e ora del riepilogo (§8):
    senza questa sottoclasse, un `.env` locale con `WORKER_ORA_RIEPILOGO=08:30`
    farebbe passare o fallire i test della pagina Impostazioni a seconda di cosa
    c'è sul computer di chi li lancia.
    """

    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=None, extra="ignore")


@pytest.fixture
def worker() -> ImpostazioniWorker:
    """Le manopole del worker com'è nata l'installazione: domenica alle 21:00.

    Un test che vuole vedere la pagina Impostazioni con un `.env` diverso
    ridefinisce questa fixture — è l'unico modo di provare che il valore
    mostrato è quello del `.env` e non una costante del registro.
    """
    return _WorkerDiTest()


class _MeteoDiTest(ImpostazioniMeteo):
    """Ignora il `.env` dello sviluppatore, come `_WorkerDiTest`: una «casa» locale
    farebbe rispondere la pagina in macchina e tacere in CI."""

    model_config = SettingsConfigDict(env_prefix="METEO_", env_file=None, extra="ignore")


@pytest.fixture
def meteo() -> ImpostazioniMeteo:
    """Senza casa: è come nasce un'installazione (§8.12)."""
    return _MeteoDiTest()


class SorgenteMeteoFinta:
    """Al posto di Open-Meteo: dà le previsioni che le si dicono e ricorda dove
    gliele hanno chieste."""

    def __init__(self) -> None:
        self.previsioni_date: list[Previsione] = []
        self.errore: Exception | None = None
        self.chiamate: list[tuple[float, float, int, str]] = []

    def previsioni(self, lat: float, lon: float, giorni: int, fuso: str) -> list[Previsione]:
        self.chiamate.append((lat, lon, giorni, fuso))
        if self.errore is not None:
            raise self.errore
        return self.previsioni_date


@pytest.fixture
def sorgente_meteo() -> SorgenteMeteoFinta:
    return SorgenteMeteoFinta()


@pytest.fixture
def client(
    fai_settings: Callable[..., Settings],
    db_path: Path,
    ora: datetime,
    modello: RouterFinto,
    budget: float | None,
    calendario: ImpostazioniCalendario,
    bot: ImpostazioniBot,
    worker: ImpostazioniWorker,
    meteo: ImpostazioniMeteo,
    sorgente_meteo: SorgenteMeteoFinta,
) -> Iterator[TestClient]:
    """API completa su un DB temporaneo, con "adesso" fissato.

    Le migrazioni le applica l'avvio dell'app, come in produzione: il test
    esercita anche quel passaggio invece di preparare lo schema per conto suo.
    """
    app = crea_app(
        fai_settings(ambiente="test", db_path=db_path, budget_settimanale=budget),
        router=modello,  # type: ignore[arg-type]
        calendario=calendario,
        bot=bot,
        worker=worker,
        meteo=meteo,
        sorgente_meteo=sorgente_meteo,
    )
    # L'ora è iniettata: senza, le etichette ("oggi", "giovedì") e la sezione
    # in cui finisce un task dipenderebbero da quando girano i test.
    app.dependency_overrides[prendi_ora] = lambda: ora
    with TestClient(app) as attivo:
        yield attivo
