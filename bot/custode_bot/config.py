"""Configurazione del bot Telegram.

Sta a parte da `custode_core.config` perché è l'unica cosa che riguarda solo
questo servizio: l'API e il worker non devono nemmeno sapere che esiste un
token. Il prefisso delle variabili è `TELEGRAM_` (vedi `.env.example`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ImpostazioniBot(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    """Token di @BotFather. Vuoto = il bot non parte (nessun default nel codice)."""

    allowed_user_id: int = 0
    """L'unico user ID Telegram ammesso: ogni altro mittente viene ignorato (§9).

    Zero significa "nessuno autorizzato": è un default sicuro, un bot mal
    configurato non risponde a nessuno invece di rispondere a chiunque.
    """

    comandi_pubblici: bool = Field(default=True)
    """Se registrare la lista comandi nel menu di Telegram."""

    whisper_url: str = "http://whisper:8100"
    """Servizio di trascrizione sulla rete interna di Docker (§4, §13).

    Vuoto = niente vocali: il bot lo dice invece di restare in silenzio.
    """

    max_secondi_vocale: int = 300
    """Un vocale più lungo di così è quasi sempre un invio per sbaglio."""

    def configurato(self) -> bool:
        return bool(self.bot_token) and self.allowed_user_id > 0


@lru_cache(maxsize=1)
def get_impostazioni_bot() -> ImpostazioniBot:
    return ImpostazioniBot()
