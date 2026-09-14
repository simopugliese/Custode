"""Il job del calendario, dal risveglio del worker fino alle righe in SQLite (§8.10).

Qui non c'è nessun pezzo sostituito nel mezzo: gira `worker_main.giro`, che
chiama il `ClientGoogle` vero, che parla HTTP con un finto Google che è un
server vero, e ciò che si guarda alla fine sono le righe di `calendar_events`.
Il solo finto è Telegram, perché mandare un messaggio non è ciò che questi test
verificano — quando è stato mandato, invece, sì.

Le regole che difendono sono quelle che si scoprirebbero dopo, e male:
- la stessa fascia non risincronizza, ma quella dopo sì;
- un guasto di rete **non** segna la fascia, così si riprova subito;
- un permesso scaduto avvisa **una volta**, e torna ad avvisare solo dopo che
  il calendario è ripartito.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

from custode_bot.risposte import Risposta
from custode_calendario.config import ImpostazioniCalendario
from custode_calendario.evento import Evento
from custode_calendario.google import ClientGoogle
from custode_core.config import Settings
from custode_core.dominio import calendario as dom
from custode_core.registro_job import (
    AVVISO_CALENDARIO_FERMO,
    SENZA_PERIODO,
    SYNC_CALENDARIO,
    gia_eseguito,
)
from custode_worker import main as worker_main
from custode_worker.config import ImpostazioniWorker
from custode_worker.telegram import InvioNonRiuscito
from tests.integration.finto_google import FintoGoogle

pytestmark = pytest.mark.integration

# Lunedì 14 settembre 2026, 10:03: dentro la fascia delle 10:00-10:05.
ADESSO = datetime(2026, 9, 14, 10, 3)
OGGI = ADESSO.date()
FASCIA = datetime(2026, 9, 14, 10, 0)
FASCIA_DOPO = datetime(2026, 9, 14, 10, 5)


class _CalendarioDiTest(ImpostazioniCalendario):
    model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")


class _WorkerDiTest(ImpostazioniWorker):
    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=None, extra="ignore")


class TelegramFinto:
    def __init__(self, errore: Exception | None = None):
        self.errore = errore
        self.mandati: list[Risposta] = []

    def manda(self, risposta: Risposta) -> None:
        if self.errore is not None:
            raise self.errore
        self.mandati.append(risposta)


class RouterFinto:
    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        return {"riepilogo": "Andata così."}


class CalendarioSpento:
    def configurata(self) -> bool:
        return False

    def eventi(self, da: date, a: date) -> list[Evento]:
        raise AssertionError("un calendario spento non va interrogato")


@pytest.fixture
def impostazioni(db_path: Path) -> Settings:
    class _Test(Settings):
        model_config = SettingsConfigDict(env_prefix="CUSTODE_", env_file=None, extra="ignore")

    return _Test(ambiente="test", db_path=db_path, timezone="Europe/Rome")


@pytest.fixture(autouse=True)
def schema(conn: Any) -> None:
    """Lo schema migrato prima di ogni giro, come lo trova il worker sul Pi.

    La fixture `conn` migra il database: qui serve anche ai test che poi non la
    guardano, perché `giro` apre le sue connessioni per conto suo.
    """


@pytest.fixture
def google() -> Iterator[FintoGoogle]:
    finto = FintoGoogle()
    try:
        yield finto
    finally:
        finto.chiudi()


@pytest.fixture
def calendario(google: FintoGoogle) -> _CalendarioDiTest:
    return _CalendarioDiTest(
        client_id="id-finto",
        client_secret="segreto-finto",
        refresh_token="refresh-finto",
        url_token=f"{google.base}/token",
        url_api=f"{google.base}/calendar/v3",
        giorni_indietro=7,
        giorni_avanti=14,
    )


def _voce(
    identificativo: str, titolo: str, giorno: date, ora_inizio: int, ore: int = 2, **extra: Any
) -> dict[str, Any]:
    """Un evento come lo manda Google, con gli orari in ora locale italiana."""
    inizio = datetime.combine(giorno, time(ora_inizio, 0))
    return {
        "id": identificativo,
        "summary": titolo,
        "start": {"dateTime": f"{inizio.isoformat()}+02:00"},
        "end": {"dateTime": f"{(inizio + timedelta(hours=ore)).isoformat()}+02:00"},
        **extra,
    }


def _giro(
    impostazioni: Settings,
    calendario: ImpostazioniCalendario,
    *,
    adesso: datetime = ADESSO,
    telegram: TelegramFinto | None = None,
    sorgente: Any = None,
    monkeypatch: pytest.MonkeyPatch,
) -> TelegramFinto:
    """Un risveglio del worker, col suo orologio fermo su `adesso`."""
    posta = telegram or TelegramFinto()
    monkeypatch.setattr(worker_main, "adesso", lambda _fuso: adesso)
    worker_main.giro(
        impostazioni,
        _WorkerDiTest(backup_cartella=Path("/backup-inesistente")),
        router=RouterFinto(),  # type: ignore[arg-type]
        telegram=posta,  # type: ignore[arg-type]
        calendario=calendario,
        sorgente_calendario=(
            sorgente
            if sorgente is not None
            else ClientGoogle(calendario, timezone=impostazioni.timezone)
        ),
    )
    return posta


# — il percorso vero ————————————————————————————————————


def test_un_giro_porta_gli_eventi_di_google_dentro_il_database(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google.stato.eventi = [
        _voce("g-analisi", "Analisi II", OGGI, 9, location="Aula 3", recurringEventId="serie-an"),
        _voce("g-palestra", "Palestra", OGGI, 18, ore=1),
    ]

    _giro(impostazioni, calendario, monkeypatch=monkeypatch)

    salvati = dom.del_giorno(conn, OGGI)
    assert [(e.titolo, e.inizio.strftime("%H:%M")) for e in salvati] == [
        ("Analisi II", "09:00"),
        ("Palestra", "18:00"),
    ]
    assert salvati[0].luogo == "Aula 3"
    assert salvati[0].serie_id == "serie-an"
    assert salvati[0].sincronizzato_il == ADESSO
    assert gia_eseguito(conn, SYNC_CALENDARIO, FASCIA)


def test_al_worker_viene_chiesta_la_finestra_configurata(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sette giorni indietro e quattordici avanti, non quelli che gli pare."""
    _giro(impostazioni, calendario, monkeypatch=monkeypatch)

    (richiesta,) = google.stato.richieste_eventi
    assert richiesta["timeMin"][0].startswith((OGGI - timedelta(days=7)).isoformat())
    # `timeMax` è l'inizio del giorno dopo l'ultimo: la finestra è inclusiva.
    assert richiesta["timeMax"][0].startswith((OGGI + timedelta(days=15)).isoformat())


