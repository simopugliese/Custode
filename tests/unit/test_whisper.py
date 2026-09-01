"""Trascrizione: la parte che si può provare senza avere whisper compilato.

Il binario e ffmpeg sono sostituiti da script finti, così si verifica ciò che
è nostro — la conversione a WAV 16 kHz mono, gli argomenti passati, i limiti e
i modi di fallire — senza dipendere da una toolchain C++.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from custode_whisper.config import ImpostazioniWhisper
from custode_whisper.trascrizione import ErroreTrascrizione, trascrivi


def _script(percorso: Path, corpo: str) -> Path:
    percorso.write_text(f"#!/bin/sh\n{corpo}\n", encoding="utf-8")
    percorso.chmod(percorso.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return percorso


class _Impostazioni(ImpostazioniWhisper):
    """Ignora il `.env` dello sviluppatore."""

    model_config = SettingsConfigDict(env_prefix="WHISPER_", env_file=None, extra="ignore")


@dataclass
class Finti:
    """Impostazioni che puntano a eseguibili finti, più il loro registro."""

    impostazioni: ImpostazioniWhisper
    registro: Path

    def righe(self) -> list[str]:
        if not self.registro.exists():
            return []
        return self.registro.read_text(encoding="utf-8").splitlines()

    def con(self, **campi: object) -> ImpostazioniWhisper:
        return self.impostazioni.model_copy(update=campi)


@pytest.fixture
def finti(tmp_path: Path) -> Finti:
    """ffmpeg e whisper-cli finti che registrano come sono stati chiamati."""
    registro = tmp_path / "argomenti.txt"
    ffmpeg = _script(
        tmp_path / "ffmpeg",
        # Registra gli argomenti e produce il file di destinazione (ultimo argomento).
        f'echo "ffmpeg $@" >> {registro}\n'
        'for ultimo in "$@"; do :; done\n'
        'printf "WAV" > "$ultimo"',
    )
    whisper = _script(
        tmp_path / "whisper-cli",
        f'echo "whisper $@" >> {registro}\n'
        # --output-file è seguito dal prefisso: whisper.cpp ci aggiunge .txt
        'prefisso=""\n'
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "--output-file" ]; then prefisso="$2"; fi\n'
        "  shift\n"
        "done\n"
        'printf "ho fatto la spesa\\n" > "$prefisso.txt"',
    )
    modello = tmp_path / "ggml-base-q5_1.bin"
    modello.write_bytes(b"finto")
    return Finti(
        impostazioni=_Impostazioni(binario=whisper, modello=modello, ffmpeg=ffmpeg),
        registro=registro,
    )


def test_trascrizione_riuscita(finti: Finti) -> None:
    assert trascrivi(b"audio-ogg", finti.impostazioni) == "ho fatto la spesa"


def test_converte_a_wav_16k_mono(finti: Finti) -> None:
    """whisper.cpp accetta solo questo formato; i vocali di Telegram sono OGG."""
    trascrivi(b"audio-ogg", finti.impostazioni)
    (riga_ffmpeg,) = [r for r in finti.righe() if r.startswith("ffmpeg")]
    assert "-ar 16000" in riga_ffmpeg
    assert "-ac 1" in riga_ffmpeg


def test_passa_lingua_e_thread(finti: Finti) -> None:
    trascrivi(b"audio", finti.impostazioni)
    (riga,) = [r for r in finti.righe() if r.startswith("whisper")]
    assert "--language it" in riga
    # Thread limitati apposta, per non rubare CPU al bot durante la trascrizione.
    assert "--threads 2" in riga
    assert str(finti.impostazioni.modello) in riga


def test_audio_vuoto(finti: Finti) -> None:
    with pytest.raises(ErroreTrascrizione, match="vuoto"):
        trascrivi(b"", finti.impostazioni)


def test_audio_troppo_grande(finti: Finti) -> None:
    with pytest.raises(ErroreTrascrizione, match="troppo lungo"):
        trascrivi(b"molto piu lungo di quattro byte", finti.con(max_byte_audio=4))


def test_binario_mancante(finti: Finti, tmp_path: Path) -> None:
    with pytest.raises(ErroreTrascrizione, match="non trovato"):
        trascrivi(b"audio", finti.con(binario=tmp_path / "non-esiste"))


def test_whisper_che_fallisce(finti: Finti, tmp_path: Path) -> None:
    fallisce = _script(tmp_path / "che-fallisce", 'echo "rotto" >&2\nexit 1')
    with pytest.raises(ErroreTrascrizione, match="rotto"):
        trascrivi(b"audio", finti.con(binario=fallisce))


def test_trascrizione_vuota(finti: Finti, tmp_path: Path) -> None:
    muto = _script(tmp_path / "muto", "exit 0")
    with pytest.raises(ErroreTrascrizione, match="capire"):
        trascrivi(b"audio", finti.con(binario=muto))
