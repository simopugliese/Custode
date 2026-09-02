"""Il router: dato un compito, sceglie il provider e gli parla.

Chi chiama nomina il *compito* (§6), mai il modello: la scelta sta nella
tabella in `compiti.py`, così cambiarla non richiede di toccare i moduli.
"""

from __future__ import annotations

import logging
from typing import Any

from custode_router.claude import ClientClaude
from custode_router.compiti import CON_IMMAGINI, Compito, Provider, motivo, provider_per
from custode_router.config import ImpostazioniRouter, get_impostazioni_router
from custode_router.deepseek import ClientDeepSeek
from custode_router.errori import CompitoNonSupportato

log = logging.getLogger("custode.router")


class Router:
    def __init__(
        self,
        impostazioni: ImpostazioniRouter | None = None,
        *,
        deepseek: ClientDeepSeek | None = None,
        claude: ClientClaude | None = None,
    ):
        self._impostazioni = impostazioni or get_impostazioni_router()
        self._deepseek = deepseek or ClientDeepSeek(self._impostazioni)
        self._claude = claude or ClientClaude(self._impostazioni)

    def provider(self, compito: Compito) -> Provider:
        return provider_per(compito)

    def configurato_per(self, compito: Compito) -> bool:
        """Se il provider a cui il compito è instradato ha una chiave."""
        if provider_per(compito) is Provider.DEEPSEEK:
            return self._deepseek.configurato()
        return self._claude.configurato()

    def chiedi_json(
        self, compito: Compito, *, sistema: str, utente: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        if compito in CON_IMMAGINI:
            raise CompitoNonSupportato(
                f"«{compito}» ha bisogno di un'immagine: usa chiedi_json_con_immagine"
            )

        scelto = provider_per(compito)
        log.debug("compito %s → %s (%s)", compito, scelto, motivo(compito))
        client = self._deepseek if scelto is Provider.DEEPSEEK else self._claude
        return client.chiedi_json(sistema=sistema, utente=utente, schema=schema)

    def chiedi_json_con_immagine(
        self,
        compito: Compito,
        *,
        sistema: str,
        utente: str,
        schema: dict[str, Any],
        immagine: bytes,
        media_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        """Come `chiedi_json`, ma facendo vedere un'immagine al modello.

        Solo per i compiti che §6 marca come vision: instradarci qualcos'altro
        vorrebbe dire mandare un'immagine a un modello scelto per un compito di
        testo, e §6 quella scelta l'ha fatta guardando proprio questo.
        """
        if compito not in CON_IMMAGINI:
            raise CompitoNonSupportato(f"«{compito}» non è un compito con immagini (§6)")

        scelto = provider_per(compito)
        log.debug("compito %s → %s (%s), con immagine", compito, scelto, motivo(compito))
        if scelto is not Provider.CLAUDE:
            # Oggi non può succedere — §6 manda a Claude l'unica riga vision —
            # ma se un giorno la tabella cambiasse, meglio un errore chiaro che
            # un client di testo che riceve dei byte.
            raise CompitoNonSupportato(f"il provider di «{compito}» non legge immagini")
        return self._claude.chiedi_json(
            sistema=sistema,
            utente=utente,
            schema=schema,
            immagine=immagine,
            media_type=media_type,
        )
