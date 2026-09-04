"""`/api/abitudini`: la pagina, la spunta, e le proposte (§8.6).

Girano sull'API vera su un database vero: aderenze, strisce e obiettivi
centrati passano dalle stesse funzioni che disegneranno la dashboard.

L'ora è fissata a lunedì 31 agosto 2026 (vedi `tests/conftest.py`), che è il
primo giorno della settimana: comodo per contare, perché settimana e «oggi»
cominciano insieme.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from custode_core.db import connect
from custode_core.dominio import abitudini as dom

pytestmark = pytest.mark.integration


def _con_db(db_path: Path, funzione: Any) -> Any:
    conn = connect(db_path)
    try:
        risultato = funzione(conn)
        conn.commit()
        return risultato
    finally:
        conn.close()


def _crea(client: TestClient, nome: str, target: int) -> dict[str, Any]:
    risposta = client.post("/api/abitudini", json={"nome": nome, "targetSettimanale": target})
    assert risposta.status_code == 200, risposta.text
    corpo: dict[str, Any] = risposta.json()
    return corpo


def _segna(client: TestClient, abitudine_id: str, giorno: date, fatto: bool = True) -> Any:
    return client.patch(
        f"/api/abitudini/{abitudine_id}/log", json={"data": giorno.isoformat(), "fatto": fatto}
    )


# — la pagina —


def test_una_pagina_vuota_lo_dice_senza_inventare(client: TestClient) -> None:
    dati = client.get("/api/abitudini").json()
    assert dati["titolo"] == "Non segui ancora nessuna abitudine."
    assert dati["stats"] == {
        "attive": 0,
        "obiettiviCentrati": {"fatti": 0, "totali": 0},
        "streakMigliore": 0,
        "costanzaMese": 0,
    }
    assert dati["abitudini"] == []
    # Campo assente ≠ campo vuoto: senza proposta e senza report non compaiono.
    assert "proposta" not in dati
    assert "report" not in dati


def test_creare_segnare_e_rileggere(client: TestClient, ora: datetime) -> None:
    creata = _crea(client, "Palestra", 3)
    assert creata["frequenzaLabel"] == "3 volte a settimana"
    assert creata["segnataOggi"] is False

    aggiornata = _segna(client, creata["id"], ora.date()).json()
    assert aggiornata["segnataOggi"] is True
    assert aggiornata["goalRatioLabel"] == "1/3"
    # Lunedì è il primo dei sette pallini.
    assert aggiornata["giorni"] == [True, False, False, False, False, False, False]


def test_l_evidenziazione_dice_esattamente_quello_che_si_legge(
    client: TestClient, ora: datetime
) -> None:
    """Una riga verde accanto a «1/3» sarebbe un numero che si contraddice."""
    creata = _crea(client, "Palestra", 3)
    _segna(client, creata["id"], ora.date())

    (riga,) = client.get("/api/abitudini?vista=settimana").json()["abitudini"]
    assert riga["goalRatioLabel"] == "1/3"
    assert "evidenziata" not in riga


def test_l_obiettivo_centrato_si_evidenzia(client: TestClient, ora: datetime) -> None:
    creata = _crea(client, "Palestra", 3)
    # L'ora fissata è lunedì: i tre log stanno tutti nel passato, quindi solo
    # quello di oggi cade nella settimana corrente. Il target si centra dal
    # lato del mese, dove i giorni trascorsi sono trenta.
    for scarto in range(3):
        _segna(client, creata["id"], ora.date() - timedelta(days=scarto))

    settimana = client.get("/api/abitudini?vista=settimana").json()
    assert settimana["abitudini"][0]["goalRatioLabel"] == "1/3"
    assert settimana["stats"]["obiettiviCentrati"] == {"fatti": 0, "totali": 1}
    assert settimana["titolo"] == "0 obiettivi centrati su 1, questa settimana."

    # Nel mese il denominatore è proporzionale ai giorni trascorsi: 31 giorni a
    # 3 volte a settimana fanno 13, e tre volte non bastano.
    mese = client.get("/api/abitudini?vista=mese").json()
    assert mese["abitudini"][0]["goalRatioLabel"] == "3/13"
    assert mese["stats"]["obiettiviCentrati"] == {"fatti": 0, "totali": 1}


def test_centrare_il_target_della_settimana(client: TestClient, ora: datetime) -> None:
    creata = _crea(client, "Corsa", 2)
    _segna(client, creata["id"], ora.date())
    # La settimana comincia oggi (lunedì): per centrarne due serve un secondo
    # giorno, che nel passato cadrebbe nella settimana scorsa. Si abbassa il
    # target invece di inventare un futuro che non si può segnare.
    client.patch(f"/api/abitudini/{creata['id']}", json={"targetSettimanale": 1})

    dati = client.get("/api/abitudini?vista=settimana").json()
    assert dati["abitudini"][0]["goalRatioLabel"] == "1/1"
    assert dati["abitudini"][0]["evidenziata"] is True
    assert dati["titolo"] == "Tutti gli obiettivi centrati questa settimana."


def test_il_target_settimanale_conta_solo_i_giorni_della_settimana(
    client: TestClient, ora: datetime
) -> None:
    """Un log della settimana scorsa non gonfia il rapporto di questa."""
    creata = _crea(client, "Lettura", 5)
    _segna(client, creata["id"], ora.date() - timedelta(days=3))  # venerdì scorso

    (riga,) = client.get("/api/abitudini?vista=settimana").json()["abitudini"]
    assert riga["goalRatioLabel"] == "0/5"


def test_tutti_i_giorni_si_dice_a_parole(client: TestClient) -> None:
    creata = _crea(client, "Meditazione", 7)
    assert creata["frequenzaLabel"] == "tutti i giorni"


def test_la_striscia_e_in_giorni_e_la_migliore_si_evidenzia(
    client: TestClient, ora: datetime
) -> None:
    palestra = _crea(client, "Palestra", 3)
    lettura = _crea(client, "Lettura", 5)
    for scarto in range(4):
        _segna(client, lettura["id"], ora.date() - timedelta(days=scarto))
    _segna(client, palestra["id"], ora.date())

    dati = client.get("/api/abitudini").json()
    strisce = {s["nome"]: s for s in dati["streak"]}
    assert strisce["Lettura"]["valoreLabel"] == "4 giorni"
    assert strisce["Lettura"].get("evidenziata") is True
    assert strisce["Palestra"]["valoreLabel"] == "1 giorno"
    assert dati["stats"]["streakMigliore"] == 4


def test_una_striscia_a_zero_resta_visibile_ma_spenta(client: TestClient) -> None:
    """Toglierla nasconderebbe proprio quella su cui c'è da lavorare."""
    _crea(client, "Corsa", 2)
    (riga,) = client.get("/api/abitudini").json()["streak"]
    assert riga["valoreLabel"] == "—"
    assert riga["mutedRow"] is True


