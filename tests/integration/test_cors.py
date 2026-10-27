"""CORS: la dashboard su Pages deve poter chiamare l'API con il cookie di Access (§9)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from custode_api.main import crea_app
from custode_core.config import Settings

pytestmark = pytest.mark.integration

ORIGINE = "https://custode.example.it"


def _client(fai_settings: Callable[..., Settings], db_path: Path) -> TestClient:
    return TestClient(
        crea_app(fai_settings(ambiente="test", db_path=db_path, cors_origins=[ORIGINE]))
    )


def test_preflight_dall_origine_della_dashboard_ammette_le_credenziali(
    fai_settings: Callable[..., Settings], db_path: Path
) -> None:
    with _client(fai_settings, db_path) as client:
        risposta = client.options(
            "/api/health",
            headers={
                "Origin": ORIGINE,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert risposta.status_code == 200
    assert risposta.headers["access-control-allow-origin"] == ORIGINE
    assert risposta.headers["access-control-allow-credentials"] == "true"


def test_un_altra_origine_non_viene_ammessa(
    fai_settings: Callable[..., Settings], db_path: Path
) -> None:
    with _client(fai_settings, db_path) as client:
        risposta = client.get("/api/health", headers={"Origin": "https://altro.example.it"})
    assert "access-control-allow-origin" not in risposta.headers
