"""`custode-autorizza-calendario`: il permesso si chiede una volta sola (§8.10).

Questo è l'unico pezzo di Custode che ha bisogno di un **browser** e di una
persona che clicchi. Produce un `refresh_token` da incollare nel `.env`; da lì
in poi il resto del calendario funziona da solo.

**Perché il reindirizzamento su localhost e non il flusso «per dispositivi».**
Il flusso pensato per TV e dispositivi senza tastiera sarebbe più comodo su un
Pi headless — stampa un codice, lo digiti dal telefono — ma Google lo consente
solo per un sottoinsieme di permessi, e non ho potuto confermare che quello del
calendario ci sia dentro. Un flusso che fallisce con «invalid_scope» al primo
tentativo costerebbe più di quanto fa risparmiare. Il reindirizzamento su
localhost funziona con le credenziali «Desktop app» per qualunque permesso.

**Il Pi è headless: dove si lancia questo comando?** Dove c'è un browser. Sono
due strade, tutte e due documentate in DEPLOY.md:
- sul tuo computer, e poi il token si incolla nel `.env` del Pi;
- sul Pi via SSH, con `ssh -L 8765:localhost:8765`, così il browser del tuo
  computer raggiunge il server che questo comando apre sul Pi.

Il token viene **stampato**, non scritto: scriverlo in automatico vorrebbe dire
che questo comando sappia dove sta il `.env` di un ambiente che non conosce, e
un segreto scritto di nascosto è un segreto che poi non sai dove trovare.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import secrets
import threading
import urllib.parse
import webbrowser

import httpx

from custode_calendario.config import ImpostazioniCalendario, get_impostazioni_calendario
from custode_calendario.errori import CalendarioNonConfigurato, CalendarioNonRaggiungibile
from custode_calendario.google import SCOPE

PAGINA_FATTO = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><title>Custode</title></head>
<body style="font-family: system-ui; padding: 3rem; max-width: 30rem">
<h1>Fatto.</h1>
<p>Custode può leggere il tuo calendario. Torna al terminale: lì trovi il token
da incollare nel <code>.env</code>.</p>
<p>Questa finestra si può chiudere.</p>
</body></html>"""

PAGINA_ERRORE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><title>Custode</title></head>
<body style="font-family: system-ui; padding: 3rem; max-width: 30rem">
<h1>Non ha funzionato.</h1>
<p>Google ha risposto con un errore. Il terminale dice quale.</p>
</body></html>"""


def _verificatore() -> tuple[str, str]:
    """PKCE: un segreto usa-e-getta e la sua impronta.

    Serve perché queste sono credenziali di un'app **installata**: il
    `client_secret` sta su una macchina che non controlli del tutto, quindi non
    è davvero segreto. PKCE fa sì che il codice di autorizzazione intercettato
    da qualcun altro non basti a completare lo scambio.
    """
    verificatore = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    impronta = hashlib.sha256(verificatore.encode("ascii")).digest()
    return verificatore, base64.urlsafe_b64encode(impronta).decode().rstrip("=")


class _Raccoglitore(http.server.BaseHTTPRequestHandler):
    """Aspetta che Google rimandi qui il browser, e prende il codice."""

    codice: str = ""
    errore: str = ""
    stato_atteso: str = ""

    def do_GET(self) -> None:  # noqa: N802
        parametri = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        stato = (parametri.get("state") or [""])[0]
        if stato != _Raccoglitore.stato_atteso:
            # Senza questo controllo un'altra pagina aperta nel browser
            # potrebbe far arrivare qui un codice non nostro.
            _Raccoglitore.errore = "lo stato non combacia: richiesta ignorata"
            self._rispondi(400, PAGINA_ERRORE)
            return

        _Raccoglitore.errore = (parametri.get("error") or [""])[0]
        _Raccoglitore.codice = (parametri.get("code") or [""])[0]
        if _Raccoglitore.errore or not _Raccoglitore.codice:
            self._rispondi(400, PAGINA_ERRORE)
        else:
            self._rispondi(200, PAGINA_FATTO)

    def _rispondi(self, codice: int, pagina: str) -> None:
        corpo = pagina.encode("utf-8")
        self.send_response(codice)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *_args: object) -> None:
        """Zitto: la riga di log del server confonderebbe l'unica cosa da leggere."""


