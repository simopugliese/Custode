"""I moduli non ancora costruiti rispondono 501 spiegando cosa manca."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

PAGINE = [
    ("/api/lezioni", "lezioni e corsi"),
    ("/api/regole", "regole di contesto"),
    ("/api/impostazioni", "impostazioni"),
]


@pytest.mark.parametrize(("percorso", "modulo"), PAGINE)
def test_pagine_non_attive(client: TestClient, percorso: str, modulo: str) -> None:
    risposta = client.get(percorso)
    assert risposta.status_code == 501
    # Il motivo deve essere leggibile: la dashboard lo mostra così com'è.
    assert modulo in risposta.json()["detail"]


def test_le_mutazioni_dei_moduli_assenti(client: TestClient) -> None:
    assert client.patch("/api/regole/1", json={}).status_code == 501
    assert client.post("/api/regole/1/approva").status_code == 501


def test_le_rotte_attive_non_sono_coperte(client: TestClient) -> None:
    # Gli stub 501 sono registrati per ultimi: non devono coprire una rotta vera.
    for percorso in (
        "/api/home",
        "/api/task",
        "/api/lista-spesa",
        "/api/spese",
        "/api/diario",
        "/api/abitudini",
        "/api/health",
    ):
        assert client.get(percorso).status_code == 200
    assert client.post("/api/assistente/messaggio", json={"testo": "ciao"}).status_code == 200
