"""`/meteo` (§8.12): stesso dato della Home, in righe di Telegram."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from custode_bot import risposte
from custode_core.dominio import posizione
from custode_meteo import MeteoNonRaggiungibile, Previsione

OGGI = date(2026, 8, 31)


class SorgenteFinta:
    def __init__(self, previsioni: list[Previsione] | None = None) -> None:
        self.previsioni_date = previsioni or []
        self.errore: Exception | None = None
        self.chiamate: list[tuple[float, float]] = []

    def previsioni(self, lat: float, lon: float, giorni: int, fuso: str) -> list[Previsione]:
        self.chiamate.append((lat, lon))
        if self.errore is not None:
            raise self.errore
        return self.previsioni_date


def _meteo(
    conn: sqlite3.Connection,
    ora: datetime,
    sorgente: SorgenteFinta,
    casa: tuple[float, float] | None = None,
) -> risposte.Risposta:
    return risposte.meteo(conn, ora, sorgente, casa=casa, giorni=3, fuso="Europe/Rome")


def test_senza_sapere_dove_sei_lo_dice_e_non_chiama_nessuno(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    sorgente = SorgenteFinta()

    risposta = _meteo(conn, ora, sorgente)

    assert risposta.testo == risposte.NON_SO_DOVE_SEI
    assert sorgente.chiamate == []


def test_tre_giorni_con_emoji_e_oggi_in_grassetto(conn: sqlite3.Connection, ora: datetime) -> None:
    posizione.salva(conn, 45.07, 7.69, ora)
    sorgente = SorgenteFinta(
        [
            Previsione(OGGI, 45, 6.8, 16.7, 0),
            Previsione(OGGI + timedelta(days=1), 3, 8.0, 18.2, None),
            Previsione(OGGI + timedelta(days=2), 0, 9.0, 19.0, 5),
        ]
    )

    risposta = _meteo(conn, ora, sorgente)

    assert risposta.testo == (
        "<b>Meteo</b>\n"
        "🌫️ <b>Oggi</b> nebbia, 7–17° · 💧 0%\n"
        # Senza probabilità non si scrive «0%»: è un'assenza, non una promessa.
        "☁️ domani coperto, 8–18°\n"
        "☀️ mercoledì sereno, 9–19° · 💧 5%"
    )
    assert sorgente.chiamate == [(45.07, 7.69)]


def test_la_casa_del_env_vale_solo_senza_posizione_e_lo_dice(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    sorgente = SorgenteFinta([Previsione(OGGI, 0, 10.0, 20.0, 0)])

    risposta = _meteo(conn, ora, sorgente, casa=(44.5, 8.9))

    assert risposta.testo.startswith("<b>Meteo</b> · casa\n")
    assert sorgente.chiamate == [(44.5, 8.9)]


def test_una_posizione_vecchia_si_usa_ma_lo_dice(conn: sqlite3.Connection, ora: datetime) -> None:
    posizione.salva(conn, 45.0, 7.0, ora - timedelta(days=3))
    sorgente = SorgenteFinta([Previsione(OGGI, 0, 10.0, 20.0, 0)])

    risposta = _meteo(conn, ora, sorgente)

    assert risposta.testo.startswith("<b>Meteo</b> · ultima posizione: 3 giorni fa\n")


def test_la_pioggia_aggiunge_l_ombrello(conn: sqlite3.Connection, ora: datetime) -> None:
    posizione.salva(conn, 45.0, 7.0, ora)
    sorgente = SorgenteFinta([Previsione(OGGI, 61, 16.0, 24.0, 80)])

    risposta = _meteo(conn, ora, sorgente)

    assert risposta.testo.endswith("\n\n<i>Pioggia probabile (80%): porta l'ombrello.</i>")


def test_servizio_giu_non_inventa_un_meteo(conn: sqlite3.Connection, ora: datetime) -> None:
    posizione.salva(conn, 45.0, 7.0, ora)
    sorgente = SorgenteFinta()
    sorgente.errore = MeteoNonRaggiungibile("giù")

    risposta = _meteo(conn, ora, sorgente)

    assert risposta.testo == "Il servizio meteo non risponde: riprova fra poco."


def test_il_meteo_e_nell_aiuto() -> None:
    assert "/meteo" in risposte.aiuto().testo
