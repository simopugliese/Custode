"""Applicazione FastAPI di Custode.

Tutti gli endpoint stanno sotto il prefisso `/api`, come da contratto in
`dashboard/API.md`. L'autenticazione non è gestita qui: davanti al tunnel c'è
Cloudflare Access, che lascia passare solo l'identità autorizzata (§2, §9).
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from custode_core.config import Settings, get_settings
from custode_core.db import db_raggiungibile


def _versione() -> str:
    try:
        return version("custode")
    except PackageNotFoundError:  # eseguito da sorgenti, senza installazione
        return "0.0.0+dev"


class StatoSalute(BaseModel):
    """Corpo di `GET /api/health`, usato dallo smoke test post-deploy (§10)."""

    stato: Literal["ok", "degradato"]
    versione: str
    ambiente: str
    db: Literal["ok", "irraggiungibile"]


def crea_app(settings: Settings | None = None) -> FastAPI:
    """Costruisce l'app. Parametrizzata sulle impostazioni per i test."""
    impostazioni = settings or get_settings()
    logging.basicConfig(level=impostazioni.log_level.upper())

    in_produzione = impostazioni.ambiente == "production"
    app = FastAPI(
        title="Custode API",
        version=_versione(),
        # In produzione l'API sta dietro Cloudflare Access, ma non c'è motivo
        # di pubblicare comunque lo schema: superficie in meno (§9).
        docs_url=None if in_produzione else "/docs",
        redoc_url=None,
        openapi_url=None if in_produzione else "/openapi.json",
    )

    # La dashboard gira su Cloudflare Pages, quindi su un'origine diversa
    # dall'API raggiunta via tunnel: senza CORS il browser blocca le chiamate.
    if impostazioni.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=impostazioni.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
        )

    @app.get("/api/health", response_model=StatoSalute, summary="Health check")
    def health() -> JSONResponse:
        db_ok = db_raggiungibile(impostazioni.db_path)
        corpo = StatoSalute(
            stato="ok" if db_ok else "degradato",
            versione=_versione(),
            ambiente=impostazioni.ambiente,
            db="ok" if db_ok else "irraggiungibile",
        )
        # 503 quando il DB non risponde: è il segnale su cui lo smoke test
        # post-deploy fa scattare il rollback (§10).
        return JSONResponse(status_code=200 if db_ok else 503, content=corpo.model_dump())

    return app


app = crea_app()
