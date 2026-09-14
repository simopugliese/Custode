"""Il tag degli eventi, dal risveglio del worker fino alle righe in SQLite (§8.10).

Stessa impalcatura del sync (`test_worker_calendario.py`): gira
`worker_main.giro`, che parla HTTP con un finto Google che è un server vero, e
ciò che si guarda alla fine sono le righe di `calendar_events`. L'unico pezzo
sostituito è il modello, che qui non è un dizionario fisso: legge l'elenco
numerato che riceve davvero e risponde su quello, così il giro di andata e
ritorno — prompt numerato, risposta riletta per numero — viene esercitato per
intero invece che dato per buono.

Le regole che questi test difendono sono quelle che costerebbero care:
- una serie si tagga **una volta**, non un'occorrenza alla volta;
- il modello non viene richiamato per qualcosa che ha già guardato — è la
  differenza fra una chiamata al giorno e 288;
- la coda si svuota **sempre**, anche quando il modello risponde male, perché
  una coda che non si svuota è una chiamata ogni cinque minuti per sempre;
- ma una risposta di cui non si capisce niente non è una classificazione: lì la
  coda resta intatta e si riprova.
"""

from __future__ import annotations

import sqlite3
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
from custode_router import calendario as router_calendario
from custode_router.compiti import Compito
from custode_router.errori import ProviderNonRaggiungibile
from custode_worker import main as worker_main
from custode_worker.config import ImpostazioniWorker
from tests.integration.finto_google import FintoGoogle

pytestmark = pytest.mark.integration

# Lunedì 14 settembre 2026, 10:03: dentro la fascia delle 10:00-10:05.
ADESSO = datetime(2026, 9, 14, 10, 3)
OGGI = ADESSO.date()


class _CalendarioDiTest(ImpostazioniCalendario):
    model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")


class _WorkerDiTest(ImpostazioniWorker):
    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=None, extra="ignore")


class TelegramFinto:
    def __init__(self) -> None:
        self.mandati: list[Risposta] = []

    def manda(self, risposta: Risposta) -> None:
        self.mandati.append(risposta)


class CalendarioSpento:
    def configurata(self) -> bool:
        return False

    def eventi(self, da: date, a: date) -> list[Evento]:
        raise AssertionError("un calendario spento non va interrogato")


class ModelloFinto:
    """Il modello del tagging: legge l'elenco numerato e risponde su quello.

    Non risponde un dizionario fisso apposta: così un prompt che smettesse di
    numerare gli eventi, o una risposta riletta per posizione, farebbero
    fallire i test invece di passare inosservati.
    """

    def __init__(
        self,
        tipi: dict[str, str] | None = None,
        *,
        risposta_fissa: dict[str, Any] | None = None,
        errore: Exception | None = None,
        configurato: bool = True,
    ) -> None:
        self.tipi = tipi or {}
        self.risposta_fissa = risposta_fissa
        self.errore = errore
        self.configurato = configurato
        self.chiamate: list[str] = []
        """Il prompt di ogni chiamata al tagging: quante sono e cosa c'era dentro."""

    def configurato_per(self, compito: Compito) -> bool:
        return self.configurato

    def titoli_visti(self, chiamata: int = 0) -> list[str]:
        """I titoli dell'elenco numerato, nell'ordine in cui li ha ricevuti."""
        righe = self.chiamate[chiamata].splitlines()[1:]
        return [riga.split(". ", 1)[1] for riga in righe]

    def chiedi_json(self, compito: Compito, **kwargs: Any) -> dict[str, Any]:
        if compito is not Compito.TAG_CALENDARIO:
            # Il riepilogo settimanale e il resoconto delle abitudini passano
            # dallo stesso router: non sono il soggetto di questi test.
            return {"riepilogo": "Andata così."}

        self.chiamate.append(kwargs["utente"])
        if self.errore is not None:
            raise self.errore
        if self.risposta_fissa is not None:
            return self.risposta_fissa
        return {
            "tag": [
                {"n": n, "tipo": self.tipi.get(titolo, "altro")}
                for n, titolo in enumerate(self.titoli_visti(-1), start=1)
            ]
        }


