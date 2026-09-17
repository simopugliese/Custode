"""I moduli non ancora costruiti rispondono 501 spiegando cosa manca."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

# Resta solo §8.11. Le regole di contesto (§8.10) stavano qui fino al pezzo che
# le ha costruite: da lì in poi la pagina risponde 200, e `test_regole_api` è il
# posto dove si prova cosa dice.
PAGINE = [
    ("/api/lezioni", "lezioni e corsi"),
]


@pytest.mark.parametrize(("percorso", "modulo"), PAGINE)
def test_pagine_non_attive(client: TestClient, percorso: str, modulo: str) -> None:
    risposta = client.get(percorso)
    assert risposta.status_code == 501
    # Il motivo deve essere leggibile: la dashboard lo mostra così com'è.
    assert modulo in risposta.json()["detail"]


def test_le_mutazioni_dei_moduli_assenti(client: TestClient) -> None:
    assert client.post("/api/lezioni/piani/1/rigenera").status_code == 501
    assert client.post("/api/lezioni/piani/1/manda-al-bot").status_code == 501


def test_le_rotte_attive_non_sono_coperte(client: TestClient) -> None:
    # Gli stub 501 sono registrati per ultimi: non devono coprire una rotta vera.
    for percorso in (
        "/api/home",
        "/api/task",
        "/api/lista-spesa",
        "/api/spese",
        "/api/diario",
        "/api/abitudini",
        "/api/calendario",
        "/api/impostazioni",
        "/api/regole",
        "/api/health",
    ):
        assert client.get(percorso).status_code == 200
    assert client.post("/api/assistente/messaggio", json={"testo": "ciao"}).status_code == 200
