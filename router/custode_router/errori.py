"""Errori del router, distinti per come vanno gestiti a monte."""

from __future__ import annotations


class ErroreRouter(Exception):
    """Base: qualcosa è andato storto nel far rispondere un modello."""


class ProviderNonConfigurato(ErroreRouter):
    """Manca la chiave API del provider a cui il compito è instradato.

    Non è un guasto: è una configurazione incompleta, e chi chiama può dirlo
    all'utente in modo comprensibile invece di mostrare un errore di rete.
    """


class ProviderNonRaggiungibile(ErroreRouter):
    """Il provider non ha risposto, o ha risposto con un errore.

    Riguarda la rete o il servizio remoto: riprovare più tardi ha senso.
    """


class RispostaNonValida(ErroreRouter):
    """Il modello ha risposto, ma non con il JSON richiesto."""


class CompitoNonSupportato(ErroreRouter):
    """Il compito esiste in §6 ma non è ancora implementato qui.

    È il caso della lettura degli scontrini, che ha bisogno di mandare
    un'immagine: arriverà col modulo spese (§8.5).
    """
