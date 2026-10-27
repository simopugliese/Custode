"""Configurazione del meteo (prefisso `METEO_`).

Niente qui è un segreto: Open-Meteo non vuole una chiave.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ImpostazioniMeteo(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="METEO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    casa_lat: float | None = None
    casa_lon: float | None = None
    """Dove stai di solito. Serve **solo finché la dashboard non ti ha detto dove
    sei**: dalla prima apertura col permesso concesso vince la posizione vera, e
    questa torna a contare soltanto se non ne hai mai data una.

    Senza default: una città scelta dal codice sarebbe un meteo di un posto in
    cui non sei, scritto con la stessa sicurezza di uno vero. Vuoti, la pagina
    dice che non sa dove sei.
    """

    giorni: int = 3
    """Quanti giorni di previsione, oggi compreso."""

    def casa(self) -> tuple[float, float] | None:
        if self.casa_lat is None or self.casa_lon is None:
            return None
        return self.casa_lat, self.casa_lon


@lru_cache
def get_impostazioni_meteo() -> ImpostazioniMeteo:
    return ImpostazioniMeteo()
