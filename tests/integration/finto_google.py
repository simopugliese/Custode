"""Un finto Google che è un SERVER HTTP VERO (§8.10).

Non è un oggetto sostituito al client: è un server che parla il protocollo di
Google — endpoint del token e `events.list` — e a cui si punta il client vero
cambiandogli gli URL. Così i test esercitano anche *come* la richiesta è
costruita: gli estremi della finestra col fuso giusto, `singleEvents`,
l'header `Authorization`, il seguito delle pagine. Con un client finto in
memoria quella parte — che è esattamente quella che si sbaglia — non verrebbe
provata da niente.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class StatoFinto:
    """Cosa il finto Google deve rispondere, e cosa gli è stato chiesto."""

    def __init__(self) -> None:
        self.eventi: list[dict[str, Any]] = []
        self.pagine: list[list[dict[str, Any]]] = []
        """Se valorizzato, gli eventi arrivano a pagine invece che tutti insieme."""
        self.errore_token: tuple[int, dict[str, Any]] | None = None
        self.stato_eventi: int = 200
        self.durata_token: int = 3600
        self.richieste_token: list[dict[str, list[str]]] = []
        self.richieste_eventi: list[dict[str, list[str]]] = []
        self.autorizzazioni_viste: list[str] = []


class _Gestore(BaseHTTPRequestHandler):
    stato: StatoFinto

    def do_POST(self) -> None:  # noqa: N802
        lunghezza = int(self.headers.get("Content-Length") or 0)
        corpo = urllib.parse.parse_qs(self.rfile.read(lunghezza).decode("utf-8"))
        _Gestore.stato.richieste_token.append(corpo)

        errore = _Gestore.stato.errore_token
        if errore is not None:
            self._json(errore[0], errore[1])
            return

        if (corpo.get("grant_type") or [""])[0] == "authorization_code":
            self._json(
                200,
                {
                    "access_token": "access-nuovo",
                    "refresh_token": "refresh-nuovo",
                    "expires_in": _Gestore.stato.durata_token,
                },
            )
            return

        self._json(
            200,
            {"access_token": "access-nuovo", "expires_in": _Gestore.stato.durata_token},
        )

    def do_GET(self) -> None:  # noqa: N802
        pezzi = urllib.parse.urlparse(self.path)
        parametri = urllib.parse.parse_qs(pezzi.query)
        _Gestore.stato.richieste_eventi.append(parametri)
        _Gestore.stato.autorizzazioni_viste.append(self.headers.get("Authorization") or "")

        if _Gestore.stato.stato_eventi != 200:
            self._json(_Gestore.stato.stato_eventi, {"error": {"message": "no"}})
            return

        if _Gestore.stato.pagine:
            indice = int((parametri.get("pageToken") or ["0"])[0])
            voci = _Gestore.stato.pagine[indice]
            corpo: dict[str, Any] = {"items": voci}
            if indice + 1 < len(_Gestore.stato.pagine):
                corpo["nextPageToken"] = str(indice + 1)
            self._json(200, corpo)
            return

        self._json(200, {"items": _Gestore.stato.eventi})

    def _json(self, codice: int, corpo: dict[str, Any]) -> None:
        carico = json.dumps(corpo).encode("utf-8")
        self.send_response(codice)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(carico)))
        self.end_headers()
        self.wfile.write(carico)

    def log_message(self, *_args: object) -> None:
        """Zitto: i test non devono stampare una riga per richiesta."""


class FintoGoogle:
    """Il server, avviato su una porta libera scelta dal sistema."""

    def __init__(self) -> None:
        self.stato = StatoFinto()
        _Gestore.stato = self.stato
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Gestore)
        self._filo = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._filo.start()

    @property
    def base(self) -> str:
        porta = self._server.server_address[1]
        return f"http://127.0.0.1:{porta}"

    def chiudi(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._filo.join(timeout=5)
