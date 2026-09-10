"""Client HTTP che parla con l'API vera, su un database vero su disco."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from custode_api.dipendenze import prendi_ora
from custode_api.main import crea_app
from custode_core.config import Settings

CAMPI_MESSAGGIO = frozenset({"segnale", "segnale_estratto", "segnale_domanda"})


class RouterFinto:
    """Al posto del modello: risponde l'intenzione che gli si dice."""

    def __init__(self) -> None:
        self.risposta: dict[str, Any] = {"azioni": [{"azione": "nessuna"}]}
        self.errore: Exception | None = None
        self.messaggi_visti: list[str] = []

    def interpreta_come(self, *azioni: dict[str, Any]) -> None:
        """Fa rispondere all'interprete queste azioni, nella forma vera.

        I test descrivono un'azione come un dizionario piatto — che si legge
        meglio — e qui finisce nella lista `azioni` dello schema, coi campi che
        riguardano il messaggio intero (il segnale) lasciati fuori. Chi invece
        deve fingere una risposta di **Claude** (una categoria di spesa, un
        riassunto) continua a scrivere `risposta` a mano: ha un'altra forma.
        """
        self.risposta = {
            "azioni": [{k: v for k, v in a.items() if k not in CAMPI_MESSAGGIO} for a in azioni],
            **{k: v for a in azioni for k, v in a.items() if k in CAMPI_MESSAGGIO},
        }

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.messaggi_visti.append(kwargs.get("utente", ""))
        if self.errore is not None:
            raise self.errore
        return self.risposta


@pytest.fixture
def modello() -> RouterFinto:
    return RouterFinto()


@pytest.fixture
def budget() -> float | None:
    """Nessun budget: è come nasce un'installazione (§8.5).

    Un test che vuole il blocco spese della Home ridefinisce questa fixture.
    """
    return None


@pytest.fixture
def client(
    fai_settings: Callable[..., Settings],
    db_path: Path,
    ora: datetime,
    modello: RouterFinto,
    budget: float | None,
) -> Iterator[TestClient]:
    """API completa su un DB temporaneo, con "adesso" fissato.

    Le migrazioni le applica l'avvio dell'app, come in produzione: il test
    esercita anche quel passaggio invece di preparare lo schema per conto suo.
    """
    app = crea_app(
        fai_settings(ambiente="test", db_path=db_path, budget_settimanale=budget),
        router=modello,  # type: ignore[arg-type]
    )
    # L'ora è iniettata: senza, le etichette ("oggi", "giovedì") e la sezione
    # in cui finisce un task dipenderebbero da quando girano i test.
    app.dependency_overrides[prendi_ora] = lambda: ora
    with TestClient(app) as attivo:
        yield attivo