def test_il_mese_mostra_l_abitudine_piu_costante(client: TestClient, ora: datetime) -> None:
    palestra = _crea(client, "Palestra", 3)
    lettura = _crea(client, "Lettura", 5)
    _segna(client, palestra["id"], ora.date())
    for scarto in range(3):
        _segna(client, lettura["id"], ora.date() - timedelta(days=scarto))

    mese = client.get("/api/abitudini?vista=mese").json()["meseSingolaAbitudine"]
    assert mese["nome"] == "Lettura"
    # Il mese va dal primo a oggi: il 31 agosto sono 31 caselle.
    assert len(mese["giorni"]) == 31
    assert mese["giorni"][-1] is True
    assert "3 giorni su 31" in mese["nota"]


def test_l_avviso_esce_solo_per_un_abitudine_ferma_da_un_pezzo(
    client: TestClient, ora: datetime
) -> None:
    creata = _crea(client, "Palestra", 3)
    _segna(client, creata["id"], ora.date() - timedelta(days=3))
    assert "avviso" not in client.get("/api/abitudini").json()

    _segna(client, creata["id"], ora.date() - timedelta(days=3), fatto=False)
    _segna(client, creata["id"], ora.date() - timedelta(days=20))
    dati = client.get("/api/abitudini").json()
    assert "«Palestra» non la segni da 20 giorni" in dati["avviso"]


def test_un_abitudine_mai_segnata_non_fa_scattare_l_avviso(client: TestClient) -> None:
    """È nuova, non è in calo: dirle che «non la segni da mai» sarebbe assurdo."""
    _crea(client, "Palestra", 3)
    assert "avviso" not in client.get("/api/abitudini").json()


# — creazione e modifica (§8.6: tutto modificabile in qualsiasi momento) —


def test_cambiare_target_e_nome(client: TestClient) -> None:
    creata = _crea(client, "Palestra", 3)
    modificata = client.patch(
        f"/api/abitudini/{creata['id']}", json={"nome": "Pesi", "targetSettimanale": 4}
    ).json()
    assert modificata["nome"] == "Pesi"
    assert modificata["frequenzaLabel"] == "4 volte a settimana"


def test_disattivare_la_toglie_dalla_pagina_ma_non_dai_dati(
    client: TestClient, ora: datetime
) -> None:
    creata = _crea(client, "Palestra", 3)
    _segna(client, creata["id"], ora.date())

    client.patch(f"/api/abitudini/{creata['id']}", json={"attiva": False})

    assert client.get("/api/abitudini").json()["abitudini"] == []
    # Riattivandola la storia è ancora lì.
    client.patch(f"/api/abitudini/{creata['id']}", json={"attiva": True})
    (riga,) = client.get("/api/abitudini").json()["abitudini"]
    assert riga["goalRatioLabel"] == "1/3"


