"""Applicazione FastAPI di Custode.

Tutti gli endpoint stanno sotto il prefisso `/api`, come da contratto in
`dashboard/API.md`. L'autenticazione non è gestita qui: davanti al tunnel c'è
Cloudflare Access, che lascia passare solo l'identità autorizzata (§2, §9).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from custode_api.rotte import (
    abitudini,
    assistente,
    diario,
    home,
    lista_spesa,
    non_attivi,
    spese,
    task,
)
from custode_api.rotte import calendario as rotta_calendario
from custode_api.rotte import impostazioni as rotta_impostazioni
from custode_bot.config import ImpostazioniBot, get_impostazioni_bot
from custode_calendario.config import ImpostazioniCalendario, get_impostazioni_calendario
from custode_core.config import Settings, get_settings, versione
from custode_core.db import connessione, db_raggiungibile
from custode_core.log import configura as configura_log
from custode_core.migrazioni import migra
from custode_router import Router
from custode_worker.config import ImpostazioniWorker, get_impostazioni_worker


class StatoSalute(BaseModel):
    """Corpo di `GET /api/health`, usato dallo smoke test post-deploy (§10)."""

    stato: Literal["ok", "degradato"]
    versione: str
    ambiente: str
    db: Literal["ok", "irraggiungibile"]
    migrazioni: Literal["ok", "fallite"]


def crea_app(
    settings: Settings | None = None,
    router: Router | None = None,
    calendario: ImpostazioniCalendario | None = None,
    bot: ImpostazioniBot | None = None,
    worker: ImpostazioniWorker | None = None,
) -> FastAPI:
    """Costruisce l'app. Parametrizzata sulle impostazioni per i test."""
    impostazioni = settings or get_settings()
    instradatore = router or Router()
    calendario_impostazioni = calendario or get_impostazioni_calendario()
    bot_impostazioni = bot or get_impostazioni_bot()
    worker_impostazioni = worker or get_impostazioni_worker()
    configura_log(impostazioni.log_level)
    log = logging.getLogger("custode.api")

    @asynccontextmanager
    async def ciclo_di_vita(app: FastAPI) -> AsyncIterator[None]:
        # Le migrazioni girano ad ogni avvio: sono idempotenti, e così un
        # deploy non richiede un passo manuale che ci si può dimenticare.
        #
        # Se falliscono l'app parte lo stesso, degradata: un processo che muore
        # all'avvio dà solo "connection refused" allo smoke test, mentre così
        # `/api/health` risponde 503 dicendo cosa non va (§10).
        app.state.migrazioni_ok = True
        try:
            with connessione(impostazioni.db_path) as conn:
                applicate = migra(conn)
        except Exception:
            app.state.migrazioni_ok = False
            log.exception("migrazioni fallite: l'API parte in stato degradato")
        else:
            if applicate:
                log.info("migrazioni applicate: %s", ", ".join(applicate))
        yield

    in_produzione = impostazioni.ambiente == "production"
    app = FastAPI(
        lifespan=ciclo_di_vita,
        title="Custode API",
        version=versione(),
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
        migrazioni_ok = bool(getattr(app.state, "migrazioni_ok", False))
        sano = db_ok and migrazioni_ok
        corpo = StatoSalute(
            stato="ok" if sano else "degradato",
            versione=versione(),
            ambiente=impostazioni.ambiente,
            db="ok" if db_ok else "irraggiungibile",
            migrazioni="ok" if migrazioni_ok else "fallite",
        )
        # 503 quando il DB non risponde: è il segnale su cui lo smoke test
        # post-deploy fa scattare il rollback (§10).
        return JSONResponse(status_code=200 if sano else 503, content=corpo.model_dump())

    app.include_router(assistente.router)
    app.include_router(rotta_calendario.router)
    app.include_router(diario.router)
    app.include_router(home.router)
    app.include_router(task.router)
    app.include_router(lista_spesa.router)
    app.include_router(spese.router)
    app.include_router(abitudini.router)
    app.include_router(rotta_impostazioni.router)
    # Per ultimo: i moduli non ancora attivi non devono coprire una rotta vera.
    app.include_router(non_attivi.router)

    # Le rotte leggono le impostazioni da qui (vedi `dipendenze.py`), così i
    # test possono costruire l'app puntandola a un database temporaneo.
    app.state.settings = impostazioni
    app.state.router = instradatore
    app.state.calendario = calendario_impostazioni
    app.state.bot = bot_impostazioni
    # Non per farci girare i job, ma per sapere da dove parte un'impostazione
    # calda che non hai mai salvato: giorno e ora del riepilogo nascono nel
    # `.env` del worker, ed è quello che la pagina deve mostrare (§8).
    app.state.worker = worker_impostazioni

    return app


app = crea_app()
