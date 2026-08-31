"""Configurazione di Custode, letta da variabili d'ambiente / file .env.

Ogni variabile è documentata in `.env.example` alla radice del repo. I segreti
non hanno mai un default reale nel codice: restano vuoti finché non li fornisce
l'ambiente (ARCHITECTURE.md §5, §9).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Ambiente = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Impostazioni comuni a tutti i servizi.

    Le variabili d'ambiente hanno prefisso `CUSTODE_`: ad esempio
    `CUSTODE_DB_PATH` popola `db_path`.
    """

    model_config = SettingsConfigDict(
        env_prefix="CUSTODE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ambiente: Ambiente = "development"
    """Profilo di esecuzione. In `production` la API non espone la documentazione."""

    db_path: Path = Path("data/custode.db")
    """Percorso del file SQLite. Nei container punta al volume montato su /data."""

    log_level: str = "INFO"

    timezone: str = "Europe/Rome"
    """Fuso orario usato per digest, check-in e job schedulati (§8.13)."""

    # `NoDecode` disattiva il parsing JSON automatico di pydantic-settings sui
    # campi complessi: così la variabile d'ambiente può essere un semplice
    # elenco separato da virgole, che è come si scrive a mano in un .env.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    """Origini ammesse per la dashboard su Cloudflare Pages.

    Accetta sia una lista JSON sia un elenco separato da virgole.
    """

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        testo = value.strip()
        if not testo:
            return []
        if testo.startswith("["):
            return json.loads(testo)
        return [pezzo.strip() for pezzo in testo.split(",") if pezzo.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Istanza unica delle impostazioni (una sola lettura di ambiente/.env)."""
    return Settings()
