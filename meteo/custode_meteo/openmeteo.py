"""Open-Meteo, con httpx (§8.12).

I nomi dei campi (`daily`, `weather_code`, `precipitation_probability_max`…)
sono quelli della documentazione di Open-Meteo scritti a memoria: se un giorno
il servizio li cambia, l'errore è `MeteoNonRaggiungibile` e non una previsione
sbagliata.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from custode_meteo.errori import MeteoNonRaggiungibile
from custode_meteo.previsione import Previsione

log = logging.getLogger("custode.meteo")

URL = "https://api.open-meteo.com/v1/forecast"
GIORNALIERI = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"


class ClientOpenMeteo:
    """Prende una posizione, dà le previsioni. Il client HTTP è iniettabile per
    la stessa ragione di `ClientGoogle`: un test lo punta a un finto servizio che
    risponde davvero su HTTP, e così prova anche come la richiesta è costruita."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 10.0):
        self._client = client
        self._timeout = timeout

    def previsioni(self, lat: float, lon: float, giorni: int, fuso: str) -> list[Previsione]:
        parametri: dict[str, str | float | int] = {
            "latitude": lat,
            "longitude": lon,
            "daily": GIORNALIERI,
            "timezone": fuso,
            "forecast_days": giorni,
        }
        try:
            if self._client is not None:
                risposta = self._client.get(URL, params=parametri, timeout=self._timeout)
            else:
                with httpx.Client() as client:
                    risposta = client.get(URL, params=parametri, timeout=self._timeout)
            risposta.raise_for_status()
            return _leggi(risposta.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as errore:
            log.warning("open-meteo non ha dato una previsione: %s", errore)
            raise MeteoNonRaggiungibile(str(errore)) from errore


def _leggi(corpo: dict[str, Any]) -> list[Previsione]:
    """Dalle colonne di Open-Meteo (un array per campo) a una riga per giorno."""
    giornaliero = corpo["daily"]
    date_iso = giornaliero["time"]
    pioggia = giornaliero.get("precipitation_probability_max") or [None] * len(date_iso)
    return [
        Previsione(
            giorno=date.fromisoformat(giorno),
            codice=int(giornaliero["weather_code"][i]),
            minima=float(giornaliero["temperature_2m_min"][i]),
            massima=float(giornaliero["temperature_2m_max"][i]),
            prob_pioggia=None if pioggia[i] is None else int(pioggia[i]),
        )
        for i, giorno in enumerate(date_iso)
    ]
