"""Open-Meteo e le parole del meteo (§8.12): nessuna rete, risposte fisse."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from custode_meteo import MeteoNonRaggiungibile, Previsione
from custode_meteo.openmeteo import ClientOpenMeteo
from custode_meteo.testo import descrizione, frase_ombrello

RISPOSTA = {
    "daily": {
        "time": ["2026-08-31", "2026-09-01"],
        "weather_code": [61, 0],
        "temperature_2m_max": [24.4, 27.0],
        "temperature_2m_min": [16.1, 17.5],
        "precipitation_probability_max": [80, None],
    }
}


def _client(gestore: httpx.MockTransport) -> ClientOpenMeteo:
    return ClientOpenMeteo(httpx.Client(transport=gestore))


def test_una_riga_per_giorno_e_la_richiesta_ha_i_parametri_giusti() -> None:
    viste: list[httpx.Request] = []

    def risponde(richiesta: httpx.Request) -> httpx.Response:
        viste.append(richiesta)
        return httpx.Response(200, json=RISPOSTA)

    previsioni = _client(httpx.MockTransport(risponde)).previsioni(45.07, 7.69, 2, "Europe/Rome")

    assert previsioni == [
        Previsione(date(2026, 8, 31), 61, 16.1, 24.4, 80),
        # Nessuna probabilità non è «0%»: è un'assenza, e resta tale.
        Previsione(date(2026, 9, 1), 0, 17.5, 27.0, None),
    ]
    parametri = viste[0].url.params
    assert parametri["latitude"] == "45.07"
    assert parametri["longitude"] == "7.69"
    assert parametri["forecast_days"] == "2"
    assert parametri["timezone"] == "Europe/Rome"


@pytest.mark.parametrize(
    "risposta",
    [
        httpx.Response(500),
        httpx.Response(200, json={"error": True}),
        httpx.Response(200, text="non è json"),
    ],
)
def test_un_servizio_che_non_da_una_previsione_e_un_errore_non_un_meteo_finto(
    risposta: httpx.Response,
) -> None:
    client = _client(httpx.MockTransport(lambda _: risposta))
    with pytest.raises(MeteoNonRaggiungibile):
        client.previsioni(45.0, 7.0, 3, "Europe/Rome")


def test_rete_giu_e_un_errore_non_un_meteo_finto() -> None:
    def giu(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("giù")

    with pytest.raises(MeteoNonRaggiungibile):
        _client(httpx.MockTransport(giu)).previsioni(45.0, 7.0, 3, "Europe/Rome")


@pytest.mark.parametrize(
    ("codice", "parola"),
    [
        (0, "sereno"),
        (2, "poco nuvoloso"),
        (3, "coperto"),
        (63, "pioggia"),
        (81, "pioggia"),
        (73, "neve"),
        (95, "temporale"),
        (45, "nebbia"),
        (53, "pioviggine"),
        (10, "variabile"),
    ],
)
def test_i_codici_in_parole(codice: int, parola: str) -> None:
    assert descrizione(codice) == parola


def test_l_ombrello_si_dice_solo_sopra_la_soglia() -> None:
    assert frase_ombrello(None, ("09:00", "Analisi")) is None
    assert frase_ombrello(49, ("09:00", "Analisi")) is None
    assert frase_ombrello(50, None) == "Pioggia probabile (50%): porta l'ombrello."
    assert (
        frase_ombrello(80, ("09:00", "Analisi"))
        == "Pioggia probabile (80%) e hai «Analisi» alle 09:00: porta l'ombrello."
    )
