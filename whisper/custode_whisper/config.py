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

    filtri_audio: str = "highpass=f=80,dynaudnorm"
    """Filtri `-af` di ffmpeg applicati prima di trascrivere.

    Un vocale registrato per strada o a mezzo metro dalla bocca è il caso
    normale, non l'eccezione: togliere il rimbombo sotto gli 80 Hz e portare il
    parlato a un volume costante costa qualche millisecondo e toglie una fetta
    degli errori. Si svuota (`WHISPER_FILTRI_AUDIO=`) per tornare alla
    conversione nuda e confrontare.
    """

    sopprimi_non_parlato: bool = True
    """`--suppress-nst`: niente token che non sono parlato.

    Su silenzio e rumore Whisper inventa, e in italiano tira fuori le frasi da
    sottotitoli («Sottotitoli a cura di…»), che poi arrivano all'interprete
    come se fossero state dette. In whisper.cpp v1.7.4 non c'è ancora la VAD,
    che sarebbe il rimedio pulito: questa è la leva disponibile.
    """

    timeout_secondi: float = 120.0
    max_byte_audio: int = 25 * 1024 * 1024

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_impostazioni_whisper() -> ImpostazioniWhisper:
    return ImpostazioniWhisper()
