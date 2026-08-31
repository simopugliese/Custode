"""Codice condiviso fra i servizi di Custode (api, bot, router, worker).

Qui vivono le sole cose che tutti i processi devono vedere allo stesso modo:
la configurazione letta dall'ambiente e l'accesso al file SQLite (ARCHITECTURE.md
§3, §4). La logica di dominio si aggiunge modulo per modulo, seguendo §8.
"""

from custode_core.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
