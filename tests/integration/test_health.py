"""Smoke test dell'API: `GET /api/health` contro un DB reale su disco (§10)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from custode_api.main import crea_app
from custode_core.config import Settings

pytestmark = pytest.mark.integration


def test_health_ok(settings: Settings) -> None:
    with TestClient(crea_app(settings)) as client:
        risposta = client.get("/api/health")
    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["stato"] == "ok"
    assert corpo["db"] == "ok"
    assert corpo["ambiente"] == "test"
    assert corpo["versione"]


def test_health_503_se_il_db_non_risponde(
    fai_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    # Una cartella al posto del file: sqlite non riesce ad aprirlo.
    cartella = tmp_path / "custode.db"
    cartella.mkdir()
    with TestClient(crea_app(fai_settings(ambiente="test", db_path=cartella))) as client:
        risposta = client.get("/api/health")
    assert risposta.status_code == 503
    assert risposta.json()["db"] == "irraggiungibile"


def test_docs_esposte_solo_fuori_produzione(
    settings: Settings, fai_settings: Callable[..., Settings], db_path: Path
) -> None:
    with TestClient(crea_app(settings)) as client:
        assert client.get("/openapi.json").status_code == 200

    produzione = fai_settings(ambiente="production", db_path=db_path)
    with TestClient(crea_app(produzione)) as client:
        assert client.get("/openapi.json").status_code == 404


def test_cors_per_la_dashboard(fai_settings: Callable[..., Settings], db_path: Path) -> None:
    origine = "https://custode.pages.dev"
    impostazioni = fai_settings(ambiente="test", db_path=db_path, cors_origins=[origine])
    with TestClient(crea_app(impostazioni)) as client:
        risposta = client.get("/api/health", headers={"Origin": origine})
    assert risposta.headers["access-control-allow-origin"] == origine
