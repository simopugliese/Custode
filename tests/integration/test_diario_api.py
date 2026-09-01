"""`/api/diario` contro l'API completa e un database vero su disco.

Il contratto è `dashboard/API.md` + `dashboard/src/types/api.ts`: qui si
verifica che la risposta abbia esattamente quella forma, campi omessi compresi.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from custode_core.db import connect
from custode_core.dominio import diario as dom

pytestmark = pytest.mark.integration


@pytest.fixture
def scrivi(client: TestClient, db_path: Path) -> Iterator[sqlite3.Connection]:
    """Una connessione allo stesso file su cui gira l'API.

    Il diario si riempie da Telegram, non dall'API: per esercitare la pagina
    serve scrivere le voci dal dominio, come fa il bot.
    """
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _voce_approvata(
    conn: sqlite3.Connection, ora: datetime, giorno: date, testo: str, tag: list[str]
) -> dom.Voce:
    voce, _ = dom.aggiungi_materiale(conn, giorno=giorno, testo="materiale", ora=ora)
    dom.proponi(conn, voce.id, riassunto=testo, tag=tag)
    return dom.approva(conn, voce.id, ora)


def _bozza(conn: sqlite3.Connection, ora: datetime, giorno: date) -> dom.Voce:
    voce, _ = dom.aggiungi_materiale(conn, giorno=giorno, testo="materiale", ora=ora)
    dom.aggiungi_materiale(conn, giorno=giorno, testo="dettato", ora=ora, da_vocale=True)
    return dom.proponi(conn, voce.id, riassunto="Bozza da approvare.", tag=["umore"])


# — pagina vuota —


def test_diario_vuoto(client: TestClient) -> None:
    """Il modulo c'è e non ha niente da dire: 200, non 501, e liste vuote."""
    dati = client.get("/api/diario").json()

    assert dati["titolo"] == "Il diario è ancora vuoto."
    assert dati["vociApprovate"] == 0
    assert dati["vociInAttesa"] == 0
    assert dati["temiDelMese"] == []
    assert dati["coperturaMese"] == [False] * 31  # agosto
    # Un solo segnaposto per oggi, non trenta righe "nessuna voce".
    assert [v["stato"] for v in dati["voci"]] == ["assente"]


def test_i_riepiloghi_sono_omessi_finche_non_c_e_il_worker(client: TestClient) -> None:
    """Campo assente ≠ campo vuoto: la dashboard non disegna il blocco."""
    dati = client.get("/api/diario").json()
    assert "riepilogoSettimanale" not in dati
    assert "riepilogoMensile" not in dati


# — timeline —


def test_una_voce_approvata_e_una_bozza(
    client: TestClient, scrivi: sqlite3.Connection, ora: datetime
) -> None:
    oggi = ora.date()
    _voce_approvata(
        scrivi, ora, oggi - timedelta(days=1), "Hai studiato tutto il giorno.", ["studio"]
    )
    _bozza(scrivi, ora, oggi)

    dati = client.get("/api/diario").json()

    assert dati["vociApprovate"] == 1
    assert dati["vociInAttesa"] == 1
    assert "1 voce da approvare" in dati["titolo"]

    oggi_riga, ieri_riga = dati["voci"][0], dati["voci"][1]
    assert oggi_riga["stato"] == "da_approvare"
    assert oggi_riga["testo"] == "Bozza da approvare."
    assert oggi_riga["fonteLabel"] == "da 1 vocale e 1 messaggio"
    assert "approvataAlleLabel" not in oggi_riga  # non è approvata

    assert ieri_riga["stato"] == "approvata"
    assert ieri_riga["dataLabel"] == "Dom 30 agosto"
    assert ieri_riga["approvataAlleLabel"] == "08:41"
    assert ieri_riga["tag"] == ["studio"]


def test_i_buchi_dentro_il_periodo_si_vedono(
    client: TestClient, scrivi: sqlite3.Connection, ora: datetime
) -> None:
    """Un giorno saltato è un'informazione; un mese mai iniziato no."""
    oggi = ora.date()
    _voce_approvata(scrivi, ora, oggi - timedelta(days=2), "Due giorni fa.", [])

    voci = client.get("/api/diario").json()["voci"]

    assert [v["stato"] for v in voci] == ["assente", "assente", "approvata"]
    assert voci[0]["dataLabel"] == "Lun 31 agosto"


def test_statistiche_e_temi(client: TestClient, scrivi: sqlite3.Connection, ora: datetime) -> None:
    oggi = ora.date()
    _voce_approvata(scrivi, ora, oggi, "una due tre", ["studio", "umore"])
    _voce_approvata(scrivi, ora, oggi - timedelta(days=1), "una due tre quattro cinque", ["studio"])

    dati = client.get("/api/diario").json()

    assert dati["stats"]["vociDelMese"] == 2
    assert dati["stats"]["giorniConsecutivi"] == 2
    assert dati["stats"]["paroleMedia"] == 4  # (3 + 5) / 2
    assert dati["stats"]["temaPiuRicorrente"] == "studio"
    assert dati["temiDelMese"] == [
        {"nome": "studio", "occorrenze": 2, "quota": 1.0},
        {"nome": "umore", "occorrenze": 1, "quota": 0.5},
    ]
    assert dati["coperturaMese"][29:31] == [True, True]


