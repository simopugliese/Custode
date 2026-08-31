"""Fixture condivise dai test.

Ogni test che tocca il DB lavora su un file temporaneo dedicato: mai il DB di
sviluppo, mai un DB in memoria (in memoria SQLite non usa WAL, quindi non
eserciterebbe la configurazione reale — ARCHITECTURE.md §3).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

from custode_core.config import Settings
from custode_core.db import connect
from custode_core.migrazioni import migra


class _SettingsDiTest(Settings):
    """`Settings` che ignora il `.env` dello sviluppatore.

    I test devono dipendere solo dall'ambiente che impostano esplicitamente:
    senza questo, un `.env` presente in locale cambierebbe il risultato dei
    test rispetto alla CI.
    """

    model_config = SettingsConfigDict(env_prefix="CUSTODE_", env_file=None, extra="ignore")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "custode-test.db"


@pytest.fixture
def fai_settings() -> Callable[..., Settings]:
    """Costruisce `Settings` isolate dal `.env`, con i campi passati per nome."""

    def _fai(**campi: Any) -> Settings:
        return _SettingsDiTest(**campi)

    return _fai


@pytest.fixture
def settings(fai_settings: Callable[..., Settings], db_path: Path) -> Settings:
    return fai_settings(ambiente="test", db_path=db_path, cors_origins=[])


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Connessione a un database temporaneo con lo schema già migrato."""
    connessione = connect(db_path)
    migra(connessione)
    try:
        yield connessione
    finally:
        connessione.close()


# Lunedì 31 agosto 2026, 08:41: un istante fisso, così le etichette ("oggi",
# "giovedì") non cambiano a seconda di quando girano i test.
ORA = datetime(2026, 8, 31, 8, 41)


@pytest.fixture
def ora() -> datetime:
    return ORA
