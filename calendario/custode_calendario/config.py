"""Configurazione della lettura del calendario (prefisso `CALENDARIO_`).

Le credenziali non hanno default: senza, la sorgente si dichiara **non
configurata** e chi la usa lo dice invece di fallire in rete (§9), esattamente
come fa il router quando manca la chiave di un modello.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ImpostazioniCalendario(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CALENDARIO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str = ""
    client_secret: str = ""
    """Le credenziali OAuth del progetto su Google Cloud, tipo «Desktop app»."""

    refresh_token: str = ""
    """Il permesso di leggere il calendario, ottenuto una volta sola.

    Lo produce `custode-autorizza-calendario` e sta nel `.env` come ogni altra
    credenziale del progetto, invece che in un file suo dentro un volume. Due
    ragioni: una sola convenzione per i segreti, e un backup del database che
    non si porta dietro un token — un ripristino di tre mesi fa
    rimetterebbe in circolo un permesso che nel frattempo hai revocato.

    Google non ruota i refresh token per le app installate: resta valido finché
    non lo revochi tu o non scade (vedi `AutorizzazioneNonValida`). Se un
    giorno cominciasse a ruotare, questo campo diventerebbe un file scrivibile.
    """

    calendario_id: str = "primary"
    """Quale calendario leggere. «primary» è quello principale dell'account."""

    giorni_indietro: int = 1
    giorni_avanti: int = 14
    """Quanta finestra sincronizzare.

    Indietro serve poco — un giorno, per il «dopo_evento» di ieri sera che
    deve ancora scattare. Avanti bastano due settimane: le regole guardano al
    massimo qualche ora avanti, e una finestra più larga sarebbe solo roba da
    tenere aggiornata.
    """

    timeout_secondi: float = 20.0

    # Sostituibili perché i test possano puntare a un finto Google che parla lo
    # stesso protocollo. In esercizio non si toccano.
    url_token: str = "https://oauth2.googleapis.com/token"
    url_autorizzazione: str = "https://accounts.google.com/o/oauth2/v2/auth"
    url_api: str = "https://www.googleapis.com/calendar/v3"

    porta_autorizzazione: int = 8765
    """Dove il comando di autorizzazione aspetta la risposta di Google.

    Google rimanda il browser su `http://localhost:<porta>`: il comando ci
    tiene aperto un server per il tempo di un clic. Deve combaciare con l'URI
    di reindirizzamento registrato nelle credenziali.
    """

    ascolta_su: str = "127.0.0.1"
    """Su quale interfaccia il comando di autorizzazione aspetta il clic.

    Solo il computer stesso, per impostazione predefinita: quel server vive il
    tempo di una richiesta, ma è comunque una porta aperta e non ha senso che
    la veda la rete di casa. Va portato a `0.0.0.0` **solo** se lo lanci dentro
    un container, dove `127.0.0.1` è l'interno del container e il browser non
    lo raggiungerebbe. Vedi DEPLOY.md.
    """

    def configurato(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)


@lru_cache(maxsize=1)
def get_impostazioni_calendario() -> ImpostazioniCalendario:
    return ImpostazioniCalendario()