# — viste —


@pytest.mark.parametrize("vista", ["timeline", "settimane", "mesi"])
def test_tutte_le_viste_del_contratto_rispondono(
    client: TestClient, scrivi: sqlite3.Connection, ora: datetime, vista: str
) -> None:
    _voce_approvata(scrivi, ora, ora.date(), "Una giornata.", ["studio"])
    risposta = client.get(f"/api/diario?vista={vista}")
    assert risposta.status_code == 200
    assert risposta.json()["voci"]


def test_la_vista_settimane_raggruppa(
    client: TestClient, scrivi: sqlite3.Connection, ora: datetime
) -> None:
    oggi = ora.date()  # lunedì 31 agosto 2026
    _voce_approvata(scrivi, ora, oggi, "Lunedì.", ["studio"])
    _voce_approvata(scrivi, ora, oggi - timedelta(days=7), "Lunedì scorso.", ["studio"])

    voci = client.get("/api/diario?vista=settimane").json()["voci"]

    assert len(voci) == 2
    assert voci[0]["testo"] == "1 giornata scritta."
    # A cavallo di due mesi si nominano entrambi: «31–6 settembre» sarebbe un
    # intervallo che va all'indietro.
    assert voci[0]["dataLabel"] == "31 agosto – 6 settembre"
    assert voci[1]["dataLabel"] == "24–30 agosto"


def test_una_vista_inventata_e_rifiutata(client: TestClient) -> None:
    assert client.get("/api/diario?vista=annuale").status_code == 422


# — mutazioni —


def test_approva(client: TestClient, scrivi: sqlite3.Connection, ora: datetime) -> None:
    voce = _bozza(scrivi, ora, ora.date())

    risposta = client.post(f"/api/diario/{voce.id}/approva")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["stato"] == "approvata"
    assert corpo["testo"] == "Bozza da approvare."
    assert corpo["approvataAlleLabel"] == "08:41"

    assert client.get("/api/diario").json()["vociInAttesa"] == 0


def test_scarta(client: TestClient, scrivi: sqlite3.Connection, ora: datetime) -> None:
    voce = _bozza(scrivi, ora, ora.date())

    assert client.post(f"/api/diario/{voce.id}/scarta").status_code == 204

    dati = client.get("/api/diario").json()
    assert dati["vociInAttesa"] == 0
    assert [v["stato"] for v in dati["voci"]] == ["assente"]


def test_approvare_una_voce_che_non_c_e(client: TestClient) -> None:
    assert client.post("/api/diario/999/approva").status_code == 404
    assert client.post("/api/diario/999/scarta").status_code == 404


def test_approvare_una_giornata_senza_bozza(
    client: TestClient, scrivi: sqlite3.Connection, ora: datetime
) -> None:
    """La raccolta è ancora aperta: non c'è niente da approvare."""
    voce, _ = dom.aggiungi_materiale(scrivi, giorno=ora.date(), testo="materiale", ora=ora)

    risposta = client.post(f"/api/diario/{voce.id}/approva")

    assert risposta.status_code == 409
    assert "bozza" in risposta.json()["detail"]


def test_una_bozza_del_mese_scorso_resta_visibile(
    client: TestClient, scrivi: sqlite3.Connection, ora: datetime
) -> None:
    """Una cosa da sbrigare non deve sparire perché è cambiato il mese.

    Il periodo della timeline è il mese corrente: senza un trattamento a parte,
    una bozza lasciata in sospeso il 31 diventerebbe invisibile — e non
    approvabile — il primo del mese dopo.
    """
    scorso = dom.primo_del_mese(ora.date()) - timedelta(days=1)
    voce = _bozza(scrivi, ora, scorso)

    dati = client.get("/api/diario").json()

    assert dati["vociInAttesa"] == 1
    arretrata = [v for v in dati["voci"] if v["id"] == str(voce.id)]
    assert arretrata and arretrata[0]["stato"] == "da_approvare"
    # E si può ancora approvare.
    assert client.post(f"/api/diario/{voce.id}/approva").status_code == 200


def test_una_bozza_arretrata_si_vede_anche_nelle_viste_aggregate(
    client: TestClient, scrivi: sqlite3.Connection, ora: datetime
) -> None:
    scorso = dom.primo_del_mese(ora.date()) - timedelta(days=1)
    _bozza(scrivi, ora, scorso)

    for vista in ("settimane", "mesi"):
        voci = client.get(f"/api/diario?vista={vista}").json()["voci"]
        assert any(v["stato"] == "da_approvare" for v in voci), vista
