"""La barra «A Custode» della dashboard, sullo stesso canale del bot (§8.1)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from custode_router.errori import ProviderNonRaggiungibile
from tests.integration.conftest import RouterFinto

pytestmark = pytest.mark.integration


def test_un_messaggio_esegue_e_racconta(client: TestClient, modello: RouterFinto) -> None:
    modello.risposta = {"azione": "aggiungi_voce_spesa", "titolo": "latte"}

    risposta = client.post("/api/assistente/messaggio", json={"testo": "sto finendo il latte"})

    assert risposta.status_code == 200
    assert risposta.json()["rispostaLabel"] == "Aggiunto alla lista: latte"
    # E si vede subito nella pagina che la dashboard ricarica dopo l'invio.
    lista = client.get("/api/lista-spesa").json()
    assert [v["nome"] for r in lista["reparti"] for v in r["voci"]] == ["latte"]


def test_lo_stesso_interprete_del_bot(client: TestClient, modello: RouterFinto) -> None:
    """Il contesto passato al modello è quello reale, non uno finto."""
    client.post("/api/task", json={"titolo": "Pagare la bolletta"})
    client.post("/api/assistente/messaggio", json={"testo": "fatto la bolletta"})
    assert "Pagare la bolletta" in modello.messaggi_visti[0]


def test_un_task_creato_dalla_dashboard(client: TestClient, modello: RouterFinto) -> None:
    modello.risposta = {
        "azione": "aggiungi_task",
        "titolo": "Chiamare l'officina",
        "scadenza": "2026-09-03",
    }
    risposta = client.post(
        "/api/assistente/messaggio", json={"testo": "ricordami di chiamare l'officina giovedì"}
    )
    assert "Chiamare l'officina" in risposta.json()["rispostaLabel"]

    sezioni = {
        s["titolo"]: [t["titolo"] for t in s["task"]]
        for s in client.get("/api/task").json()["sezioni"]
    }
    assert sezioni["Prossimi sette giorni"] == ["Chiamare l'officina"]


def test_quando_il_modello_non_risponde(client: TestClient, modello: RouterFinto) -> None:
    modello.errore = ProviderNonRaggiungibile("timeout")
    risposta = client.post("/api/assistente/messaggio", json={"testo": "aggiungi il latte"})
    # 200 con una frase leggibile: la barra non deve mostrare un errore HTTP
    # per una cosa che l'utente può semplicemente riprovare.
    assert risposta.status_code == 200
    assert "Riprova" in risposta.json()["rispostaLabel"]


def test_messaggio_vuoto(client: TestClient) -> None:
    risposta = client.post("/api/assistente/messaggio", json={"testo": "   "})
    assert risposta.status_code == 200
    assert risposta.json()["rispostaLabel"]


def test_una_spesa_detta_per_ieri_finisce_a_ieri(
    client: TestClient, modello: RouterFinto, ora: datetime
) -> None:
    """Il giro completo del bug osservato sul Pi, dalla frase alla pagina Spese."""
    ieri = ora.date() - timedelta(days=1)
    modello.risposta = {
        "azione": "registra_spesa",
        "titolo": "spesa xyz",
        "importo": 17,
        "data": ieri.isoformat(),
    }

    risposta = client.post(
        "/api/assistente/messaggio", json={"testo": "ieri ho pagato 17 euro la spesa xyz"}
    )
    assert "di ieri" in risposta.json()["rispostaLabel"]

    # E la pagina la data la mostra dov'è davvero, non dove è stata registrata.
    (movimento,) = client.get("/api/spese?periodo=mese").json()["movimenti"]
    assert movimento["dataLabel"] == "ieri"