@pytest.mark.parametrize("target", [0, 8])
def test_un_target_fuori_scala_e_422(client: TestClient, target: int) -> None:
    assert (
        client.post("/api/abitudini", json={"nome": "X", "targetSettimanale": target}).status_code
        == 422
    )


def test_un_nome_vuoto_e_422(client: TestClient) -> None:
    assert (
        client.post("/api/abitudini", json={"nome": "  ", "targetSettimanale": 3}).status_code
        == 422
    )


def test_modificare_qualcosa_che_non_esiste_e_404(client: TestClient) -> None:
    assert client.patch("/api/abitudini/999", json={"attiva": False}).status_code == 404


# — il log —


def test_togliere_la_spunta(client: TestClient, ora: datetime) -> None:
    creata = _crea(client, "Palestra", 3)
    _segna(client, creata["id"], ora.date())
    aggiornata = _segna(client, creata["id"], ora.date(), fatto=False).json()
    assert aggiornata["segnataOggi"] is False
    assert aggiornata["goalRatioLabel"] == "0/3"


def test_un_giorno_futuro_non_si_segna(client: TestClient, ora: datetime) -> None:
    """Come per le spese (§8.5): sarebbe scritto e invisibile in ogni vista."""
    creata = _crea(client, "Palestra", 3)
    risposta = _segna(client, creata["id"], ora.date() + timedelta(days=1))
    assert risposta.status_code == 422


def test_una_data_malformata_e_422(client: TestClient) -> None:
    creata = _crea(client, "Palestra", 3)
    risposta = client.patch(
        f"/api/abitudini/{creata['id']}/log", json={"data": "31/08/2026", "fatto": True}
    )
    assert risposta.status_code == 422


def test_segnare_un_abitudine_che_non_esiste_e_404(client: TestClient, ora: datetime) -> None:
    assert _segna(client, "999", ora.date()).status_code == 404


# — proposte —


def test_la_proposta_si_vede_e_accettandola_cambia_il_target(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    creata = _crea(client, "Palestra", 3)

    proposta_id = _con_db(
        db_path,
        lambda conn: dom.proponi(
            conn,
            int(creata["id"]),
            target_proposto=2,
            motivazione="sei a 2,1 di media da sei settimane",
            ora=ora,
        ).id,
    )

    dati = client.get("/api/abitudini").json()
    assert dati["proposta"]["titolo"] == "Palestra: da 3 a 2 volte a settimana"
    assert dati["proposta"]["motivazione"] == "sei a 2,1 di media da sei settimane"

    assert client.post(f"/api/abitudini/{proposta_id}/proposta/accetta").status_code == 204

    dopo = client.get("/api/abitudini").json()
    assert dopo["abitudini"][0]["frequenzaLabel"] == "2 volte a settimana"
    assert "proposta" not in dopo


def test_rifiutare_lascia_il_target_com_era(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    creata = _crea(client, "Palestra", 3)
    proposta_id = _con_db(
        db_path,
        lambda conn: dom.proponi(
            conn, int(creata["id"]), target_proposto=2, motivazione="perché", ora=ora
        ).id,
    )

    assert client.post(f"/api/abitudini/{proposta_id}/proposta/rifiuta").status_code == 204

    dopo = client.get("/api/abitudini").json()
    assert dopo["abitudini"][0]["frequenzaLabel"] == "3 volte a settimana"
    assert "proposta" not in dopo


def test_decidere_due_volte_e_409(client: TestClient, db_path: Path, ora: datetime) -> None:
    creata = _crea(client, "Palestra", 3)
    proposta_id = _con_db(
        db_path,
        lambda conn: dom.proponi(
            conn, int(creata["id"]), target_proposto=2, motivazione="perché", ora=ora
        ).id,
    )
    client.post(f"/api/abitudini/{proposta_id}/proposta/accetta")
    assert client.post(f"/api/abitudini/{proposta_id}/proposta/rifiuta").status_code == 409


def test_una_proposta_che_non_esiste_e_404(client: TestClient) -> None:
    assert client.post("/api/abitudini/999/proposta/accetta").status_code == 404


# — il report narrativo —


def test_il_report_compare_quando_il_worker_ne_ha_scritto_uno(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _crea(client, "Palestra", 3)
    _con_db(
        db_path,
        lambda conn: dom.salva_report(
            conn,
            periodo=dom.Periodo.SETTIMANA,
            chiave=ora.date(),
            testo="Settimana solida: tre volte in palestra.",
            ora=ora,
        ),
    )

    dati = client.get("/api/abitudini?vista=settimana").json()
    assert dati["report"]["testo"] == "Settimana solida: tre volte in palestra."
    assert "settimana del 31 agosto" in dati["report"]["periodoLabel"]
    # Il settimanale non compare nella vista mese: sono due racconti diversi.
    assert "report" not in client.get("/api/abitudini?vista=mese").json()
