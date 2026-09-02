"""Client Claude, tramite l'SDK ufficiale `anthropic`.

Claude serve ai compiti di §6 che richiedono qualità, visione o ragionamento.
Oggi ci passano il riassunto del diario, il riepilogo settimanale, la rifusione
del profilo (§8.4) e la lettura degli scontrini (§8.5) — l'unica riga della
tabella che ha bisogno di far *vedere* qualcosa al modello.
"""

from __future__ import annotations

import json
from typing import Any

from custode_router.config import ImpostazioniRouter
from custode_router.errori import (
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)


class ClientClaude:
    """Wrapper attorno all'SDK `anthropic`.

    `client` è il punto di innesto per i test, tipizzato `Any`: la firma di
    `messages.create` nell'SDK è molto più ricca di ciò che serve qui, e un
    Protocol strutturale non riuscirebbe a combaciare con i suoi overload.
    """

    def __init__(self, impostazioni: ImpostazioniRouter, client: Any | None = None):
        self._impostazioni = impostazioni
        self._client = client

    def configurato(self) -> bool:
        return bool(self._impostazioni.anthropic_api_key) or self._client is not None

    def _cliente(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._impostazioni.anthropic_api_key:
            raise ProviderNonConfigurato("manca ROUTER_ANTHROPIC_API_KEY: Claude non è configurato")
        import anthropic

        return anthropic.Anthropic(
            api_key=self._impostazioni.anthropic_api_key,
            timeout=self._impostazioni.timeout_secondi,
        )

    def chiedi_json(
        self,
        *,
        sistema: str,
        utente: str,
        schema: dict[str, Any],
        immagine: bytes | None = None,
        media_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        """Una domanda a Claude con risposta in JSON conforme allo schema.

        `immagine` la allega al messaggio: è la strada della lettura degli
        scontrini (§6, §8.5), l'unico compito della tabella che ha bisogno di
        far vedere qualcosa al modello. L'immagine va **prima** del testo, come
        vuole l'API quando la domanda riguarda ciò che si vede.
        """
        contenuto: Any = utente
        if immagine is not None:
            import base64

            contenuto = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(immagine).decode(),
                    },
                },
                {"type": "text", "text": utente},
            ]

        cliente = self._cliente()
        try:
            risposta = cliente.messages.create(
                model=self._impostazioni.claude_modello,
                # Tetto suo, non quello di DeepSeek: sui modelli con
                # ragionamento adattivo i token di ragionamento contano qui
                # dentro (vedi `config.py`).
                max_tokens=self._impostazioni.max_token_risposta_claude,
                system=sistema,
                messages=[{"role": "user", "content": contenuto}],
                # Structured outputs: il formato lo garantisce l'API, non una
                # richiesta nel prompt che il modello può disattendere.
                output_config={
                    "format": {"type": "json_schema", "schema": schema},
                    "effort": self._impostazioni.claude_effort,
                },
            )
        except Exception as errore:  # l'SDK alza una gerarchia sua
            if type(errore).__name__ in ("AuthenticationError", "PermissionDeniedError"):
                raise ProviderNonConfigurato(f"Claude ha rifiutato la chiave: {errore}") from errore
            raise ProviderNonRaggiungibile(f"Claude non risponde: {errore}") from errore

        # Una decisione di sicurezza del modello non è un guasto di rete: va
        # distinta, altrimenti chi chiama riproverebbe all'infinito.
        motivo_arresto = getattr(risposta, "stop_reason", None)
        if motivo_arresto == "refusal":
            raise RispostaNonValida("Claude ha rifiutato di rispondere a questa richiesta")
        # Una risposta troncata è JSON incompleto: dirlo così com'è, invece di
        # lasciare che fallisca più avanti come "non ha risposto in JSON", è la
        # differenza fra alzare `max_token_risposta_claude` e cercare un bug
        # nel prompt.
        if motivo_arresto == "max_tokens":
            raise RispostaNonValida(
                "Claude ha esaurito i token prima di finire la risposta:"
                " alza ROUTER_MAX_TOKEN_RISPOSTA_CLAUDE"
            )

        return _primo_json(risposta)


def _primo_json(risposta: Any) -> dict[str, Any]:
    testi = [
        blocco.text
        for blocco in getattr(risposta, "content", [])
        if getattr(blocco, "type", None) == "text"
    ]
    if not testi:
        raise RispostaNonValida("Claude non ha prodotto testo")
    try:
        valore = json.loads(testi[0])
    except json.JSONDecodeError as errore:
        raise RispostaNonValida(f"Claude non ha risposto in JSON: {testi[0]!r}") from errore
    if not isinstance(valore, dict):
        raise RispostaNonValida(f"atteso un oggetto JSON, ricevuto {type(valore).__name__}")
    return valore
