"""La barra «A Custode» della dashboard — `POST /api/assistente/messaggio`.

Stesso canale del bot Telegram (§8.1): il testo passa dallo stesso interprete e
produce le stesse azioni, così la dashboard e il bot non possono divergere.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_router import Router
from custode_router import assistente as dom_assistente

router = APIRouter(prefix="/api/assistente", tags=["assistente"])


@router.post(
    "/messaggio", response_model=schemi.RispostaAssistente, response_model_exclude_none=True
)
def messaggio(
    corpo: schemi.MessaggioAssistente, richiesta: Request, conn: ConnDip, ora: OraDip
) -> schemi.RispostaAssistente:
    instradatore: Router = richiesta.app.state.router
    esito = dom_assistente.interpreta_ed_esegui(conn, ora, corpo.testo, instradatore)
    # La dashboard invalida comunque le query della pagina dopo l'invio: qui
    # basta rimandare la frase da mostrare.
    return schemi.RispostaAssistente(rispostaLabel=esito.testo)
