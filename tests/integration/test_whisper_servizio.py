"""Il servizio di trascrizione: `POST /trascrivi` e `GET /health`."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import SettingsConfigDict

from custode_whisper.config import ImpostazioniWhisper
from custode_whisper.main import crea_app

pytestmark = pytest.mark.integration


class _Impostazioni(ImpostazioniWhisper):
    """Ignora il `.env` dello sviluppatore."""

    model_config = SettingsConfigDict(env_prefix="WHISPER_", env_file=None, extra="ignore")


@pytest.fixture
def impostazioni(tmp_path: Path) -> ImpostazioniWhisper:
    """Punta a eseguibili che non esistono: qui interessa il livello HTTP."""
    return _Impostazioni(
        binario=tmp_path / "whisper-cli",
        modello=tmp_path / "modello.bin",
        ffmpeg=tmp_path / "ffmpeg",
    )


def test_health_dice_se_il_modello_c_e(impostazioni: ImpostazioniWhisper) -> None:
    with TestClient(crea_app(impostazioni)) as client:
        corpo = client.get("/health").json()
    assert corpo["stato"] == "degradato"
    assert corpo["modello_presente"] is False

    impostazioni.modello.write_bytes(b"finto")
    with TestClient(crea_app(impostazioni)) as client:
        corpo = client.get("/health").json()
    assert corpo["stato"] == "ok"
    assert corpo["modello_presente"] is True


def test_audio_illeggibile_e_422_non_500(impostazioni: ImpostazioniWhisper) -> None:
    """Chi chiama deve distinguere «audio incomprensibile» da «servizio rotto»."""
    with TestClient(crea_app(impostazioni)) as client:
        risposta = client.post("/trascrivi", files={"audio": ("v.ogg", b"", "audio/ogg")})
    assert risposta.status_code == 422
    assert "vuoto" in risposta.json()["detail"]


def test_senza_file(impostazioni: ImpostazioniWhisper) -> None:
    with TestClient(crea_app(impostazioni)) as client:
        assert client.post("/trascrivi").status_code == 422


def test_non_pubblica_lo_schema(impostazioni: ImpostazioniWhisper) -> None:
    # Non è esposto e non serve a nessuno: superficie in meno (§9).
    with TestClient(crea_app(impostazioni)) as client:
        assert client.get("/openapi.json").status_code == 404
