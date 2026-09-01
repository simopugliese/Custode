"""Configurazione dei job schedulati (prefisso `WORKER_`)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

GiornoRiepilogo = Literal["domenica", "lunedi"]


class ImpostazioniWorker(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    giorno_riepilogo: GiornoRiepilogo = "domenica"
    """Quando chiudere la settimana del diario (§8.4).

    Corrisponde a `orari.riepilogoSettimanaleGiorno` del contratto della
    dashboard: quando `/api/impostazioni` esisterà, il valore verrà da lì e
    questa variabile resterà come default iniziale.
    """

    ora_riepilogo: str = "21:00"
    """Ora locale, HH:MM, nel fuso di `CUSTODE_TIMEZONE`."""

    intervallo_secondi: int = 300
    """Ogni quanto il worker si sveglia a chiedere cosa è dovuto.

    Cinque minuti: la precisione richiesta è quella di un promemoria serale, e
    un ciclo più stretto sarebbe solo CPU spesa per niente su un Pi condiviso.
    """

    def ora_e_minuto(self) -> tuple[int, int]:
        """Spezza `ora_riepilogo`. Una configurazione storta è un errore subito.

        Meglio che il worker si rifiuti di partire dicendo cosa c'è di sbagliato
        piuttosto che girare per giorni senza far scattare mai il job.
        """
        pezzi = self.ora_riepilogo.split(":")
        if len(pezzi) != 2:
            raise ValueError(f"WORKER_ORA_RIEPILOGO deve essere HH:MM, non {self.ora_riepilogo!r}")
        try:
            ore, minuti = int(pezzi[0]), int(pezzi[1])
        except ValueError as errore:
            raise ValueError(
                f"WORKER_ORA_RIEPILOGO deve essere HH:MM, non {self.ora_riepilogo!r}"
            ) from errore
        if not (0 <= ore <= 23 and 0 <= minuti <= 59):
            raise ValueError(f"orario fuori intervallo: {self.ora_riepilogo!r}")
        return ore, minuti


@lru_cache(maxsize=1)
def get_impostazioni_worker() -> ImpostazioniWorker:
    return ImpostazioniWorker()
