"""Fixture condivise dai test.

Ogni test che tocca il DB lavora su un file temporaneo dedicato: mai il DB di
sviluppo, mai un DB in memoria (in memoria SQLite non usa WAL, quindi non
eserciterebbe la configurazione reale — ARCHITECTURE.md §3).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

from custode_core.config import Settings


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