@pytest.fixture
def impostazioni(db_path: Path) -> Settings:
    class _Test(Settings):
        model_config = SettingsConfigDict(env_prefix="CUSTODE_", env_file=None, extra="ignore")

    return _Test(ambiente="test", db_path=db_path, timezone="Europe/Rome")


@pytest.fixture(autouse=True)
def schema(conn: sqlite3.Connection) -> None:
    """Lo schema migrato prima di ogni giro, come lo trova il worker sul Pi."""


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
    identificativo: str, titolo: str, giorno: date, ora_inizio: int = 9, **extra: Any
) -> dict[str, Any]:
    inizio = datetime.combine(giorno, time(ora_inizio, 0))
    return {
        "id": identificativo,
        "summary": titolo,
        "start": {"dateTime": f"{inizio.isoformat()}+02:00"},
        "end": {"dateTime": f"{(inizio + timedelta(hours=2)).isoformat()}+02:00"},
        **extra,
    }


def _serie(
    identificativo: str, titolo: str, serie: str, giorni: list[date]
) -> list[dict[str, Any]]:
    """Le occorrenze di una ricorrenza, come le manda Google già espanse."""
    return [
        _voce(f"{identificativo}-{n}", titolo, giorno, recurringEventId=serie)
        for n, giorno in enumerate(giorni)
    ]


