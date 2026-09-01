"""Scelta del modello e chiamata ai provider (ARCHITECTURE.md §6).

Il principio di §1 è "massima resa, minima spesa": i compiti banali e ad alto
volume vanno a DeepSeek, quelli che richiedono qualità, visione o ragionamento
a Claude. La tabella che decide sta in `compiti.py`, una sola volta, invece di
essere sparsa nei punti di chiamata.

Questo pacchetto dipende da `custode_core` (dominio e configurazione), mai il
contrario: il codice condiviso non deve sapere che esistono dei modelli.
"""

from custode_router.compiti import Compito, Provider, provider_per
from custode_router.errori import (
    CompitoNonSupportato,
    ErroreRouter,
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)
from custode_router.router import Router

__all__ = [
    "Compito",
    "CompitoNonSupportato",
    "ErroreRouter",
    "Provider",
    "ProviderNonConfigurato",
    "ProviderNonRaggiungibile",
    "RispostaNonValida",
    "Router",
    "provider_per",
]
