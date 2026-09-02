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
    BACKUP,
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
    *,
    backup_cartella: Path | None = None,
) -> None:
    monkeypatch.setattr(worker_main, "adesso", lambda _fuso: adesso)
    worker_main.giro(
        impostazioni,
        _WorkerDiTest(
            giorno_riepilogo="domenica",
            ora_riepilogo="21:00",
            ora_backup="03:30",
            # Senza percorso esplicito il backup finirebbe in /backup, che qui
            # non esiste: fallisce e viene solo registrato nei log, che è il
            # comportamento voluto per i test che non lo riguardano.
            backup_cartella=backup_cartella or Path("/backup-inesistente"),
        ),
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


# — backup giornaliero (§9) —


def test_il_backup_gira_ogni_giorno_e_si_segna(
    impostazioni: Settings, conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cartella = tmp_path / "backup"
    telegram = TelegramFinto()

    _giro(impostazioni, DOMENICA_SERA, telegram, monkeypatch, backup_cartella=cartella)

    assert [p.name for p in cartella.iterdir()] == ["custode-2026-09-06.db.gz"]
    assert gia_eseguito(conn, BACKUP, DOMENICA_SERA.date())
    # Un backup riuscito non manda notifiche: se lo facesse ogni giorno, la
    # notifica smetterebbe di voler dire qualcosa.
    assert telegram.mandati == []


def test_il_backup_non_si_ripete_nello_stesso_giorno(
    impostazioni: Settings, conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cartella = tmp_path / "backup"
    _giro(impostazioni, DOMENICA_SERA, TelegramFinto(), monkeypatch, backup_cartella=cartella)
    primo = (cartella / "custode-2026-09-06.db.gz").read_bytes()

    _giro(
        impostazioni,
        DOMENICA_SERA + timedelta(minutes=5),
        TelegramFinto(),
        monkeypatch,
        backup_cartella=cartella,
    )

    assert (cartella / "custode-2026-09-06.db.gz").read_bytes() == primo
    assert len(list(cartella.iterdir())) == 1


def test_un_backup_fallito_non_si_segna_e_non_ferma_il_resto(
    impostazioni: Settings, conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backup e riepilogo sono due job indipendenti: uno rotto non ferma l'altro.

    La cartella si fa fallire mettendo un *file* dove dovrebbe esserci una
    directory, invece che togliendo i permessi: i test girano spesso come root,
    e root i bit di permesso li ignora — la prova non proverebbe niente.
    """
    dom_profilo.aggiungi_candidato(
        conn, messaggio_origine="x", estratto="Preferisce il backend", ora=DOMENICA_SERA
    )
    ostacolo = tmp_path / "non-una-cartella"
    ostacolo.write_text("sono un file")
    telegram = TelegramFinto()

    _giro(impostazioni, DOMENICA_SERA, telegram, monkeypatch, backup_cartella=ostacolo)

    assert not gia_eseguito(conn, BACKUP, DOMENICA_SERA.date())
    # Il riepilogo settimanale è andato avanti: sono due job indipendenti.
    assert len(telegram.mandati) == 1


def test_il_backup_recupera_il_giorno_prima(
    impostazioni: Settings, conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alle 02:00, prima dell'ora di backup: quello di ieri non è stato fatto."""
    cartella = tmp_path / "backup"

    _giro(
        impostazioni,
        datetime(2026, 9, 6, 2, 0),
        TelegramFinto(),
        monkeypatch,
        backup_cartella=cartella,
    )

    # Il file porta la data di *adesso*, ma copre il giorno rimasto scoperto.
    assert gia_eseguito(conn, BACKUP, date(2026, 9, 5))
