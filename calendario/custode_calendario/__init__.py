"""Lettura del calendario (§8.10). Custode legge e basta: non scrive mai."""

from custode_calendario.errori import (
    AutorizzazioneNonValida,
    CalendarioNonConfigurato,
    CalendarioNonRaggiungibile,
    ErroreCalendario,
)
from custode_calendario.evento import Evento, SorgenteCalendario

__all__ = [
    "AutorizzazioneNonValida",
    "CalendarioNonConfigurato",
    "CalendarioNonRaggiungibile",
    "ErroreCalendario",
    "Evento",
    "SorgenteCalendario",
]
