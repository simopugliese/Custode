"""Client DeepSeek.

DeepSeek espone un'API compatibile con quella di OpenAI, ma qui se ne usa una
sola chiamata: scriverla con httpx — che è già una dipendenza — evita di
aggiungere l'SDK di OpenAI a un progetto che non usa OpenAI.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from custode_router.config import ImpostazioniRouter
from custode_router.errori import (
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)


def _istruzioni_schema(schema: dict[str, Any]) -> str:
    """DeepSeek garantisce JSON valido, non che rispetti uno schema preciso.

    Lo schema va quindi messo nel prompt, e il risultato validato da chi chiama.
    """
    return (
        "Rispondi esclusivamente con un oggetto JSON conforme a questo schema, "
        "senza testo attorno e senza blocchi di codice:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )


class ClientDeepSeek:
    def __init__(self, impostazioni: ImpostazioniRouter, client: httpx.Client | None = None):
        self._impostazioni = impostazioni
        self._client = client

    def configurato(self) -> bool:
        return bool(self._impostazioni.deepseek_api_key)

    def chiedi_json(self, *, sistema: str, utente: str, schema: dict[str, Any]) -> dict[str, Any]:
        if not self.configurato():
            raise ProviderNonConfigurato(
                "manca ROUTER_DEEPSEEK_API_KEY: DeepSeek non è configurato"
            )

        corpo = {
            "model": self._impostazioni.deepseek_modello,
            "messages": [
                {"role": "system", "content": f"{sistema}\n\n{_istruzioni_schema(schema)}"},
                {"role": "user", "content": utente},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self._impostazioni.max_token_risposta,
            # Un parser deve essere ripetibile: la stessa frase deve dare la
            # stessa interpretazione, non una a caso fra quelle plausibili.
            "temperature": 0,
            "stream": False,
        }

        client = self._client or httpx.Client(timeout=self._impostazioni.timeout_secondi)
        try:
            risposta = client.post(
                f"{self._impostazioni.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self._impostazioni.deepseek_api_key}"},
                json=corpo,
            )
            risposta.raise_for_status()
            dati = risposta.json()
        except httpx.HTTPError as errore:
            raise ProviderNonRaggiungibile(f"DeepSeek non risponde: {errore}") from errore
        finally:
            if self._client is None:
                client.close()

        try:
            testo = dati["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as errore:
            raise RispostaNonValida(f"risposta di DeepSeek inattesa: {dati!r}") from errore

        return _json_o_errore(testo)


def _json_o_errore(testo: str) -> dict[str, Any]:
    try:
        valore = json.loads(testo)
    except json.JSONDecodeError as errore:
        raise RispostaNonValida(f"il modello non ha risposto in JSON: {testo!r}") from errore
    if not isinstance(valore, dict):
        raise RispostaNonValida(f"atteso un oggetto JSON, ricevuto {type(valore).__name__}")
    return valore
