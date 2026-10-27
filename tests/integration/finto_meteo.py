"""Il meteo per i test del worker che non lo riguardano.

`giro()` chiede una sorgente e le impostazioni del meteo ad ogni risveglio. Qui:
nessuna «casa» (è come nasce un'installazione, §8.12) e una sorgente che non va
interrogata, così un test che non parla di digest se ne accorge se lo fa
scattare per sbaglio.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from custode_meteo.config import ImpostazioniMeteo
from custode_meteo.previsione import Previsione


class MeteoDiTest(ImpostazioniMeteo):
    """Ignora il `.env` dello sviluppatore, come `_WorkerDiTest`."""

    model_config = SettingsConfigDict(env_prefix="METEO_", env_file=None, extra="ignore")


class MeteoSpento:
    def previsioni(self, lat: float, lon: float, giorni: int, fuso: str) -> list[Previsione]:
        raise AssertionError("questo test non ha una posizione: il meteo non va interrogato")
