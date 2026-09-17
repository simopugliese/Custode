"""Un finto Anthropic che è un SERVER HTTP VERO (§6).

Stessa idea di `finto_google.py`, e per la stessa ragione. Non è un client
sostituito in memoria: è un server che parla il protocollo delle Messages API, e
a cui si punta l'SDK `anthropic` **vero** tramite `ANTHROPIC_BASE_URL`. Così un
test esercita anche tutto ciò che sta fra il compito e la risposta — la scelta
del provider in `custode_router.router`, il corpo che `ClientClaude` costruisce
(modello, `max_tokens`, `output_config` con lo schema JSON), l'SDK, l'HTTP, e la
rilettura della risposta. Con un router finto quella parte non la prova niente,
ed è proprio la parte che non si può provare sul Pi senza spendere.

`ANTHROPIC_BASE_URL` è una variabile che legge l'SDK, non il progetto: per
questo non c'è niente da cambiare in `custode_router.config` per puntarci, e per
questo un test che la usa sta esercitando il client di produzione e non una sua
variante.

**Quello che il finto non fa** va detto, o si crede di aver provato più di
quanto si è provato: non valida lo schema che riceve, non conta i token e non
ragiona. Che la risposta sia conforme allo schema lo garantisce l'API vera
(structured outputs); qui la risposta la decide il test, ed è giusto così —
serve a provare cosa fa *Custode* con una risposta, non cosa risponde Claude.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class StatoFinto:
    """Cosa il finto Anthropic deve rispondere, e cosa gli è stato chiesto."""

    def __init__(self) -> None:
        self.risposta: dict[str, Any] = {}
        """Il JSON che il modello «produce», come corpo di un blocco di testo."""
        self.testo_grezzo: str | None = None
        """Se valorizzato, vince su `risposta`: serve a provare cosa succede
        quando il modello non risponde in JSON."""
        self.stop_reason: str = "end_turn"
        """`refusal` e `max_tokens` sono i due casi che `ClientClaude` distingue
        da un guasto di rete, e da qui si possono far succedere davvero."""
        self.stato: int = 200
        self.richieste: list[dict[str, Any]] = []
        """I corpi ricevuti: è dove si guarda *cosa* è stato chiesto al modello."""


class _Gestore(BaseHTTPRequestHandler):
    stato: StatoFinto

    def do_POST(self) -> None:  # noqa: N802
        lunghezza = int(self.headers.get("Content-Length") or 0)
        corpo = json.loads(self.rfile.read(lunghezza).decode("utf-8") or "{}")
        _Gestore.stato.richieste.append(corpo)

        if _Gestore.stato.stato != 200:
            self._json(
                _Gestore.stato.stato,
                {"type": "error", "error": {"type": "api_error", "message": "finto"}},
            )
            return

        testo = _Gestore.stato.testo_grezzo
        if testo is None:
            testo = json.dumps(_Gestore.stato.risposta, ensure_ascii=False)
        self._json(
            200,
            {
                "id": "msg_finto",
                "type": "message",
                "role": "assistant",
                "model": corpo.get("model", "claude-opus-5"),
                "content": [{"type": "text", "text": testo}],
                "stop_reason": _Gestore.stato.stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    def _json(self, codice: int, corpo: dict[str, Any]) -> None:
        grezzo = json.dumps(corpo).encode("utf-8")
        self.send_response(codice)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(grezzo)))
        self.end_headers()
        self.wfile.write(grezzo)

    def log_message(self, *_args: object) -> None:
        """Zitto: il server gira dentro i test."""


class FintoAnthropic:
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
