"""Chi riceve l'avviso della CI e fa partire `deploy.sh`.

Due richieste, entrambe firmate (vedi `firma.py`) e già filtrate da Cloudflare
Access prima di arrivare qui:

    POST /deploy         →  202 {"id": "…"}      mette in coda un deploy
    GET  /stato/<id>     →  200 {"stato": …}     com'è andato (la CI aspetta)

Il corpo della richiesta **non conta**: il commit da installare lo decide
`deploy.sh` leggendo `origin/main`. Anche con tutti e due i segreti in mano,
chi chiama può chiedere «aggiorna», non «installa questo».

Gira come servizio systemd sull'host (DEPLOY.md §6) e usa solo la libreria
standard: il Pi non ha bisogno di un ambiente Python per ricevere un deploy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from custode_deploy.firma import verifica

# Gli exit code di `deploy.sh`. Stanno qui e nello script: se ne cambi uno,
# cambia anche l'altro (c'è un test che li tiene allineati).
STATI_PER_CODICE = {
    0: "ok",
    10: "rifiutato",  # la CI non è tutta verde
    11: "rollback",  # il nuovo non sta in piedi, è tornato al precedente
    12: "da_guardare",  # serve una mano: migrazione toccata o rollback fallito
}
STATO_FALLITO = "fallito"

MAX_CORPO = 4096
MAX_LAVORI_RICORDATI = 20
# Il deploy più lungo è quello che ricompila whisper.cpp da zero.
TIMEOUT_DEPLOY_SECONDI = 30 * 60

Esecutore = Callable[[Sequence[str]], tuple[int, str]]


def esegui_comando(comando: Sequence[str]) -> tuple[int, str]:
    """Lancia il comando e dà `(exit code, ultima riga stampata)`.

    Ogni riga che il comando stampa (anche sugli errori) viene riscritta subito
    sullo standard output del listener, che systemd manda nel journal: così
    `journalctl -u custode-deploy -f` mostra il deploy mentre accade, e un
    deploy fallito si rilegge dopo. Alla CI e a Telegram ne arriva solo l'ultima
    riga, come prima.
    """
    processo = subprocess.Popen(
        list(comando),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    scaduto = threading.Event()

    def ferma() -> None:
        scaduto.set()
        processo.kill()

    timer = threading.Timer(TIMEOUT_DEPLOY_SECONDI, ferma)
    timer.start()
    ultima = ""
    try:
        assert processo.stdout is not None
        for riga in processo.stdout:
            print(f"[deploy] {riga.rstrip()}", flush=True)
            if riga.strip():
                ultima = riga.strip()
        processo.wait()
    finally:
        timer.cancel()
    if scaduto.is_set():
        return 1, "il deploy ha superato il tempo massimo"
    return processo.returncode, ultima


class Servizio:
    """La logica del listener, senza HTTP: si prova passando richieste finte."""

    def __init__(
        self,
        segreto: str,
        comando: Sequence[str],
        *,
        esecutore: Esecutore = esegui_comando,
        ora: Callable[[], float] = time.time,
        in_background: bool = True,
    ):
        if not segreto:
            raise ValueError("il segreto per le firme non può essere vuoto")
        self._segreto = segreto
        self._comando = list(comando)
        self._esecutore = esecutore
        self._ora = ora
        self._in_background = in_background
        self._lavori: dict[str, dict[str, str]] = {}
        # Un deploy alla volta, in fila: `deploy.sh` prende comunque l'ultimo
        # `origin/main`, quindi due richieste ravvicinate non installano
        # versioni diverse, la seconda è solo una conferma.
        self._uno_alla_volta = threading.Lock()
        self._mutex = threading.Lock()

    def gestisci(
        self, metodo: str, percorso: str, intestazioni: Mapping[str, str], corpo: bytes
    ) -> tuple[int, dict[str, Any]]:
        # I nomi degli header sono case-insensitive in HTTP, e passando da
        # Cloudflare possono arrivare in minuscolo: si cercano così.
        header = {nome.lower(): valore for nome, valore in intestazioni.items()}
        valida = verifica(
            self._segreto,
            header.get("x-custode-timestamp"),
            header.get("x-custode-firma"),
            metodo,
            percorso,
            corpo,
            self._ora(),
        )
        if not valida:
            # Lo stesso messaggio per ogni causa: non dire cosa non andava.
            return 401, {"errore": "non autorizzato"}

        if metodo == "POST" and percorso == "/deploy":
            return 202, {"id": self._accoda()}
        if metodo == "GET" and percorso.startswith("/stato/"):
            lavoro = self._lavori.get(percorso.removeprefix("/stato/"))
            if lavoro is None:
                return 404, {"errore": "deploy sconosciuto"}
            return 200, dict(lavoro)
        return 404, {"errore": "percorso sconosciuto"}

    def _accoda(self) -> str:
        id_lavoro = uuid.uuid4().hex[:12]
        with self._mutex:
            self._lavori[id_lavoro] = {"stato": "in_coda", "messaggio": ""}
            # Si ricordano solo gli ultimi: la CI chiede dell'ultimo, subito.
            for vecchio in list(self._lavori)[:-MAX_LAVORI_RICORDATI]:
                del self._lavori[vecchio]
        if self._in_background:
            threading.Thread(target=self._esegui, args=(id_lavoro,), daemon=True).start()
        else:
            self._esegui(id_lavoro)
        return id_lavoro

    def _esegui(self, id_lavoro: str) -> None:
        with self._uno_alla_volta:
            self._lavori[id_lavoro] = {"stato": "in_corso", "messaggio": ""}
            codice, messaggio = self._esecutore(self._comando)
            stato = STATI_PER_CODICE.get(codice, STATO_FALLITO)
            self._lavori[id_lavoro] = {"stato": stato, "messaggio": messaggio}


def _gestore(servizio: Servizio) -> type[BaseHTTPRequestHandler]:
    class Gestore(BaseHTTPRequestHandler):
        def _risponde(self, metodo: str) -> None:
            lunghezza = int(self.headers.get("Content-Length") or 0)
            if lunghezza > MAX_CORPO:
                self._scrive(413, {"errore": "corpo troppo grande"})
                return
            corpo = self.rfile.read(lunghezza) if lunghezza else b""
            codice, risposta = servizio.gestisci(metodo, self.path, dict(self.headers), corpo)
            self._scrive(codice, risposta)

        def _scrive(self, codice: int, risposta: dict[str, Any]) -> None:
            dati = json.dumps(risposta).encode()
            self.send_response(codice)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dati)))
            self.end_headers()
            self.wfile.write(dati)

        def do_GET(self) -> None:
            self._risponde("GET")

        def do_POST(self) -> None:
            self._risponde("POST")

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")

    return Gestore


def main() -> int:
    segreto = os.environ.get("CUSTODE_DEPLOY_SEGRETO", "")
    if not segreto:
        print("manca CUSTODE_DEPLOY_SEGRETO: il listener non parte senza", file=sys.stderr)
        return 2
    host, _, porta = os.environ.get("CUSTODE_DEPLOY_ASCOLTA", "127.0.0.1:9000").rpartition(":")
    script = Path(__file__).resolve().parent.parent / "deploy.sh"
    servizio = Servizio(segreto, ["bash", str(script)])
    ThreadingHTTPServer((host, int(porta)), _gestore(servizio)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
