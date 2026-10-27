"""Il modo in cui il meteo può fallire."""

from __future__ import annotations


class MeteoNonRaggiungibile(RuntimeError):
    """Open-Meteo non risponde, o risponde qualcosa che non è una previsione.

    Un solo errore per due cause, perché a chi lo riceve chiedono la stessa
    cosa: non mostrare un meteo inventato e riprovare più tardi.
    """
