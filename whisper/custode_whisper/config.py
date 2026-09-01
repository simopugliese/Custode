"""Configurazione del servizio di trascrizione (prefisso `WHISPER_`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ImpostazioniWhisper(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WHISPER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    binario: Path = Path("/opt/whisper/whisper-cli")
    modello: Path = Path("/opt/whisper/models/ggml-base-q5_1.bin")
    """Modello `base` quantizzato q5_1: ~1 GB di RAM, pochi secondi per un
    vocale di 30-60s su Pi 5, accuratezza già solida con parlato pulito (§13)."""

    lingua: str = "it"
    thread: int = 2
    """Limitati apposta per non rubare CPU a bot e API durante la trascrizione."""

    ffmpeg: Path = Path("/usr/bin/ffmpeg")
    """I vocali di Telegram sono OGG/Opus: vanno portati a WAV 16 kHz mono."""

    timeout_secondi: float = 120.0
    max_byte_audio: int = 25 * 1024 * 1024

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_impostazioni_whisper() -> ImpostazioniWhisper:
    return ImpostazioniWhisper()
