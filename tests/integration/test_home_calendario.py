"""Il blocco calendario della Home (§8.10): quando compare, e cosa dice se è vuoto.

Il calendario è collegato per tutto questo file — è lo stato in cui il blocco
esiste. Che *senza* credenziali non compaia affatto sta in `test_home.py`,
insieme agli altri moduli non attivi.

Il job qui non gira: ha i suoi test contro un finto Google che è un server vero
(`test_worker_calendario.py`). Qui si prova cosa la Home fa dei dati che il job
lascia dietro di sé, compreso il caso in cui non ne ha ancora lasciati.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import SettingsConfigDict

from custode_calendario.config import ImpostazioniCalendario
from custode_calendario.evento import Evento
from custode_core.db import connessione
from custode_core.dominio import calendario as dom_calendario
from custode_core.registro_job import SYNC_CALENDARIO, segna_eseguito

pytestmark = pytest.mark.integration

ORA_DI_TEST = datetime(2026, 8, 31, 8, 41)
OGGI = ORA_DI_TEST.date()


@pytest.fixture
def calendario() -> ImpostazioniCalendario:
    """Calendario collegato: è lo stato in cui il blocco deve comparire."""

    class _Collegato(ImpostazioniCalendario):
        model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")

    return _Collegato(client_id="id", client_secret="segreto", refresh_token="refresh")


def _sincronizza(db_path: Path, eventi: list[Evento], quando: datetime = ORA_DI_TEST) -> None:
    """Quello che avrebbe fatto il worker, scritto direttamente sul database.

    Qui non si prova il job — quello ha i suoi test contro un finto Google che
    è un server vero: si prova cosa la Home fa dei dati che il job lascia.
    """
    with connessione(db_path) as conn:
        dom_calendario.sincronizza(
            conn,
            eventi,
            da=OGGI - timedelta(days=7),
            a=OGGI + timedelta(days=14),
            ora=quando,
        )
        segna_eseguito(conn, SYNC_CALENDARIO, quando, quando)


def _evento(
    identificativo: str,
    titolo: str,
    ora_inizio: int,
    ore: int = 2,
    giorno: date = OGGI,
    **extra: Any,
) -> Evento:
    inizio = datetime.combine(giorno, time(ora_inizio, 0))
    return Evento(
        id=identificativo,
        titolo=titolo,
        inizio=inizio,
        fine=inizio + timedelta(hours=ore),
        **extra,
    )


def test_il_blocco_compare_appena_lo_colleghi_non_al_primo_evento(
    client: TestClient,
) -> None:
    """Il segnale sono le credenziali, non gli eventi.

    Aspettare il primo sync vorrebbe dire far comparire il blocco un quarto
    d'ora dopo averlo collegato, senza che niente spieghi l'attesa.
    """
    assert "calendarioOggi" in client.get("/api/home").json()


def test_collegato_ma_mai_sincronizzato_lo_dice_invece_di_mentire(
    client: TestClient,
) -> None:
    """«Nessun evento oggi» a calendario appena collegato sarebbe falso."""
    corpo = client.get("/api/home").json()

    assert corpo["calendarioOggi"] == []
    assert corpo["calendarioNotaVuoto"] == "Non ho ancora sincronizzato gli eventi di oggi."


def test_sincronizzato_e_davvero_libero_dice_un_altra_cosa(
    client: TestClient, db_path: Path
) -> None:
    _sincronizza(db_path, [])

    corpo = client.get("/api/home").json()

    assert corpo["calendarioOggi"] == []
    assert corpo["calendarioNotaVuoto"] == "Nessun evento oggi."


def test_gli_impegni_di_oggi_in_ordine_di_orario(client: TestClient, db_path: Path) -> None:
    _sincronizza(
        db_path,
        [
            _evento("g-2", "Palestra", 18, ore=1),
            _evento("g-1", "Analisi II", 9, luogo="Aula 3"),
            _evento("g-3", "Domani", 9, giorno=OGGI + timedelta(days=1)),
        ],
    )

    corpo = client.get("/api/home").json()

    assert corpo["calendarioOggi"] == [
        {
            "id": corpo["calendarioOggi"][0]["id"],
            "ora": "09:00",
            "titolo": "Analisi II",
            "luogo": "Aula 3",
        },
        {"id": corpo["calendarioOggi"][1]["id"], "ora": "18:00", "titolo": "Palestra"},
    ]
    # Con degli eventi la nota non serve: sparisce.
    assert "calendarioNotaVuoto" not in corpo


def test_un_evento_di_giornata_non_si_inventa_un_orario(client: TestClient, db_path: Path) -> None:
    _sincronizza(
        db_path,
        [
            Evento(
                id="g-ferie",
                titolo="Ferie",
                inizio=datetime.combine(OGGI - timedelta(days=1), time.min),
                fine=datetime.combine(OGGI + timedelta(days=1), time.max),
                tutto_il_giorno=True,
            )
        ],
    )

    (voce,) = client.get("/api/home").json()["calendarioOggi"]

    # «00:00» per delle ferie sarebbe un dato inventato: l'ora non c'è.
    assert voce["ora"] == "—"
    assert voce["meta"] == "tutto il giorno"


def test_un_evento_cominciato_ieri_non_mostra_l_ora_di_ieri(
    client: TestClient, db_path: Path
) -> None:
    """Un treno notturno partito ieri alle 22 non è «le 22» di oggi."""
    _sincronizza(
        db_path,
        [_evento("g-treno", "Treno per Milano", 22, ore=10, giorno=OGGI - timedelta(days=1))],
    )

    (voce,) = client.get("/api/home").json()["calendarioOggi"]

    assert voce["ora"] == "—"
    assert voce["meta"] == "in corso"
