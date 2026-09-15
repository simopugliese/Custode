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

from custode_calendario.config import ImpostazioniCalendario
from custode_core.config import Settings
from custode_core.db import connect
from custode_core.formato import adesso
from custode_router import Router


def prendi_settings(request: Request) -> Settings:
    """Le impostazioni con cui l'app è stata costruita."""
    settings: Settings = request.app.state.settings
    return settings


ImpostazioniDip = Annotated[Settings, Depends(prendi_settings)]


def prendi_calendario(request: Request) -> ImpostazioniCalendario:
    """Le impostazioni del calendario, per sapere se il modulo è acceso.

    L'API non legge mai il calendario — quello è mestiere del worker — ma deve
    sapere se le credenziali ci sono: senza, il blocco della Home non si
    disegna affatto (§5 del contratto, campo omesso ≠ campo vuoto).
    """
    calendario: ImpostazioniCalendario = request.app.state.calendario
    return calendario


CalendarioDip = Annotated[ImpostazioniCalendario, Depends(prendi_calendario)]


def prendi_router(request: Request) -> Router:
    """Il router dei compiti (§6), per sapere quali sono accesi.

    L'API non fa **mai** parlare un modello dentro una richiesta — quello è
    mestiere del bot e del worker — ma ha bisogno di sapere se un compito ha
    una chiave dietro: una pagina che promette «Custode ci pensa al prossimo
    giro» quando nessuno ci penserà mai è peggio di una che non promette
    niente.
    """
    instradatore: Router = request.app.state.router
    return instradatore


RouterDip = Annotated[Router, Depends(prendi_router)]


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
