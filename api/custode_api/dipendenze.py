"""Dipendenze condivise dalle rotte.

Le impostazioni non si leggono direttamente da `get_settings()` dentro le
rotte: passano da qui, così i test possono sostituirle con
`app.dependency_overrides` e puntare a un database temporaneo.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request

from custode_core.config import Settings
from custode_core.db import connect
from custode_core.formato import adesso


def prendi_settings(request: Request) -> Settings:
    """Le impostazioni con cui l'app è stata costruita."""
    settings: Settings = request.app.state.settings
    return settings


ImpostazioniDip = Annotated[Settings, Depends(prendi_settings)]


def prendi_conn(settings: ImpostazioniDip) -> Iterator[sqlite3.Connection]:
    """Una connessione per richiesta, chiusa a risposta inviata.

    SQLite regge bene questo schema: aprire il file è un'operazione locale e
    poco costosa, e una connessione per richiesta evita di condividere stato
    fra i thread del server.
    """
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


ConnDip = Annotated[sqlite3.Connection, Depends(prendi_conn)]


def prendi_ora(settings: ImpostazioniDip) -> datetime:
    """Adesso, nel fuso configurato. Iniettata per poterla fissare nei test."""
    return adesso(settings.timezone)


OraDip = Annotated[datetime, Depends(prendi_ora)]
