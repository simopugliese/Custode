"""Servizio HTTP di trascrizione: `POST /trascrivi`.

Raggiungibile solo sulla rete interna di Docker — non passa dal tunnel e non è
esposto a nessuno. Nessuna autenticazione qui: chi può parlare con questo
container è già dentro casa (§2, §9).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel

from custode_core.log import configura as configura_log
from custode_whisper.config import ImpostazioniWhisper, get_impostazioni_whisper
from custode_whisper.trascrizione import ErroreTrascrizione, trascrivi


class Trascrizione(BaseModel):
    testo: str


class StatoWhisper(BaseModel):
    stato: str
    modello: str
    modello_presente: bool


def crea_app(impostazioni: ImpostazioniWhisper | None = None) -> FastAPI:
    conf = impostazioni or get_impostazioni_whisper()
    configura_log(conf.log_level)

    app = FastAPI(title="Custode Whisper", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health", response_model=StatoWhisper)
    def health() -> StatoWhisper:
        presente = conf.modello.exists()
        return StatoWhisper(
            stato="ok" if presente else "degradato",
            modello=conf.modello.name,
            modello_presente=presente,
        )

    @app.post("/trascrivi", response_model=Trascrizione)
    async def trascrivi_audio(
        audio: UploadFile, contesto: Annotated[str, Form()] = ""
    ) -> Trascrizione:
        """`contesto`: i nomi che il proprietario usa, per non farli sbagliare.

        Facoltativo, e il servizio resta **senza stato**: quei nomi stanno nel
        database, che è del bot, non di qui. Chi chiama li manda insieme
        all'audio invece di far leggere il database a questo container — che
        altrimenti dovrebbe montarselo solo per questo.
        """
        contenuto = await audio.read()
        try:
            return Trascrizione(testo=trascrivi(contenuto, conf, contesto))
        except ErroreTrascrizione as errore:
            # 422: l'audio è arrivato ma non se ne cava un testo. Chi chiama lo
            # distingue da un 500, che sarebbe un guasto del servizio.
            raise HTTPException(status_code=422, detail=str(errore)) from errore

    return app


app = crea_app()
