"""`/api/lista-spesa` contro il DB reale (§8.3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_lista_vuota(client: TestClient) -> None:
    corpo = client.get("/api/lista-spesa").json()
    assert corpo["titolo"] == "Lista della spesa vuota."
    assert corpo["reparti"] == []
    assert corpo["stats"] == {"daPrendere": 0, "presi": 0}
    # Stima carrello e ultima spesa dipendono dal modulo spese: assenti, non a zero.
    assert "stimaCarrello" not in corpo["stats"]
    assert "ultimaSpesaGiorni" not in corpo["stats"]


def test_aggiungi_e_raggruppa_per_reparto(client: TestClient) -> None:
    creata = client.post(
        "/api/lista-spesa", json={"nome": "latte", "quantita": "1 L", "reparto": "Latticini"}
    )
    assert creata.status_code == 201
    client.post("/api/lista-spesa", json={"nome": "yogurt", "reparto": "Latticini"})
    client.post("/api/lista-spesa", json={"nome": "mele", "reparto": "Frutta e verdura"})
    client.post("/api/lista-spesa", json={"nome": "carta forno"})

    corpo = client.get("/api/lista-spesa?ordina=reparto").json()
    assert corpo["titolo"] == "4 voci da prendere in 3 reparti."
    assert [r["nome"] for r in corpo["reparti"]] == ["Frutta e verdura", "Latticini", "Altro"]
    assert [v["nome"] for v in corpo["reparti"][1]["voci"]] == ["latte", "yogurt"]


def test_ordine_di_aggiunta_e_una_sezione_sola(client: TestClient) -> None:
    for nome in ("latte", "mele", "carta forno"):
        client.post("/api/lista-spesa", json={"nome": nome})

    corpo = client.get("/api/lista-spesa?ordina=aggiunta").json()
    assert [r["nome"] for r in corpo["reparti"]] == ["Da prendere"]
    assert [v["nome"] for v in corpo["reparti"][0]["voci"]] == ["latte", "mele", "carta forno"]


def test_aggiungere_due_volte_non_duplica(client: TestClient) -> None:
    prima = client.post("/api/lista-spesa", json={"nome": "latte"}).json()
    seconda = client.post("/api/lista-spesa", json={"nome": "Latte"}).json()
    assert seconda["id"] == prima["id"]
    assert client.get("/api/lista-spesa").json()["stats"]["daPrendere"] == 1


def test_spunta_una_voce(client: TestClient) -> None:
    voce_id = client.post("/api/lista-spesa", json={"nome": "mele"}).json()["id"]

    assert client.patch(f"/api/lista-spesa/{voce_id}", json={"preso": True}).json()["preso"] is True

    corpo = client.get("/api/lista-spesa").json()
    assert corpo["stats"] == {"daPrendere": 0, "presi": 1}
    assert [v["nome"] for v in corpo["presi"]] == ["mele"]


def test_svuota_presi(client: TestClient) -> None:
    presa = client.post("/api/lista-spesa", json={"nome": "carta forno"}).json()["id"]
    client.post("/api/lista-spesa", json={"nome": "mele"})
    client.patch(f"/api/lista-spesa/{presa}", json={"preso": True})

    assert client.post("/api/lista-spesa/svuota-presi").status_code == 204

    corpo = client.get("/api/lista-spesa").json()
    assert corpo["presi"] == []
    assert corpo["stats"] == {"daPrendere": 1, "presi": 0}


def test_voce_inesistente_e_nome_vuoto(client: TestClient) -> None:
    assert client.patch("/api/lista-spesa/999", json={"preso": True}).status_code == 404
    assert client.post("/api/lista-spesa", json={"nome": "  "}).status_code == 422