def indirizzo_consenso(impostazioni: ImpostazioniCalendario, *, impronta: str, stato: str) -> str:
    """La pagina di Google su cui l'utente dà il permesso.

    `access_type=offline` è ciò che fa arrivare un refresh token invece del
    solo access token; `prompt=consent` lo fa arrivare **anche** quando hai già
    autorizzato in passato — senza, una seconda autorizzazione tornerebbe senza
    token e sembrerebbe rotta.
    """
    parametri = {
        "client_id": impostazioni.client_id,
        "redirect_uri": f"http://localhost:{impostazioni.porta_autorizzazione}",
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": impronta,
        "code_challenge_method": "S256",
        "state": stato,
    }
    return f"{impostazioni.url_autorizzazione}?{urllib.parse.urlencode(parametri)}"


def scambia_codice(impostazioni: ImpostazioniCalendario, *, codice: str, verificatore: str) -> str:
    """Dal codice di un clic al refresh token. Ritorna il token."""
    corpo = {
        "client_id": impostazioni.client_id,
        "client_secret": impostazioni.client_secret,
        "code": codice,
        "code_verifier": verificatore,
        "grant_type": "authorization_code",
        "redirect_uri": f"http://localhost:{impostazioni.porta_autorizzazione}",
    }
    try:
        with httpx.Client(timeout=impostazioni.timeout_secondi) as client:
            risposta = client.post(impostazioni.url_token, data=corpo)
    except httpx.HTTPError as errore:
        raise CalendarioNonRaggiungibile(f"Google non risponde: {errore}") from errore

    if risposta.status_code >= 400:
        raise CalendarioNonRaggiungibile(
            f"Google ha rifiutato lo scambio ({risposta.status_code}): {risposta.text[:300]}"
        )
    dati = risposta.json()
    token = str(dati.get("refresh_token") or "")
    if not token:
        # Succede se manca `prompt=consent` e avevi già autorizzato: Google
        # manda solo l'access token, e senza refresh token non si va avanti.
        raise CalendarioNonRaggiungibile(
            "Google non ha mandato un refresh token. Togli l'accesso a Custode da"
            " myaccount.google.com/permissions e riprova."
        )
    return token


def principale() -> int:
    """Il comando vero e proprio. Ritorna il codice di uscita."""
    impostazioni = get_impostazioni_calendario()
    if not (impostazioni.client_id and impostazioni.client_secret):
        raise CalendarioNonConfigurato(
            "mancano CALENDARIO_CLIENT_ID e CALENDARIO_CLIENT_SECRET nel .env:"
            " creali su console.cloud.google.com come credenziali «Desktop app»."
        )

    verificatore, impronta = _verificatore()
    stato = secrets.token_urlsafe(24)
    _Raccoglitore.codice = ""
    _Raccoglitore.errore = ""
    _Raccoglitore.stato_atteso = stato

    server = http.server.HTTPServer(
        (impostazioni.ascolta_su, impostazioni.porta_autorizzazione), _Raccoglitore
    )
    filo = threading.Thread(target=server.handle_request, daemon=True)
    filo.start()

    indirizzo = indirizzo_consenso(impostazioni, impronta=impronta, stato=stato)
    print("\nApri questo indirizzo nel browser e dai il permesso a Custode:\n")
    print(indirizzo, "\n")
    # Se un browser c'è, si apre da solo; se siamo via SSH non succede niente e
    # resta l'indirizzo stampato sopra, che è la strada normale sul Pi.
    with contextlib.suppress(Exception):
        webbrowser.open(indirizzo)

    print("Aspetto che tu dia il permesso…")
    filo.join(timeout=300)
    server.server_close()

    if _Raccoglitore.errore:
        print(f"\nGoogle ha risposto con un errore: {_Raccoglitore.errore}")
        return 1
    if not _Raccoglitore.codice:
        print("\nNessuna risposta entro cinque minuti. Riprova.")
        return 1

    token = scambia_codice(impostazioni, codice=_Raccoglitore.codice, verificatore=verificatore)
    print("\nFatto. Metti questa riga nel .env del Pi e riavvia i servizi:\n")
    print(f"CALENDARIO_REFRESH_TOKEN={token}\n")
    print(
        "Se il progetto su Google Cloud è ancora in «Testing», questo token"
        " scade fra 7 giorni: metti la schermata di consenso «In production».\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principale())
