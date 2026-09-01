"""Mandare un messaggio su Telegram, senza `python-telegram-bot`.

Il worker deve solo *spedire*: i tap sui bottoni li riceve e li gestisce il
bot, che è già in long polling. Per una sola chiamata HTTP non vale la pena
mettere la libreria del bot (e le sue dipendenze) anche in questa immagine —
`httpx` c'è già perché serve a DeepSeek.

I `callback_data` dei bottoni sono costruiti con `custode_bot.azioni`, lo stesso
modulo che poi li rilegge nel bot: è esattamente ciò che quel modulo esiste per
evitare, cioè che la stringa venga scritta a mano in un punto e letta a mano in
un altro.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from custode_bot.risposte import Risposta

log = logging.getLogger("custode.worker")


class InvioNonRiuscito(RuntimeError):
    """Telegram non ha accettato il messaggio."""


class ClientTelegram:
    """Il minimo per mandare un messaggio con dei bottoni inline.

    `client` è iniettabile: i test fanno passare le richieste per un trasporto
    finto invece che per la rete.
    """

    def __init__(
        self,
        token: str,
        chat_id: int,
        *,
        client: httpx.Client | None = None,
        timeout_secondi: float = 15.0,
    ):
        self._token = token
        self._chat_id = chat_id
        self._client = client
        self._timeout = timeout_secondi

    def configurato(self) -> bool:
        return bool(self._token) and self._chat_id > 0

    def manda(self, risposta: Risposta) -> None:
        if not self.configurato():
            raise InvioNonRiuscito("mancano TELEGRAM_BOT_TOKEN o TELEGRAM_ALLOWED_USER_ID")

        corpo: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": risposta.testo,
            "parse_mode": "HTML",
        }
        if risposta.bottoni:
            corpo["reply_markup"] = json.dumps(
                {
                    "inline_keyboard": [
                        [{"text": b.testo, "callback_data": b.dato} for b in riga]
                        for riga in risposta.bottoni
                    ]
                }
            )

        cliente = self._client or httpx.Client(timeout=self._timeout)
        try:
            risultato = cliente.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage", json=corpo
            )
            risultato.raise_for_status()
        except httpx.HTTPError as errore:
            raise InvioNonRiuscito(f"Telegram non risponde: {errore}") from errore
        finally:
            if self._client is None:
                cliente.close()
