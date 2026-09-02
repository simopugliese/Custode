"""Le impostazioni leggono l'ambiente e non portano segreti nei default."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from custode_core.config import Settings, get_settings


def test_default_senza_ambiente(fai_settings: Callable[..., Settings]) -> None:
    impostazioni = fai_settings()
    assert impostazioni.ambiente == "development"
    assert impostazioni.db_path == Path("data/custode.db")
    assert impostazioni.cors_origins == []
    assert impostazioni.timezone == "Europe/Rome"


def test_legge_le_variabili_con_prefisso(
    fai_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUSTODE_AMBIENTE", "production")
    monkeypatch.setenv("CUSTODE_DB_PATH", "/data/custode.db")
    impostazioni = fai_settings()
    assert impostazioni.ambiente == "production"
    assert impostazioni.db_path == Path("/data/custode.db")


@pytest.mark.parametrize(
    ("valore", "atteso"),
    [
        ("https://custode.pages.dev", ["https://custode.pages.dev"]),
        ("https://a.dev, https://b.dev", ["https://a.dev", "https://b.dev"]),
        ('["https://a.dev"]', ["https://a.dev"]),
        ("", []),
    ],
)
def test_cors_origins_da_stringa(
    fai_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    valore: str,
    atteso: list[str],
) -> None:
    monkeypatch.setenv("CUSTODE_CORS_ORIGINS", valore)
    assert fai_settings().cors_origins == atteso


def test_get_settings_e_memoizzata() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


def test_un_budget_vuoto_vale_non_impostato(
    fai_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.env.example` lascia la riga vuota: copiarlo non deve bloccare l'avvio."""
    monkeypatch.setenv("CUSTODE_BUDGET_SETTIMANALE", "")
    assert fai_settings().budget_settimanale is None

    monkeypatch.setenv("CUSTODE_BUDGET_SETTIMANALE", "120")
    assert fai_settings().budget_settimanale == 120.0
