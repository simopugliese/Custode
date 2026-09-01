"""Client del servizio Whisper (§8.1).

Il bot scarica il vocale da Telegram e lo manda al container `whisper` sulla
rete interna di Docker. L'audio non esce di casa in nessun momento.
"""

from __future__ import annotations

import httpx


class TrascrizioneNonRiuscita(RuntimeError):
    """Il servizio non ha prodotto un testo: audio incomprensibile o servizio giù."""


class ClientWhisper:
    def __init__(self, base_url: str, timeout: float = 180.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def configurato(self) -> bool:
        return bool(self._base_url)

    def trascrivi(self, audio: bytes, nome_file: str = "vocale.ogg") -> str:
        if not self.configurato():
            raise TrascrizioneNonRiuscita("il servizio di trascrizione non è configurato")
        try:
            with httpx.Client(timeout=self._timeout) as client:
                risposta = client.post(
                    f"{self._base_url}/trascrivi",
                    files={"audio": (nome_file, audio, "application/octet-stream")},
                )
        except httpx.HTTPError as errore:
            raise TrascrizioneNonRiuscita(f"servizio non raggiungibile: {errore}") from errore

        if risposta.status_code == 422:
            # L'audio è arrivato ma non se ne cava niente: è un problema
            # dell'audio, non del servizio, e va detto in modo diverso.
            raise TrascrizioneNonRiuscita(
                _dettaglio(risposta) or "non sono riuscito a capire l'audio"
            )
        if risposta.status_code >= 400:
            raise TrascrizioneNonRiuscita(f"errore del servizio ({risposta.status_code})")

        testo = str(risposta.json().get("testo", "")).strip()
        if not testo:
            raise TrascrizioneNonRiuscita("trascrizione vuota")
        return testo


def _dettaglio(risposta: httpx.Response) -> str:
    try:
        return str(risposta.json().get("detail", ""))
    except ValueError:
        return ""
