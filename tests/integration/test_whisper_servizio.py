"""Il servizio di trascrizione: `POST /trascrivi` e `GET /health`."""

from __future__ import annotations

import stat
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


# — il vocabolario del proprietario, dal bot fino a whisper.cpp —


def _script(percorso: Path, corpo: str) -> Path:
    percorso.write_text(f"#!/bin/sh\n{corpo}\n", encoding="utf-8")
    percorso.chmod(percorso.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return percorso


@pytest.fixture
def impostazioni_vere(tmp_path: Path) -> tuple[ImpostazioniWhisper, Path]:
    """Eseguibili finti ma funzionanti: il giro HTTP arriva fino al comando."""
    registro = tmp_path / "argomenti.txt"
    ffmpeg = _script(
        tmp_path / "ffmpeg",
        f'echo "ffmpeg $@" >> {registro}\n'
        'for ultimo in "$@"; do :; done\n'
        'printf "WAV" > "$ultimo"',
    )
    whisper = _script(
        tmp_path / "whisper-cli",
        f'echo "whisper $@" >> {registro}\n'
        'prefisso=""\n'
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "--output-file" ]; then prefisso="$2"; fi\n'
        "  shift\n"
        "done\n"
        'printf "sono stato da Bricoman\\n" > "$prefisso.txt"',
    )
    modello = tmp_path / "modello.bin"
    modello.write_bytes(b"finto")
    return _Impostazioni(binario=whisper, modello=modello, ffmpeg=ffmpeg), registro


def test_il_contesto_arriva_dal_form_fino_al_comando(
    impostazioni_vere: tuple[ImpostazioniWhisper, Path],
) -> None:
    """Il giro vero: campo del form → servizio → riga di comando di whisper.cpp."""
    impostazioni, registro = impostazioni_vere
    with TestClient(crea_app(impostazioni)) as client:
        risposta = client.post(
            "/trascrivi",
            files={"audio": ("v.ogg", b"audio", "audio/ogg")},
            data={"contesto": "Meditazione, Bricoman."},
        )

    assert risposta.status_code == 200
    assert risposta.json()["testo"] == "sono stato da Bricoman"
    righe = registro.read_text(encoding="utf-8")
    assert "--prompt Meditazione, Bricoman." in righe


def test_il_contesto_resta_facoltativo(
    impostazioni_vere: tuple[ImpostazioniWhisper, Path],
) -> None:
    """Chi non ha niente da suggerire manda solo l'audio, come prima."""
    impostazioni, registro = impostazioni_vere
    with TestClient(crea_app(impostazioni)) as client:
        risposta = client.post("/trascrivi", files={"audio": ("v.ogg", b"audio", "audio/ogg")})

    assert risposta.status_code == 200
    assert "--prompt" not in registro.read_text(encoding="utf-8")