def _giro(
    impostazioni: Settings,
    calendario: ImpostazioniCalendario,
    modello: ModelloFinto,
    *,
    adesso: datetime = ADESSO,
    sorgente: Any = None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un risveglio del worker, col suo orologio fermo su `adesso`."""
    monkeypatch.setattr(worker_main, "adesso", lambda _fuso: adesso)
    worker_main.giro(
        impostazioni,
        _WorkerDiTest(backup_cartella=Path("/backup-inesistente")),
        router=modello,  # type: ignore[arg-type]
        telegram=TelegramFinto(),  # type: ignore[arg-type]
        calendario=calendario,
        sorgente_calendario=(
            sorgente
            if sorgente is not None
            else ClientGoogle(calendario, timezone=impostazioni.timezone)
        ),
    )


def _eventi(conn: sqlite3.Connection) -> list[dom.Evento]:
    return dom.fra(conn, OGGI - timedelta(days=7), OGGI + timedelta(days=14))


def _tipi(conn: sqlite3.Connection) -> dict[str, dom.Tipo]:
    """Il tipo per titolo, che è il verso in cui si leggono questi test."""
    return {evento.titolo: evento.tipo for evento in _eventi(conn)}


# — il percorso vero ————————————————————————————————————


def test_gli_eventi_nuovi_ricevono_il_tipo_proposto_dal_modello(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google.stato.eventi = [
        *_serie("g-analisi", "Analisi II", "serie-an", [OGGI, OGGI + timedelta(days=7)]),
        _voce("g-pale", "Palestra", OGGI, 18, recurringEventId="serie-pa"),
        _voce("g-dentista", "Dentista", OGGI + timedelta(days=2), 15),
    ]
    modello = ModelloFinto({"Analisi II": "lezione", "Palestra": "palestra"})

    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)

    assert _tipi(conn) == {
        "Analisi II": dom.Tipo.LEZIONE,
        "Palestra": dom.Tipo.PALESTRA,
        # Il dentista non è nessuno dei tre, e «altro» è un esito legittimo.
        "Dentista": dom.Tipo.ALTRO,
    }


def test_il_tag_e_una_proposta_non_una_tua_conferma(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La pagina Calendario deve poter distinguere le due cose (§8.10)."""
    google.stato.eventi = [_voce("g-analisi", "Analisi II", OGGI)]

    _giro(
        impostazioni, calendario, ModelloFinto({"Analisi II": "lezione"}), monkeypatch=monkeypatch
    )

    (evento,) = _eventi(conn)
    assert evento.tag_proposto_il == ADESSO
    assert evento.tag_confermato_da_te is False


def test_una_serie_si_chiede_una_volta_e_si_scrive_tutta(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.10: il tipo si decide per la serie, non per il martedì.

    Tre occorrenze, un titolo solo nel prompt, e il tag su tutte e tre.
    """
    google.stato.eventi = _serie(
        "g-analisi",
        "Analisi II",
        "serie-an",
        [OGGI, OGGI + timedelta(days=7), OGGI + timedelta(days=14)],
    )
    modello = ModelloFinto({"Analisi II": "lezione"})

    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)

    assert modello.titoli_visti() == ["Analisi II"]
    salvati = _eventi(conn)
    assert len(salvati) == 3
    assert {e.tipo for e in salvati} == {dom.Tipo.LEZIONE}


# — quante volte si chiama il modello ————————————————————


def test_quello_che_ha_gia_guardato_non_si_richiede(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il sync gira ogni cinque minuti: senza questo sarebbero 288 chiamate al giorno."""
    google.stato.eventi = [_voce("g-analisi", "Analisi II", OGGI)]
    modello = ModelloFinto({"Analisi II": "lezione"})

    for scarto in (0, 5, 10, 15):
        _giro(
            impostazioni,
            calendario,
            modello,
            adesso=ADESSO + timedelta(minutes=scarto),
            monkeypatch=monkeypatch,
        )

    assert len(modello.chiamate) == 1


def test_un_occorrenza_nuova_di_una_serie_gia_taggata_non_torna_in_coda(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il duplicato di §8.10: la lezione di martedì non si ritagga ogni settimana.

    Il sync eredita il tag dalla serie; se non lo facesse, la settimana dopo
    l'occorrenza nuova rientrerebbe in coda e il modello la riguarderebbe.
    """
    google.stato.eventi = _serie("g-analisi", "Analisi II", "serie-an", [OGGI])
    modello = ModelloFinto({"Analisi II": "lezione"})
    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)

    google.stato.eventi = _serie(
        "g-analisi", "Analisi II", "serie-an", [OGGI, OGGI + timedelta(days=7)]
    )
    _giro(
        impostazioni,
        calendario,
        modello,
        adesso=ADESSO + timedelta(minutes=5),
        monkeypatch=monkeypatch,
    )

    assert len(modello.chiamate) == 1
    assert [e.tipo for e in _eventi(conn)] == [dom.Tipo.LEZIONE, dom.Tipo.LEZIONE]


def test_un_evento_davvero_nuovo_viene_taggato_al_giro_dopo(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google.stato.eventi = [_voce("g-analisi", "Analisi II", OGGI)]
    modello = ModelloFinto({"Analisi II": "lezione", "Volo per Catania": "viaggio"})
    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)

    google.stato.eventi = [
        _voce("g-analisi", "Analisi II", OGGI),
        _voce("g-volo", "Volo per Catania", OGGI + timedelta(days=3), 7),
    ]
    _giro(
        impostazioni,
        calendario,
        modello,
        adesso=ADESSO + timedelta(minutes=5),
        monkeypatch=monkeypatch,
    )

    assert modello.titoli_visti(1) == ["Volo per Catania"]
    assert _tipi(conn)["Volo per Catania"] is dom.Tipo.VIAGGIO


def test_la_coda_si_svuota_in_piu_giri_quando_e_piu_lunga_del_tetto(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il tetto sta nella risposta di DeepSeek: oltre, arriverebbe troncata.

    Quello che avanza non si perde: rientra nella chiamata del sync dopo.
    """
    tetto = router_calendario.MAX_TITOLI_PER_CHIAMATA
    google.stato.eventi = [
        _voce(f"g-{n}", f"Impegno {n}", OGGI + timedelta(days=n % 14)) for n in range(tetto + 5)
    ]
    modello = ModelloFinto({f"Impegno {n}": "lezione" for n in range(tetto + 5)})

    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)
    taggati = [e for e in _eventi(conn) if e.tag_proposto_il is not None]
    assert len(taggati) == tetto

    _giro(
        impostazioni,
        calendario,
        modello,
        adesso=ADESSO + timedelta(minutes=5),
        monkeypatch=monkeypatch,
    )
    assert len(modello.chiamate[1].splitlines()) == 1 + 5
    assert all(e.tag_proposto_il is not None for e in _eventi(conn))


# — quando il modello risponde male ——————————————————————


def test_un_tipo_inventato_esce_comunque_dalla_coda(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una serie che resta in coda ci resta per sempre, a cinque minuti per giro.

    Diventa «altro proposto»: lo stesso stato che avrebbe se il modello avesse
    detto altro davvero, e che si corregge dalla pagina Calendario.
    """
    google.stato.eventi = [
        _voce("g-analisi", "Analisi II", OGGI),
        _voce("g-pale", "Palestra", OGGI, 18),
    ]
    modello = ModelloFinto({"Analisi II": "lezione", "Palestra": "sport"})

    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)
    _giro(
        impostazioni,
        calendario,
        modello,
        adesso=ADESSO + timedelta(minutes=5),
        monkeypatch=monkeypatch,
    )

    assert _tipi(conn)["Palestra"] is dom.Tipo.ALTRO
    assert all(e.tag_proposto_il == ADESSO for e in _eventi(conn))
    assert len(modello.chiamate) == 1


def test_una_risposta_di_cui_non_si_capisce_niente_lascia_la_coda_intatta(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non è «sono tutti altro»: è un guasto, e seppellirebbe una coda intera."""
    google.stato.eventi = [
        _voce("g-analisi", "Analisi II", OGGI),
        _voce("g-pale", "Palestra", OGGI, 18),
    ]
    modello = ModelloFinto(risposta_fissa={"errore": "non ho capito"})

    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)

    assert all(e.tag_proposto_il is None for e in _eventi(conn))
    # E al giro dopo si riprova, invece di restare fermi.
    _giro(
        impostazioni,
        calendario,
        modello,
        adesso=ADESSO + timedelta(minutes=5),
        monkeypatch=monkeypatch,
    )
    assert len(modello.chiamate) == 2


def test_un_modello_irraggiungibile_non_si_porta_via_il_sync(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gli eventi sono già salvati: il tag è la seconda metà, non la prima.

    E il sync non si rifà per colpa del tagging — richiamerebbe Google fra
    cinque secondi per qualcosa che era andato bene.
    """
    google.stato.eventi = [_voce("g-analisi", "Analisi II", OGGI)]
    modello = ModelloFinto(errore=ProviderNonRaggiungibile("DeepSeek non risponde"))

    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)

    (evento,) = _eventi(conn)
    assert evento.titolo == "Analisi II"
    assert evento.tag_proposto_il is None
    assert len(google.stato.richieste_eventi) == 1

    _giro(
        impostazioni, calendario, modello, adesso=ADESSO.replace(minute=4), monkeypatch=monkeypatch
    )
    # Stessa fascia: Google non si richiama, e nemmeno il modello.
    assert len(google.stato.richieste_eventi) == 1
    assert len(modello.chiamate) == 1


# — quando il tagging è spento ————————————————————————————


def test_senza_chiave_il_modello_non_si_chiama_e_gli_eventi_restano_da_guardare(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    google: FintoGoogle,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Senza ROUTER_DEEPSEEK_API_KEY il tagging è spento, non rotto."""
    google.stato.eventi = [_voce("g-analisi", "Analisi II", OGGI)]
    modello = ModelloFinto({"Analisi II": "lezione"}, configurato=False)

    _giro(impostazioni, calendario, modello, monkeypatch=monkeypatch)

    assert modello.chiamate == []
    (evento,) = _eventi(conn)
    assert evento.tag_proposto_il is None
    assert evento.tipo is dom.Tipo.ALTRO


def test_col_calendario_spento_non_si_chiama_nessuno(
    impostazioni: Settings,
    calendario: _CalendarioDiTest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Senza sync non ci sono eventi nuovi: una chiamata a vuoto si pagherebbe."""
    modello = ModelloFinto()

    _giro(impostazioni, calendario, modello, sorgente=CalendarioSpento(), monkeypatch=monkeypatch)

    assert modello.chiamate == []
