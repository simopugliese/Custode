"""Un giro del worker: cosa decide di fare, e cosa succede quando qualcosa va male.

`giro` è il punto in cui pianificazione, job e invio si incontrano. La regola
che questi test difendono è quella che si scoprirebbe solo perdendo una
settimana: **un invio fallito non segna il job come fatto**.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

from custode_bot.risposte import Risposta
from custode_core.config import Settings
from custode_core.db import connessione
from custode_core.dominio import profilo as dom_profilo
from custode_worker import main as worker_main
from custode_worker.config import ImpostazioniWorker
from custode_worker.pianificazione import (
    RIEPILOGO_SETTIMANALE,
    gia_eseguito,
    segna_eseguito,
)
from custode_worker.telegram import InvioNonRiuscito

pytestmark = pytest.mark.integration

# Domenica 6 settembre 2026, le 21:00 in punto: il momento previsto.
DOMENICA_SERA = datetime(2026, 9, 6, 21, 0)
LUNEDI = date(2026, 8, 31)  # la settimana che finisce quella domenica
LUNEDI_PRIMA = LUNEDI - timedelta(days=7)


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


@pytest.fixture
def impostazioni(db_path: Path) -> Settings:
    class _Test(Settings):
        model_config = SettingsConfigDict(env_prefix="CUSTODE_", env_file=None, extra="ignore")

    return _Test(ambiente="test", db_path=db_path, timezone="Europe/Rome")


@pytest.fixture
def preparato(conn: Any, ora: datetime) -> Iterator[None]:
    """Lo schema c'è già (fixture `conn`) e c'è un candidato da rivedere."""
    dom_profilo.aggiungi_candidato(
        conn, messaggio_origine="un messaggio", estratto="Preferisce il backend", ora=ora
    )
    yield


def _giro(
    impostazioni: Settings,
    adesso: datetime,
    telegram: TelegramFinto,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_main, "adesso", lambda _fuso: adesso)
    worker_main.giro(
        impostazioni,
        _WorkerDiTest(giorno_riepilogo="domenica", ora_riepilogo="21:00"),
        router=RouterFinto(),  # type: ignore[arg-type]
        telegram=telegram,  # type: ignore[arg-type]
    )


def test_prima_dell_ora_la_settimana_in_corso_non_e_dovuta(
    impostazioni: Settings,
    conn: Any,
    preparato: None,
    ora: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alle 20:00 di domenica manca ancora un'ora.

    La settimana *precedente* sarebbe dovuta (il suo momento è passato da un
    pezzo): la si segna come già fatta, altrimenti scatterebbe il recupero — che
    è il comportamento voluto, provato in `test_worker_pianificazione`.
    """
    segna_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRIMA, ora)
    telegram = TelegramFinto()

    _giro(impostazioni, datetime(2026, 9, 6, 20, 0), telegram, monkeypatch)

    assert telegram.mandati == []
    assert not gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI)


def test_il_recupero_manda_la_settimana_rimasta_indietro(
    impostazioni: Settings, preparato: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Se il Pi era spento domenica scorsa, il giro di adesso la recupera."""
    telegram = TelegramFinto()

    _giro(impostazioni, datetime(2026, 9, 6, 20, 0), telegram, monkeypatch)

    assert len(telegram.mandati) == 1
    with connessione(impostazioni.db_path) as conn:
        assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI_PRIMA)


def test_all_ora_manda_e_segna(
    impostazioni: Settings, preparato: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    telegram = TelegramFinto()

    _giro(impostazioni, DOMENICA_SERA, telegram, monkeypatch)

    assert len(telegram.mandati) == 1
    assert "Preferisce il backend" in telegram.mandati[0].testo
    with connessione(impostazioni.db_path) as conn:
        assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI)


def test_un_secondo_giro_non_rimanda_niente(
    impostazioni: Settings, preparato: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il worker si sveglia ogni cinque minuti: senza registro spammerebbe."""
    telegram = TelegramFinto()
    _giro(impostazioni, DOMENICA_SERA, telegram, monkeypatch)
    _giro(impostazioni, datetime(2026, 9, 6, 21, 5), telegram, monkeypatch)

    assert len(telegram.mandati) == 1


def test_se_l_invio_fallisce_il_job_non_e_fatto(
    impostazioni: Settings, preparato: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Perdere la settimana per trenta secondi di rete giù sarebbe sproporzionato."""
    rotto = TelegramFinto(errore=InvioNonRiuscito("niente rete"))

    _giro(impostazioni, DOMENICA_SERA, rotto, monkeypatch)

    with connessione(impostazioni.db_path) as conn:
        assert not gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI)

    # Al giro dopo, con la rete tornata, il messaggio parte.
    buono = TelegramFinto()
    _giro(impostazioni, datetime(2026, 9, 6, 21, 5), buono, monkeypatch)
    assert len(buono.mandati) == 1


def test_una_settimana_muta_si_segna_lo_stesso(
    impostazioni: Settings, conn: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Niente da dire, niente messaggio — ma il job non deve riprovare all'infinito."""
    telegram = TelegramFinto()

    _giro(impostazioni, DOMENICA_SERA, telegram, monkeypatch)

    assert telegram.mandati == []
    with connessione(impostazioni.db_path) as conn2:
        assert gia_eseguito(conn2, RIEPILOGO_SETTIMANALE, LUNEDI)
