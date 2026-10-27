"""La previsione di un giorno, e l'interfaccia di chi la fornisce."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class Previsione:
    giorno: date
    codice: int
    """Il codice WMO del tempo del giorno (0 sereno … 99 temporale)."""
    minima: float
    massima: float
    prob_pioggia: int | None
    """Percentuale 0-100. `None` se il servizio non la dà per quel giorno: non è
    «0%», che sarebbe una promessa di cielo asciutto."""


class SorgenteMeteo(Protocol):
    """Chi sa dire che tempo fa. Come `SorgenteCalendario`, esiste perché i test
    non debbano uscire in rete e perché il resto non sappia chi c'è dietro."""

    def previsioni(self, lat: float, lon: float, giorni: int, fuso: str) -> list[Previsione]: ...
