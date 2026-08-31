"""`/api/home`: mostra i moduli attivi e tace su quelli che non esistono."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_home_vuota(client: TestClient) -> None:
    corpo = client.get("/api/home").json()
    assert corpo["dataLabel"] == "lunedì 31 agosto, 08:41"
    assert corpo["titolo"] == "Niente in sospeso."
    assert corpo["stats"] == {"taskAperti": 0, "listaSpesaDaPrendere": 0}


def test_i_moduli_non_attivi_sono_assenti_non_a_zero(client: TestClient) -> None:
    # È la differenza fra "non lo so ancora" e "non hai speso niente".
    corpo = client.get("/api/home").json()
    for campo in ("calendarioOggi", "abitudini", "speseSettimana", "proposteAutomazioni"):
        assert campo not in corpo
    assert "spesaSettimana" not in corpo["stats"]
    assert "streakPiuLunga" not in corpo["stats"]


def test_riepilogo_con_dati_veri(client: TestClient) -> None:
    client.post("/api/task", json={"titolo": "officina", "scadenza": "2026-08-31T18:00"})
    client.post("/api/task", json={"titolo": "bolletta", "scadenza": "2026-08-20"})
    client.post("/api/task", json={"titolo": "paper"})
    client.post("/api/lista-spesa", json={"nome": "latte"})

    corpo = client.get("/api/home").json()
    assert corpo["titolo"] == "1 task in ritardo, 1 per oggi, 1 voce sulla lista."
    assert corpo["stats"] == {"taskAperti": 3, "listaSpesaDaPrendere": 1}
    # Gli scaduti vengono prima: sono la cosa da vedere per prima.
    assert [t["titolo"] for t in corpo["taskOggi"]] == ["bolletta", "officina"]
    assert [v["nome"] for v in corpo["listaSpesa"]] == ["latte"]


def test_la_lista_in_home_e_un_riepilogo(client: TestClient) -> None:
    for n in range(12):
        client.post("/api/lista-spesa", json={"nome": f"voce {n}"})

    corpo = client.get("/api/home").json()
    assert len(corpo["listaSpesa"]) == 8  # il resto si vede nella pagina Lista spesa
    assert corpo["stats"]["listaSpesaDaPrendere"] == 12


def test_le_voci_prese_spariscono_dalla_home(client: TestClient) -> None:
    voce_id = client.post("/api/lista-spesa", json={"nome": "latte"}).json()["id"]
    client.patch(f"/api/lista-spesa/{voce_id}", json={"preso": True})
    assert client.get("/api/home").json()["listaSpesa"] == []
