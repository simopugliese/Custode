"""Il calendario di Google, letto con httpx (§8.10).

**Perché non l'SDK di Google.** Qui si usano due chiamate: rinnovare il token e
chiedere l'elenco degli eventi. `google-api-python-client` più `google-auth` si
porterebbero dietro una catena di dipendenze e un client generato per tutte le
API di Google, su un arm64 dove ogni ruota in meno è tempo di build in meno. È
la stessa ragione per cui `deepseek.py` non usa l'SDK di OpenAI.

**Custode non scrive mai sul calendario.** Lo scope chiesto è
`calendar.readonly`, quindi non è una promessa del codice: è Google che
rifiuterebbe una scrittura anche se qualcuno la scrivesse per sbaglio.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from custode_calendario.config import ImpostazioniCalendario
from custode_calendario.errori import (
    AutorizzazioneNonValida,
    CalendarioNonConfigurato,
    CalendarioNonRaggiungibile,
)
from custode_calendario.evento import Evento

log = logging.getLogger("custode.calendario")

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

# Un margine sulla scadenza dell'access token: si rinnova un minuto prima che
# scada, invece di scoprirlo con un 401 a metà di una sincronizzazione.
MARGINE_SCADENZA = timedelta(seconds=60)

# Google pagina a 250 eventi per richiesta se non si dice altro; con la
# finestra di due settimane di §8.10 una pagina basta quasi sempre, ma
# `nextPageToken` va comunque seguito o si perderebbero eventi in silenzio.
PER_PAGINA = 250

SPIEGAZIONE_SCADUTA = (
    "l'autorizzazione al calendario non vale più. Le cause possibili sono tre:"
    " il progetto su Google Cloud è rimasto in «Testing» (lì i refresh token"
    " scadono dopo 7 giorni), hai revocato l'accesso, o hai cambiato la"
    " password dell'account. Rifai `custode-autorizza-calendario`."
)


class ClientGoogle:
    """Parla con Google. Non sa niente di Custode: prende date, dà eventi.

    Il client HTTP è iniettabile perché i test possano puntarlo a un finto
    Google che risponde davvero su HTTP, invece di sostituire questo oggetto:
    così si esercita anche il modo in cui la richiesta è costruita, che è
    esattamente la parte che si sbaglia.
    """

    def __init__(
        self,
        impostazioni: ImpostazioniCalendario,
        timezone: str,
        client: httpx.Client | None = None,
    ):
        self._impostazioni = impostazioni
        self._fuso = ZoneInfo(timezone)
        self._client = client
        self._access_token: str = ""
        self._scade_il: datetime | None = None

    def configurata(self) -> bool:
        return self._impostazioni.configurato()

    # — token —————————————————————————————————————————————

    def _token_valido(self) -> str:
        """L'access token, rinnovandolo se serve.

        L'access token vive un'ora e si tiene in memoria: un processo che gira
        per giorni farebbe altrimenti una chiamata di rinnovo per ogni
        sincronizzazione, cioè quasi una al minuto, per niente.
        """
        adesso_utc = datetime.now(UTC)
        if self._access_token and self._scade_il and adesso_utc < self._scade_il:
            return self._access_token

        if not self.configurata():
            raise CalendarioNonConfigurato(
                "mancano le credenziali del calendario: CALENDARIO_CLIENT_ID,"
                " CALENDARIO_CLIENT_SECRET e CALENDARIO_REFRESH_TOKEN"
            )

        dati = self._posta_token(
            {
                "client_id": self._impostazioni.client_id,
                "client_secret": self._impostazioni.client_secret,
                "refresh_token": self._impostazioni.refresh_token,
                "grant_type": "refresh_token",
            }
        )
        token = str(dati.get("access_token") or "")
        if not token:
            raise CalendarioNonRaggiungibile(f"risposta di Google senza access_token: {dati!r}")
        durata = dati.get("expires_in")
        secondi = (
            int(durata) if isinstance(durata, int | float | str) and str(durata).isdigit() else 3600
        )
        self._access_token = token
        self._scade_il = adesso_utc + timedelta(seconds=secondi) - MARGINE_SCADENZA
        return token

    def _posta_token(self, corpo: dict[str, str]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self._impostazioni.timeout_secondi)
        try:
            risposta = client.post(self._impostazioni.url_token, data=corpo)
        except httpx.HTTPError as errore:
            raise CalendarioNonRaggiungibile(f"Google non risponde: {errore}") from errore
        finally:
            if self._client is None:
                client.close()

        # `invalid_grant` è l'unico errore che non ha senso riprovare: il
        # permesso non c'è più, e va rifatto a mano. Distinguerlo qui evita che
        # il worker ci sbatta contro ogni cinque minuti per giorni.
        if risposta.status_code == 400 and _errore_di(risposta) == "invalid_grant":
            raise AutorizzazioneNonValida(SPIEGAZIONE_SCADUTA)
        if risposta.status_code >= 400:
            raise CalendarioNonRaggiungibile(
                f"Google ha risposto {risposta.status_code} al rinnovo del token"
            )
        return _json_o_errore(risposta)

    # — eventi ————————————————————————————————————————————

    def eventi(self, da: date, a: date) -> list[Evento]:
        """Gli eventi fra due giorni, estremi inclusi, ordinati per inizio."""
        token = self._token_valido()
        raccolti: list[Evento] = []
        pagina: str | None = None

        while True:
            dati = self._chiedi_eventi(token, da, a, pagina)
            for voce in dati.get("items") or []:
                if isinstance(voce, dict):
                    evento = self._evento_da(voce)
                    if evento is not None:
                        raccolti.append(evento)
            pagina = dati.get("nextPageToken") or None
            if not pagina:
                break

        # Google li restituisce già ordinati, ma l'ordine è ciò su cui il
        # motore di contesto ragiona: riordinare qui costa niente e toglie una
        # dipendenza da un comportamento del server.
        raccolti.sort(key=lambda e: (e.inizio, e.titolo))
        return raccolti

    def _chiedi_eventi(self, token: str, da: date, a: date, pagina: str | None) -> dict[str, Any]:
        parametri: dict[str, str] = {
            "timeMin": self._istante_iso(da, inizio=True),
            "timeMax": self._istante_iso(a + timedelta(days=1), inizio=True),
            # Espande le ricorrenze in occorrenze vere: senza, «lezione ogni
            # martedì» sarebbe **un** evento con una regola dentro, e «prima
            # della prossima lezione» non avrebbe un istante a cui riferirsi.
            "singleEvents": "true",
            "orderBy": "startTime",
            "showDeleted": "false",
            "maxResults": str(PER_PAGINA),
        }
        if pagina:
            parametri["pageToken"] = pagina

        indirizzo = (
            f"{self._impostazioni.url_api.rstrip('/')}"
            f"/calendars/{self._impostazioni.calendario_id}/events"
        )
        client = self._client or httpx.Client(timeout=self._impostazioni.timeout_secondi)
        try:
            risposta = client.get(
                indirizzo, params=parametri, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as errore:
            raise CalendarioNonRaggiungibile(f"Google non risponde: {errore}") from errore
        finally:
            if self._client is None:
                client.close()

        if risposta.status_code in (401, 403):
            raise AutorizzazioneNonValida(SPIEGAZIONE_SCADUTA)
        if risposta.status_code >= 400:
            raise CalendarioNonRaggiungibile(
                f"Google ha risposto {risposta.status_code} leggendo gli eventi"
            )
        return _json_o_errore(risposta)

    # — conversione ———————————————————————————————————————

    def _istante_iso(self, giorno: date, *, inizio: bool) -> str:
        """Un giorno locale come istante con fuso, che è ciò che Google vuole.

        Mandare una data nuda farebbe interpretare la finestra in UTC, e in
        Italia questo sposta gli estremi di una o due ore: gli eventi di prima
        mattina del primo giorno resterebbero fuori.
        """
        momento = datetime.combine(giorno, time.min, tzinfo=self._fuso)
        return momento.isoformat()

    def _evento_da(self, voce: dict[str, Any]) -> Evento | None:
        """Da un evento di Google a uno di Custode. `None` se non è utilizzabile."""
        if voce.get("status") == "cancelled":
            # Con `showDeleted=false` non dovrebbero arrivare, ma un'occorrenza
            # cancellata di una serie ricorrente ci arriva lo stesso: se
            # entrasse, farebbe scattare regole per una lezione disdetta.
            return None

        identificativo = str(voce.get("id") or "").strip()
        if not identificativo:
            return None

        inizio, tutto_il_giorno = self._momento(voce.get("start"), fine=False)
        fine, _ = self._momento(voce.get("end"), fine=True)
        if inizio is None or fine is None:
            return None
        if fine < inizio:
            # Non dovrebbe succedere, ma una durata negativa manderebbe in
            # confusione ogni conto fatto a valle: meglio scartarlo e dirlo.
            log.warning("evento %s scartato: finisce prima di iniziare", identificativo)
            return None

        return Evento(
            id=identificativo,
            # Un evento senza titolo esiste eccome, ed è normale su Google:
            # meglio una parola che una stringa vuota in mezzo a un messaggio.
            titolo=str(voce.get("summary") or "").strip() or "(senza titolo)",
            inizio=inizio,
            fine=fine,
            tutto_il_giorno=tutto_il_giorno,
            luogo=str(voce.get("location") or "").strip(),
            serie_id=str(voce.get("recurringEventId") or "").strip(),
        )

    def _momento(self, grezzo: object, *, fine: bool) -> tuple[datetime | None, bool]:
        """Google dice l'orario in due forme diverse, e vanno trattate diversamente.

        `dateTime` è un istante con fuso: si converte nel fuso di casa e si
        toglie il fuso, perché è la convenzione del progetto.

        `date` è un evento di giornata, e **non ha** un istante: `2026-09-12`
        significa «tutto il 12». La fine che Google manda è **esclusiva** — un
        evento di un giorno solo finisce il 13 — quindi va tirata indietro,
        altrimenti «sei impegnato» durerebbe un giorno in più.
        """
        if not isinstance(grezzo, dict):
            return None, False

        testo = grezzo.get("dateTime")
        if isinstance(testo, str) and testo:
            try:
                istante = datetime.fromisoformat(testo)
            except ValueError:
                return None, False
            if istante.tzinfo is None:
                # Senza fuso Google non dovrebbe mandarlo, ma se capita si
                # prende per ora locale invece di buttare via l'evento.
                return istante, False
            return istante.astimezone(self._fuso).replace(tzinfo=None), False

        giorno_testo = grezzo.get("date")
        if isinstance(giorno_testo, str) and giorno_testo:
            try:
                giorno = date.fromisoformat(giorno_testo)
            except ValueError:
                return None, True
            if fine:
                return datetime.combine(giorno - timedelta(days=1), time.max), True
            return datetime.combine(giorno, time.min), True

        return None, False


def _errore_di(risposta: httpx.Response) -> str:
    try:
        corpo = risposta.json()
    except ValueError:
        return ""
    return str(corpo.get("error", "")) if isinstance(corpo, dict) else ""


def _json_o_errore(risposta: httpx.Response) -> dict[str, Any]:
    try:
        valore = risposta.json()
    except ValueError as errore:
        raise CalendarioNonRaggiungibile("Google non ha risposto in JSON") from errore
    if not isinstance(valore, dict):
        raise CalendarioNonRaggiungibile(
            f"atteso un oggetto JSON, ricevuto {type(valore).__name__}"
        )
    return valore