def test_un_evento_disdetto_su_google_sparisce_dal_database(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google.stato.eventi = [
        _voce("g-analisi", "Analisi II", OGGI, 9),
        _voce("g-palestra", "Palestra", OGGI, 18),
    ]
    _giro(impostazioni, calendario, monkeypatch=monkeypatch)

    google.stato.eventi = [_voce("g-analisi", "Analisi II", OGGI, 9)]
    _giro(impostazioni, calendario, adesso=ADESSO + timedelta(minutes=15), monkeypatch=monkeypatch)

    assert [e.titolo for e in dom.del_giorno(conn, OGGI)] == ["Analisi II"]


# — quante volte —————————————————————————————————————————


def test_dentro_la_stessa_fascia_google_si_interroga_una_volta_sola(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La fascia è larga quanto il risveglio: in pratica ogni giro ne apre una
    nuova, ma resta un registro esplicito e non «se ne occupa il ciclo» — due
    risvegli ravvicinati nello stesso minuto arrotondato (un riavvio) non
    devono interrogare Google due volte.
    """
    for minuto in (0, 2, 4):
        _giro(
            impostazioni,
            calendario,
            adesso=ADESSO.replace(minute=minuto),
            monkeypatch=monkeypatch,
        )

    assert len(google.stato.richieste_eventi) == 1


def test_la_fascia_dopo_risincronizza(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _giro(impostazioni, calendario, monkeypatch=monkeypatch)
    _giro(impostazioni, calendario, adesso=datetime(2026, 9, 14, 10, 6), monkeypatch=monkeypatch)

    assert len(google.stato.richieste_eventi) == 2
    assert gia_eseguito(conn, SYNC_CALENDARIO, FASCIA_DOPO)


def test_senza_credenziali_non_si_interroga_e_non_si_segna(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un modulo spento non è un guasto: il giorno che autorizzi parte da solo."""
    _giro(impostazioni, calendario, sorgente=CalendarioSpento(), monkeypatch=monkeypatch)

    assert google.stato.richieste_eventi == []
    assert not gia_eseguito(conn, SYNC_CALENDARIO, FASCIA)


# — quando va male ——————————————————————————————————————


def test_un_guasto_di_rete_non_segna_la_fascia(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si riprova al prossimo risveglio, senza aspettare oltre."""
    google.stato.stato_eventi = 503

    posta = _giro(impostazioni, calendario, monkeypatch=monkeypatch)

    assert not gia_eseguito(conn, SYNC_CALENDARIO, FASCIA)
    # Non ti si scrive per un timeout: si riprova e basta.
    assert posta.mandati == []


def test_un_guasto_di_rete_si_ripara_al_risveglio_dopo(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google.stato.stato_eventi = 503
    _giro(impostazioni, calendario, monkeypatch=monkeypatch)

    google.stato.stato_eventi = 200
    google.stato.eventi = [_voce("g-analisi", "Analisi II", OGGI, 9)]
    _giro(impostazioni, calendario, adesso=ADESSO.replace(minute=8), monkeypatch=monkeypatch)

    assert [e.titolo for e in dom.del_giorno(conn, OGGI)] == ["Analisi II"]


def test_un_permesso_scaduto_te_lo_dice_e_segna_la_fascia(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La trappola di §8.10: in «Testing» il permesso muore dopo sette giorni.

    La fascia si segna perché riprovare fra cinque minuti un permesso morto non
    serve a niente: alla fascia dopo si riprova comunque, che è quanto basta ad
    accorgersi che nel frattempo l'hai rifatto.
    """
    google.stato.errore_token = (400, {"error": "invalid_grant"})

    posta = _giro(impostazioni, calendario, monkeypatch=monkeypatch)

    assert len(posta.mandati) == 1
    assert "non si aggiorna più" in posta.mandati[0].testo
    assert "custode-autorizza-calendario" in posta.mandati[0].testo
    assert gia_eseguito(conn, SYNC_CALENDARIO, FASCIA)
    assert gia_eseguito(conn, AVVISO_CALENDARIO_FERMO, SENZA_PERIODO)


def test_il_permesso_scaduto_te_lo_dice_una_volta_sola(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trecento messaggi al giorno renderebbero illeggibile anche il resto."""
    google.stato.errore_token = (400, {"error": "invalid_grant"})
    posta = TelegramFinto()

    for scarto in range(0, 60 * 4, 15):
        _giro(
            impostazioni,
            calendario,
            adesso=ADESSO + timedelta(minutes=scarto),
            telegram=posta,
            monkeypatch=monkeypatch,
        )

    assert len(posta.mandati) == 1


def test_se_l_avviso_non_parte_la_fascia_non_si_segna(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram giù non deve far perdere l'avviso: al giro dopo si riprova."""
    google.stato.errore_token = (400, {"error": "invalid_grant"})

    _giro(
        impostazioni,
        calendario,
        telegram=TelegramFinto(InvioNonRiuscito("Telegram non risponde")),
        monkeypatch=monkeypatch,
    )

    assert not gia_eseguito(conn, SYNC_CALENDARIO, FASCIA)
    assert not gia_eseguito(conn, AVVISO_CALENDARIO_FERMO, SENZA_PERIODO)


def test_dopo_che_e_ripartito_un_guasto_nuovo_torna_ad_avvisare(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un avviso che vale per sempre sarebbe un avviso che non arriva più."""
    posta = TelegramFinto()
    google.stato.errore_token = (400, {"error": "invalid_grant"})
    _giro(impostazioni, calendario, telegram=posta, monkeypatch=monkeypatch)

    # Hai rifatto l'autorizzazione: il sync riesce e l'avviso si dimentica.
    google.stato.errore_token = None
    _giro(
        impostazioni,
        calendario,
        adesso=ADESSO + timedelta(minutes=15),
        telegram=posta,
        monkeypatch=monkeypatch,
    )
    assert not gia_eseguito(conn, AVVISO_CALENDARIO_FERMO, SENZA_PERIODO)

    # Un mese dopo scade di nuovo: te lo deve ridire.
    google.stato.errore_token = (400, {"error": "invalid_grant"})
    _giro(
        impostazioni,
        calendario,
        adesso=ADESSO + timedelta(days=30),
        telegram=posta,
        monkeypatch=monkeypatch,
    )

    assert len(posta.mandati) == 2
