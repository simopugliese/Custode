"""Il meteo (§8.12): una chiamata a Open-Meteo, mai un archivio."""

from custode_meteo.errori import MeteoNonRaggiungibile
from custode_meteo.previsione import Previsione, SorgenteMeteo

__all__ = ["MeteoNonRaggiungibile", "Previsione", "SorgenteMeteo"]
