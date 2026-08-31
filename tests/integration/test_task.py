"""`/api/task` contro il DB reale: è ciò che la dashboard chiama davvero."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _sezioni(corpo: dict[str, Any]) -> dict[str, list[str]]:
    return {s["titolo"]: [t["titolo"] for t in s["task"]] for s in corpo["sezioni"]}


def test_pagina_vuota(client: TestClient) -> None:
    corpo = client.get("/api/task").json()
    assert corpo["titolo"] == "Nessun task aperto."
    assert corpo["stats"] == {"aperti": 0, "oggi": 0, "inRitardo": 0, "chiusiSettimana": 0}
    assert corpo["chiusiPerGiorno"] == [0] * 7
    # "Oggi" resta, con la sua nota: la colonna non deve essere muta.
    assert _sezioni(corpo) == {"Oggi": []}
    assert corpo["sezioni"][0]["notaVuoto"] == "Niente per oggi."


def test_crea_task_e_lo_ritrova_nella_sezione_giusta(client: TestClient) -> None:
    creato = client.post(
        "/api/task", json={"titolo": "Chiamare l'officina", "scadenza": "2026-08-31T18:00"}
    )
    assert creato.status_code == 201
    assert creato.json()["scadenzaLabel"] == "18:00"

    client.post("/api/task", json={"titolo": "Pagare la bolletta", "scadenza": "2026-08-28"})
    client.post("/api/task", json={"titolo": "Preparare slide", "scadenza": "2026-09-03"})
    client.post("/api/task", json={"titolo": "Leggere il paper"})

    sezioni = _sezioni(client.get("/api/task").json())
    assert sezioni == {
        "In ritardo": ["Pagare la bolletta"],
        "Oggi": ["Chiamare l'officina"],
        "Prossimi sette giorni": ["Preparare slide"],
        "Senza scadenza": ["Leggere il paper"],
    }


def test_stats_e_provenienza(client: TestClient) -> None:
    client.post("/api/task", json={"titolo": "oggi", "scadenza": "2026-08-31"})
    client.post("/api/task", json={"titolo": "scaduto", "scadenza": "2026-08-20"})
    corpo = client.get("/api/task").json()
    assert corpo["stats"] == {"aperti": 2, "oggi": 1, "inRitardo": 1, "chiusiSettimana": 0}
    assert corpo["titolo"] == "2 task aperti, 1 in ritardo, 1 per oggi."
    assert corpo["provenienza"] == [{"origine": "Dashboard", "conteggio": 2}]


def test_segnare_fatto_aggiorna_pagina_e_grafico(client: TestClient) -> None:
    task_id = client.post("/api/task", json={"titolo": "paper"}).json()["id"]

    assert client.patch(f"/api/task/{task_id}", json={"fatto": True}).json()["fatto"] is True

    corpo = client.get("/api/task").json()
    assert corpo["stats"]["aperti"] == 0
    assert corpo["stats"]["chiusiSettimana"] == 1
    # 31 agosto 2026 è lunedì: il conteggio va nella prima colonna.
    assert corpo["chiusiPerGiorno"] == [1, 0, 0, 0, 0, 0, 0]


def test_rinvio_mostrato_come_tag(client: TestClient) -> None:
    task_id = client.post(
        "/api/task", json={"titolo": "bolletta", "scadenza": "2026-08-31"}
    ).json()["id"]

    dopo = client.patch(f"/api/task/{task_id}", json={"rinviaGiorni": 1}).json()
    assert dopo["scadenzaLabel"] == "domani"
    assert dopo["tag"] == "rinviato 1×"
    assert dopo["rinvii"] == 1


def test_avviso_sui_task_rinviati_troppe_volte(client: TestClient) -> None:
    task_id = client.post("/api/task", json={"titolo": "dentista"}).json()["id"]
    for _ in range(3):
        client.patch(f"/api/task/{task_id}", json={"rinviaGiorni": 1})

    assert client.get("/api/task").json()["avviso"] == "«dentista» è stato rinviato 3 volte."


def test_vista_completati(client: TestClient) -> None:
    task_id = client.post("/api/task", json={"titolo": "paper"}).json()["id"]
    client.patch(f"/api/task/{task_id}", json={"fatto": True})

    assert _sezioni(client.get("/api/task?vista=completati").json()) == {"Chiusi oggi": ["paper"]}


def test_vista_completati_senza_niente_chiuso(client: TestClient) -> None:
    corpo = client.get("/api/task?vista=completati").json()
    assert corpo["sezioni"][0]["notaVuoto"] == "Nessun task ancora chiuso."


def test_vista_per_progetto_raggruppa_per_provenienza(client: TestClient) -> None:
    client.post("/api/task", json={"titolo": "dalla dashboard"})
    corpo = client.get("/api/task?vista=progetto").json()
    assert _sezioni(corpo) == {"Dashboard": ["dalla dashboard"]}


def test_vista_non_ammessa(client: TestClient) -> None:
    assert client.get("/api/task?vista=inventata").status_code == 422


def test_task_inesistente(client: TestClient) -> None:
    risposta = client.patch("/api/task/999", json={"fatto": True})
    assert risposta.status_code == 404
    assert risposta.json()["detail"] == "Task non trovato."


def test_corpi_non_validi(client: TestClient) -> None:
    task_id = client.post("/api/task", json={"titolo": "x"}).json()["id"]
    assert client.patch(f"/api/task/{task_id}", json={}).status_code == 422
    assert client.patch(f"/api/task/{task_id}", json={"rinviaGiorni": 0}).status_code == 422
    assert client.post("/api/task", json={"titolo": "   "}).status_code == 422
    assert client.post("/api/task", json={"titolo": "x", "scadenza": "domani"}).status_code == 422
