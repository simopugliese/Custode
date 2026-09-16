"""Il worker segue le impostazioni senza che nessuno lo riavvii (§8).

È la metà del pezzo 7 che non si vede dall'API: cambiare giorno e ora del
riepilogo dalla pagina deve spostare il job **entro un giro**, cioè entro
cinque minuti, senza `docker compose restart` e senza toccare il `.env`.

Il giro vero, non un pezzo di lui: `worker_main.giro` con l'orologio fermo su
un istante scelto, e quello che si guarda è se il riepilogo è partito.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

from custode_bot.risposte import Risposta
from custode_calendario.config import ImpostazioniCalendario
from custode_calendario.evento import Evento
from custode_core.config import Settings
from custode_core.dominio import diario as dom_diario
from custode_core.dominio import impostazioni as dom
from custode_core.registro_job import RIEPILOGO_SETTIMANALE, gia_eseguito
from custode_worker import main as worker_main
from custode_worker.config import ImpostazioniWorker

pytestmark = pytest.mark.integration

# Domenica 13 settembre 2026. Il riepilogo di default è «domenica alle 21:00».
DOMENICA_SERA = datetime(2026, 9, 13, 21, 3)
LUNEDI_PRECEDENTE = date(2026, 9, 7)


class _WorkerDiTest(ImpostazioniWorker):
    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=None, extra="ignore")


class _CalendarioSpento(ImpostazioniCalendario):
    model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")


class TelegramFinto:
    def __init__(self) -> None:
        self.mandati: list[Risposta] = []

    def manda(self, risposta: Risposta) -> None:
        self.mandati.append(risposta)


class ModelloFinto:
    def configurato_per(self, compito: Any) -> bool:
        return True

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        return {"riepilogo": "Andata così."}


class SorgenteSpenta:
    def configurata(self) -> bool:
        return False

    def eventi(self, da: date, a: date) -> list[Evento]:
        raise AssertionError("un calendario spento non va interrogato")


@pytest.fixture
def impostazioni(db_path: Path) -> Settings:
    class _Test(Settings):
        model_config = SettingsConfigDict(env_prefix="CUSTODE_", env_file=None, extra="ignore")

    return _Test(ambiente="test", db_path=db_path, timezone="Europe/Rome")


@pytest.fixture(autouse=True)
def schema(conn: sqlite3.Connection) -> None:
    """Lo schema migrato prima di ogni giro, come lo trova il worker sul Pi."""


def _materiale(conn: sqlite3.Connection) -> None:
    """Una settimana con qualcosa dentro: senza, il riepilogo non parte."""
    dom_diario.aggiungi_materiale(
        conn,
        giorno=LUNEDI_PRECEDENTE,
        testo="giornata in laboratorio",
        ora=datetime(2026, 9, 7, 20, 0),
    )
    voce = dom_diario.leggi_giorno(conn, LUNEDI_PRECEDENTE)
    assert voce is not None
    dom_diario.proponi(conn, voce.id, riassunto="Laboratorio.", tag=["studio"])
    dom_diario.approva(conn, voce.id, datetime(2026, 9, 7, 21, 0))


def _giro(
    impostazioni: Settings, adesso: datetime, monkeypatch: pytest.MonkeyPatch
) -> TelegramFinto:
    telegram = TelegramFinto()
    monkeypatch.setattr(worker_main, "adesso", lambda _fuso: adesso)
    worker_main.giro(
        impostazioni,
        # Il `.env` dice «domenica alle 21:00»: è il punto di partenza, e i test
        # qui sotto lo contraddicono dalla tabella.
        _WorkerDiTest(
            backup_cartella=Path("/backup-inesistente"),
            giorno_riepilogo="domenica",
            ora_riepilogo="21:00",
        ),
        router=ModelloFinto(),  # type: ignore[arg-type]
        telegram=telegram,  # type: ignore[arg-type]
        calendario=_CalendarioSpento(),
        sorgente_calendario=SorgenteSpenta(),
    )
    return telegram


def test_senza_impostazioni_vale_il_env(
    conn: sqlite3.Connection, impostazioni: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La domenica sera alle 21:03 il riepilogo del `.env` è dovuto."""
    _materiale(conn)

    _giro(impostazioni, DOMENICA_SERA, monkeypatch)

    assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)


def test_spostare_il_giorno_dalla_pagina_sposta_il_job(
    conn: sqlite3.Connection, impostazioni: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il cuore del pezzo: la tabella batte il `.env`, e senza riavviare niente.

    Il `.env` dice domenica; qui si sceglie lunedì. Alla domenica sera il job
    **non** deve partire più, e il lunedì sì — e fra le due cose non è ripartito
    nessun processo.
    """
    _materiale(conn)
    dom.RIEPILOGO_GIORNO.scrivi(conn, "lunedi", DOMENICA_SERA)

    _giro(impostazioni, DOMENICA_SERA, monkeypatch)
    assert not gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)

    _giro(impostazioni, DOMENICA_SERA + timedelta(days=1), monkeypatch)
    assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)


def test_spostare_l_ora_dalla_pagina_sposta_il_job(
    conn: sqlite3.Connection, impostazioni: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mezzo interruttore non è un interruttore: anche l'ora deve contare."""
    _materiale(conn)
    dom.RIEPILOGO_ORA.scrivi(conn, "23:30", DOMENICA_SERA)

    _giro(impostazioni, DOMENICA_SERA, monkeypatch)
    assert not gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)

    _giro(impostazioni, DOMENICA_SERA.replace(hour=23, minute=31), monkeypatch)
    assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)


def test_il_cambio_vale_dal_giro_successivo_non_dal_riavvio(
    conn: sqlite3.Connection, impostazioni: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il worker rilegge in cima a ogni giro, non all'avvio.

    Qui il processo è lo stesso — la stessa funzione chiamata due volte di fila
    — e in mezzo cambia solo una riga in tabella. Se le impostazioni si
    leggessero all'avvio, il secondo giro si comporterebbe come il primo.
    """
    _materiale(conn)

    # Alle 20:03 di domenica non è ancora ora: il `.env` dice le 21:00.
    _giro(impostazioni, DOMENICA_SERA.replace(hour=20), monkeypatch)
    assert not gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)

    dom.RIEPILOGO_ORA.scrivi(conn, "19:00", DOMENICA_SERA)

    _giro(impostazioni, DOMENICA_SERA.replace(hour=20, minute=8), monkeypatch)
    assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)


def test_un_orario_storto_in_tabella_non_ferma_il_giro(
    conn: sqlite3.Connection, impostazioni: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una riga scritta a mano con sqlite3 non deve uccidere il worker.

    Vale come «non l'ho mai deciso», quindi torna a valere il `.env`: il job
    riparte all'ora di prima invece di non partire più — e senza portarsi via
    il backup e il calendario, che girano nello stesso giro.
    """
    _materiale(conn)
    conn.execute(
        "INSERT INTO impostazioni (chiave, valore, aggiornato_il) VALUES (?, ?, ?)",
        ("riepilogo_settimanale_ora", '"25:70"', DOMENICA_SERA.isoformat()),
    )

    _giro(impostazioni, DOMENICA_SERA, monkeypatch)

    assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRECEDENTE)
