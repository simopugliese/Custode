"""`/api/posizione` e `/api/meteo` (§8.12): la previsione senza archivio."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from custode_api.dipendenze import prendi_ora
from custode_api.main import crea_app
from custode_calendario.evento import Evento
from custode_core.config import Settings
from custode_core.db import connessione
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import posizione
from custode_meteo import MeteoNonRaggiungibile, Previsione
from custode_meteo.config import ImpostazioniMeteo
from tests.integration.conftest import SorgenteMeteoFinta

pytestmark = pytest.mark.integration

OGGI = date(2026, 8, 31)
PIOGGIA = Previsione(OGGI, 61, 16.4, 23.6, 80)
SERENO = Previsione(OGGI + timedelta(days=1), 0, 17.0, 27.2, 5)


def test_senza_sapere_dove_sei_la_pagina_lo_dice_e_non_chiama_nessuno(
    client: TestClient, sorgente_meteo: SorgenteMeteoFinta
) -> None:
    corpo = client.get("/api/meteo").json()

    # Niente `previsioni`: una lista vuota direbbe «non piove», che è un dato.
    assert "previsioni" not in corpo
    assert "dove sei" in corpo["notaLabel"]
    assert sorgente_meteo.chiamate == []


def test_la_posizione_arrivata_dal_browser_decide_dove_si_chiede_il_meteo(
    client: TestClient, sorgente_meteo: SorgenteMeteoFinta
) -> None:
    sorgente_meteo.previsioni_date = [PIOGGIA, SERENO]

    assert client.put("/api/posizione", json={"lat": 45.070312, "lon": 7.686864}).status_code == 204
    corpo = client.get("/api/meteo").json()

    # Arrotondata a due decimali prima di uscire, e ora e fuso sono quelli dell'app.
    assert sorgente_meteo.chiamate[0][:2] == (45.07, 7.69)
    assert sorgente_meteo.chiamate[0][3] == "Europe/Rome"
    assert corpo["previsioni"] == [
        {
            "giornoLabel": "oggi",
            "descrizione": "pioggia",
            "minima": 16,
            "massima": 24,
            "probPioggia": 80,
        },
        {
            "giornoLabel": "domani",
            "descrizione": "sereno",
            "minima": 17,
            "massima": 27,
            "probPioggia": 5,
        },
    ]
    # Posizione di questa mattina: è dove sei, non serve dirlo.
    assert "posizioneLabel" not in corpo


def test_una_posizione_di_tre_giorni_fa_si_usa_ma_lo_dice(
    client: TestClient, db_path: Path, ora: datetime, sorgente_meteo: SorgenteMeteoFinta
) -> None:
    sorgente_meteo.previsioni_date = [PIOGGIA]
    with connessione(db_path) as conn:
        posizione.salva(conn, 45.0, 7.0, ora - timedelta(days=3))

    corpo = client.get("/api/meteo").json()

    assert corpo["posizioneLabel"] == "ultima posizione: 3 giorni fa"
    assert sorgente_meteo.chiamate[0][:2] == (45.0, 7.0)


def test_coordinate_impossibili_si_rifiutano(client: TestClient) -> None:
    assert client.put("/api/posizione", json={"lat": 91, "lon": 0}).status_code == 422
    assert client.put("/api/posizione", json={"lat": 0}).status_code == 422


def test_dimmi_il_servizio_e_giu_non_inventa_un_meteo(
    client: TestClient, sorgente_meteo: SorgenteMeteoFinta
) -> None:
    client.put("/api/posizione", json={"lat": 45.0, "lon": 7.0})
    sorgente_meteo.errore = MeteoNonRaggiungibile("giù")

    risposta = client.get("/api/meteo")

    assert risposta.status_code == 502
    assert "meteo" in risposta.json()["detail"]


def test_il_consiglio_dell_ombrello_cita_il_prossimo_impegno_con_un_orario(
    client: TestClient, db_path: Path, sorgente_meteo: SorgenteMeteoFinta
) -> None:
    sorgente_meteo.previsioni_date = [PIOGGIA]
    client.put("/api/posizione", json={"lat": 45.0, "lon": 7.0})
    with connessione(db_path) as conn:
        dom_calendario.sincronizza(
            conn,
            [
                Evento("a", "Analisi 1", datetime(2026, 8, 31, 9, 0), datetime(2026, 8, 31, 11, 0)),
                Evento(
                    "b", "Ferie", datetime(2026, 8, 31), datetime(2026, 9, 1), tutto_il_giorno=True
                ),
            ],
            da=OGGI - timedelta(days=7),
            a=OGGI + timedelta(days=14),
            ora=datetime(2026, 8, 31, 8, 0),
        )

    corpo = client.get("/api/meteo").json()

    assert corpo["consiglioLabel"] == (
        "Pioggia probabile (80%) e hai «Analisi 1» alle 09:00: porta l'ombrello."
    )


def test_con_il_sereno_nessun_consiglio(
    client: TestClient, sorgente_meteo: SorgenteMeteoFinta
) -> None:
    sorgente_meteo.previsioni_date = [Previsione(OGGI, 0, 17.0, 27.0, 5)]
    client.put("/api/posizione", json={"lat": 45.0, "lon": 7.0})

    assert "consiglioLabel" not in client.get("/api/meteo").json()


@pytest.fixture
def con_casa(
    fai_settings: object, db_path: Path, ora: datetime, sorgente_meteo: SorgenteMeteoFinta
) -> Iterator[TestClient]:
    class _Casa(ImpostazioniMeteo):
        model_config = ImpostazioniMeteo.model_config | {"env_file": None}

    app = crea_app(
        fai_settings(ambiente="test", db_path=db_path),  # type: ignore[operator]
        meteo=_Casa(casa_lat=44.5, casa_lon=8.9),
        sorgente_meteo=sorgente_meteo,
    )
    app.dependency_overrides[prendi_ora] = lambda: ora
    with TestClient(app) as attivo:
        yield attivo


def test_prima_di_ogni_posizione_vale_la_casa_del_env_e_lo_dice(
    con_casa: TestClient, sorgente_meteo: SorgenteMeteoFinta
) -> None:
    sorgente_meteo.previsioni_date = [PIOGGIA]

    corpo = con_casa.get("/api/meteo").json()

    assert corpo["posizioneLabel"] == "casa"
    assert sorgente_meteo.chiamate[0][:2] == (44.5, 8.9)


_ = Settings  # il tipo della fixture `fai_settings`, per chi legge
