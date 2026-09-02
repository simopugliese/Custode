"""Configurazione dei job schedulati (prefisso `WORKER_`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
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

    ora_backup: str = "03:30"
    """Quando fare il backup giornaliero del database (§9), HH:MM locali.

    Di notte: la copia è coerente e non ferma niente, ma su un Pi condiviso
    conviene comunque che il momento di I/O più pesante della giornata non
    capiti mentre stai usando il bot.
    """

    backup_cartella: Path = Path("/backup")
    """Dove finiscono i backup, *dentro* il container.

    §13 dice «sul secondo disco già presente sul Pi»: il collegamento fra quel
    disco e questo percorso lo fa il volume in docker-compose.yml. Tenerlo
    configurabile evita di inchiodare nel codice il mount point di una macchina.
    """

    backup_chiave: str = ""
    """Chiave Fernet per cifrare i backup (§9). Vuota = backup in chiaro.

    Senza chiave il backup si fa lo stesso e si vede a occhio che non è cifrato
    (l'estensione cambia): il rischio più probabile è la scheda che si rompe, e
    da quello protegge anche un backup in chiaro. Ma **la chiave va conservata
    fuori dal Pi**: un backup che non sai aprire non è un backup.
    """

    intervallo_secondi: int = 300
    """Ogni quanto il worker si sveglia a chiedere cosa è dovuto.

    Cinque minuti: la precisione richiesta è quella di un promemoria serale, e
    un ciclo più stretto sarebbe solo CPU spesa per niente su un Pi condiviso.
    """

    def ora_e_minuto(self) -> tuple[int, int]:
        """Spezza `ora_riepilogo`."""
        return _leggi_orario(self.ora_riepilogo, "WORKER_ORA_RIEPILOGO")

    def ora_e_minuto_backup(self) -> tuple[int, int]:
        """Spezza `ora_backup`."""
        return _leggi_orario(self.ora_backup, "WORKER_ORA_BACKUP")


def _leggi_orario(valore: str, variabile: str) -> tuple[int, int]:
    """HH:MM, o un errore subito.

    Meglio che il worker si rifiuti di partire dicendo cosa c'è di sbagliato
    piuttosto che girare per giorni senza far scattare mai il job.
    """
    pezzi = valore.split(":")
    if len(pezzi) != 2:
        raise ValueError(f"{variabile} deve essere HH:MM, non {valore!r}")
    try:
        ore, minuti = int(pezzi[0]), int(pezzi[1])
    except ValueError as errore:
        raise ValueError(f"{variabile} deve essere HH:MM, non {valore!r}") from errore
    if not (0 <= ore <= 23 and 0 <= minuti <= 59):
        raise ValueError(f"{variabile}: orario fuori intervallo, {valore!r}")
    return ore, minuti


@lru_cache(maxsize=1)
def get_impostazioni_worker() -> ImpostazioniWorker:
    return ImpostazioniWorker()
