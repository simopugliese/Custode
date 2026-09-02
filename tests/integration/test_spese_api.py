"""`/api/spese`: la pagina che si rilegge, e le due cose che si fanno da lì (§8.5).

Girano sull'API vera, su un database vero: le somme, le medie e le variazioni
passano dalle stesse query che userà la dashboard.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from custode_core.db import connect
from custode_core.dominio import spese as dom

pytestmark = pytest.mark.integration


def _scrivi(db_path: Path, ora: datetime, **campi: Any) -> dom.Spesa:
    """Una spesa messa nel database direttamente: il modo in cui ci arriva è
    già coperto dai test del bot, qui serve solo il dato da rileggere."""
    valori: dict[str, Any] = {"centesimi": 1000, "descrizione": "spesa"}
    valori.update(campi)
    conn = connect(db_path)
    try:
        spesa = dom.registra(conn, ora=ora, **valori)
        conn.commit()
        return spesa
    finally:
        conn.close()


# — la pagina ——————————————————————————————————————————


def test_una_pagina_spese_vuota_non_e_un_errore(client: TestClient) -> None:
    corpo = client.get("/api/spese").json()
    assert corpo["titolo"] == "Nessuna spesa in questo periodo."
    assert corpo["movimenti"] == []
    assert corpo["categorie"] == []
    assert corpo["stats"]["totaleMese"] == 0
    assert corpo["stats"]["categoriaMaggiore"] == "—"
    # Niente scontrini in attesa: campo omesso, non un oggetto vuoto.
    assert "scontrinoInAttesa" not in corpo


def test_gli_importi_escono_in_euro(client: TestClient, db_path: Path, ora: datetime) -> None:
    _scrivi(db_path, ora, centesimi=815, descrizione="colazione", categoria="Bar")
    corpo = client.get("/api/spese").json()
    (movimento,) = corpo["movimenti"]
    assert movimento["importo"] == 8.15
    assert movimento["categoria"] == "Bar"
    assert corpo["stats"]["totaleMese"] == 8.15


def test_il_periodo_cambia_cosa_si_conta(client: TestClient, db_path: Path, ora: datetime) -> None:
    # Lunedì 31 agosto: la settimana è iniziata oggi, il mese finisce oggi.
    _scrivi(db_path, ora, centesimi=1000, descrizione="oggi")
    _scrivi(db_path, ora, centesimi=2000, descrizione="settimana scorsa", giorno=date(2026, 8, 27))
    _scrivi(db_path, ora, centesimi=4000, descrizione="a luglio", giorno=date(2026, 7, 10))

    per_periodo = {
        periodo: client.get(f"/api/spese?periodo={periodo}").json()["stats"]["totaleMese"]
        for periodo in ("settimana", "mese", "anno")
    }
    assert per_periodo == {"settimana": 10.0, "mese": 30.0, "anno": 70.0}


def test_le_spese_da_confermare_non_entrano_nei_totali(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(db_path, ora, centesimi=1000, descrizione="confermata")
    _scrivi(
        db_path,
        ora,
        centesimi=9900,
        descrizione="Coop",
        luogo="Coop",
        categoria="Alimentari",
        fonte=dom.Fonte.SCONTRINO,
        stato=dom.Stato.DA_CONFERMARE,
    )

    corpo = client.get("/api/spese").json()
    assert corpo["stats"]["totaleMese"] == 10.0
    assert [m["descrizione"] for m in corpo["movimenti"]] == ["confermata"]
    # Ma lo scontrino si vede, altrimenti resterebbe in sospeso senza saperlo.
    assert corpo["scontrinoInAttesa"]["luogo"] == "Coop"
    assert corpo["scontrinoInAttesa"]["importo"] == 99.0
    assert corpo["scontrinoInAttesa"]["categoriaProposta"] == "Alimentari"


def test_la_media_e_sui_giorni_trascorsi(client: TestClient, db_path: Path, ora: datetime) -> None:
    # 31 agosto: 31 giorni trascorsi nel mese, non 31 di calendario a caso.
    _scrivi(db_path, ora, centesimi=3100, descrizione="spesa")
    assert client.get("/api/spese").json()["stats"]["mediaGiorno"] == 1.0


def test_le_categorie_hanno_una_quota_sul_totale(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(db_path, ora, centesimi=7500, descrizione="a", categoria="Casa")
    _scrivi(db_path, ora, centesimi=2500, descrizione="b", categoria="Bar")

    categorie = client.get("/api/spese").json()["categorie"]
    assert [(c["nome"], c["importo"], c["quota"]) for c in categorie] == [
        ("Casa", 75.0, 0.75),
        ("Bar", 25.0, 0.25),
    ]


def test_le_spese_senza_categoria_sono_dichiarate(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(db_path, ora, centesimi=1000, descrizione="misteriosa")
    corpo = client.get("/api/spese").json()
    assert corpo["categorie"][0]["nome"] == "Senza categoria"
    assert "non ha" in corpo["categoriaNota"]


def test_quando_tutto_e_categorizzato_non_c_e_nessuna_nota(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(db_path, ora, centesimi=1000, descrizione="spesa", categoria="Casa")
    assert "categoriaNota" not in client.get("/api/spese").json()


def test_l_andamento_ha_una_colonna_per_giorno_e_finisce_oggi(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(db_path, ora, centesimi=1000, descrizione="a", giorno=date(2026, 8, 1))
    _scrivi(db_path, ora, centesimi=500, descrizione="b", giorno=date(2026, 8, 31))

    andamento = client.get("/api/spese?periodo=mese").json()["andamentoGiorni"]
    assert len(andamento) == 31  # dal 1 al 31 agosto
    assert andamento[0] == 100  # la colonna più alta
    assert andamento[-1] == 50
    assert andamento[1] == 0


def test_sull_anno_le_colonne_sono_i_mesi(client: TestClient, db_path: Path, ora: datetime) -> None:
    # 365 barrette da tre pixel non sarebbero un grafico.
    _scrivi(db_path, ora, centesimi=1000, descrizione="a", giorno=date(2026, 3, 4))
    andamento = client.get("/api/spese?periodo=anno").json()["andamentoGiorni"]
    assert len(andamento) == 8  # da gennaio ad agosto
    assert andamento[2] == 100


def test_la_variazione_confronta_tratti_della_stessa_lunghezza(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    # Lunedì 31: la settimana corrente è lunga un giorno, quindi il confronto
    # è col solo lunedì scorso (24 agosto), non con tutta la settimana.
    _scrivi(db_path, ora, centesimi=2000, descrizione="oggi")
    _scrivi(db_path, ora, centesimi=1000, descrizione="lunedì scorso", giorno=date(2026, 8, 24))
    _scrivi(db_path, ora, centesimi=9000, descrizione="mercoledì scorso", giorno=date(2026, 8, 26))

    stats = client.get("/api/spese?periodo=settimana").json()["stats"]
    assert stats["variazioneMesePrecedente"] == 100.0


def test_senza_niente_prima_la_variazione_e_zero_non_infinito(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(db_path, ora, centesimi=2000, descrizione="oggi")
    assert client.get("/api/spese").json()["stats"]["variazioneMesePrecedente"] == 0.0


def test_il_confronto_mostra_solo_periodi_in_cui_c_era_qualcosa(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    # Su un database appena avviato, "Mese scorso: 0,00" direbbe solo che
    # Custode è nuovo.
    _scrivi(db_path, ora, centesimi=2000, descrizione="oggi")
    assert client.get("/api/spese").json()["confronto"] == []

    _scrivi(db_path, ora, centesimi=6000, descrizione="a luglio", giorno=date(2026, 7, 10))
    confronto = client.get("/api/spese").json()["confronto"]
    assert {c["label"]: c["importo"] for c in confronto} == {
        "Mese scorso": 60.0,
        "Media 3 mesi": 20.0,
    }


def test_da_scontrino_si_vede_nella_riga(client: TestClient, db_path: Path, ora: datetime) -> None:
    _scrivi(db_path, ora, centesimi=1000, descrizione="a mano")
    _scrivi(db_path, ora, centesimi=2000, descrizione="Coop", fonte=dom.Fonte.SCONTRINO)

    movimenti = client.get("/api/spese").json()["movimenti"]
    per_descrizione = {m["descrizione"]: m for m in movimenti}
    assert per_descrizione["Coop"]["daScontrino"] is True
    # Falso viene omesso: la riga "a mano" non ha bisogno di dirlo.
    assert "daScontrino" not in per_descrizione["a mano"]


# — registrare a mano ——————————————————————————————————


def test_una_spesa_scritta_dalla_dashboard_entra_subito(
    client: TestClient, db_path: Path, modello: Any
) -> None:
    modello.risposta = {"categoria": "Bar", "esistente": False}
    risposta = client.post("/api/spese", json={"importo": 8.15, "descrizione": "colazione"})
    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["importo"] == 8.15
    # Senza categoria nel corpo, la propone il modello (§6).
    assert corpo["categoria"] == "Bar"
    assert client.get("/api/spese").json()["stats"]["totaleMese"] == 8.15


def test_una_categoria_scritta_da_te_non_passa_dal_modello(
    client: TestClient, modello: Any
) -> None:
    modello.errore = RuntimeError("il modello non deve essere chiamato")
    corpo = client.post(
        "/api/spese", json={"importo": 10, "descrizione": "benzina", "categoria": "Trasporti"}
    ).json()
    assert corpo["categoria"] == "Trasporti"


def test_una_categoria_scritta_dalla_dashboard_risulta_tua(
    client: TestClient, db_path: Path
) -> None:
    client.post(
        "/api/spese", json={"importo": 10, "descrizione": "benzina", "categoria": "Trasporti"}
    )
    conn = connect(db_path)
    try:
        categoria = dom.trova_categoria(conn, "Trasporti")
    finally:
        conn.close()
    assert categoria is not None and categoria.creata_da == "utente"


def test_una_spesa_a_zero_viene_rifiutata(client: TestClient) -> None:
    risposta = client.post("/api/spese", json={"importo": 0, "descrizione": "niente"})
    assert risposta.status_code == 422


def test_una_spesa_senza_descrizione_viene_rifiutata(client: TestClient) -> None:
    assert client.post("/api/spese", json={"importo": 5, "descrizione": "  "}).status_code == 422


# — confermare uno scontrino ————————————————————————————


def test_confermare_dalla_dashboard_fa_entrare_lo_scontrino_nei_conti(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    spesa = _scrivi(
        db_path,
        ora,
        centesimi=9900,
        descrizione="Coop",
        luogo="Coop",
        categoria="Alimentari",
        fonte=dom.Fonte.SCONTRINO,
        stato=dom.Stato.DA_CONFERMARE,
    )
    risposta = client.post(f"/api/spese/{spesa.id}/conferma", json={})
    assert risposta.status_code == 200
    assert risposta.json()["importo"] == 99.0

    corpo = client.get("/api/spese").json()
    assert corpo["stats"]["totaleMese"] == 99.0
    assert "scontrinoInAttesa" not in corpo


def test_confermando_si_puo_correggere_la_categoria(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    spesa = _scrivi(
        db_path,
        ora,
        centesimi=1000,
        descrizione="Coop",
        categoria="Alimentari",
        fonte=dom.Fonte.SCONTRINO,
        stato=dom.Stato.DA_CONFERMARE,
    )
    corpo = client.post(f"/api/spese/{spesa.id}/conferma", json={"categoria": "Casa"}).json()
    assert corpo["categoria"] == "Casa"


def test_confermare_una_spesa_che_non_esiste_da_404(client: TestClient) -> None:
    assert client.post("/api/spese/999/conferma", json={}).status_code == 404


def test_confermare_una_spesa_gia_nei_conti_da_409(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    spesa = _scrivi(db_path, ora, centesimi=1000, descrizione="già dentro")
    assert client.post(f"/api/spese/{spesa.id}/conferma", json={}).status_code == 409


# — la Home e la Lista spesa ————————————————————————————


def test_la_home_mostra_quanto_hai_speso_questa_settimana(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(db_path, ora, centesimi=2500, descrizione="oggi")
    _scrivi(db_path, ora, centesimi=9900, descrizione="settimana scorsa", giorno=date(2026, 8, 27))
    assert client.get("/api/home").json()["stats"]["spesaSettimana"] == 25.0


def test_la_lista_spesa_ricorda_dove_sei_stato(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    _scrivi(
        db_path, ora, centesimi=4200, descrizione="Coop", luogo="Coop", giorno=date(2026, 8, 28)
    )
    # Senza luogo non è una spesa "fatta": la colonna mostra proprio il posto.
    _scrivi(db_path, ora, centesimi=800, descrizione="colazione")

    corpo = client.get("/api/lista-spesa").json()
    assert [(u["luogo"], u["importo"]) for u in corpo["ultimeSpese"]] == [("Coop", 42.0)]
    assert corpo["stats"]["ultimaSpesaGiorni"] == 3
    # `stimaCarrello` resta assente: vorrebbe i prezzi delle singole voci, e
    # degli scontrini si conserva solo il totale (§8.5).
    assert "stimaCarrello" not in corpo["stats"]


def test_senza_spese_la_lista_spesa_non_inventa_un_trattino_a_zero(
    client: TestClient,
) -> None:
    corpo = client.get("/api/lista-spesa").json()
    assert corpo["ultimeSpese"] == []
    assert "ultimaSpesaGiorni" not in corpo["stats"]


class TestConBudget:
    """Il blocco «Spese · settimana» della Home esiste solo con un budget."""

    @pytest.fixture
    def budget(self) -> float:
        return 120.0

    def test_il_blocco_compare_col_budget(
        self, client: TestClient, db_path: Path, ora: datetime
    ) -> None:
        _scrivi(db_path, ora, centesimi=3000, descrizione="spesa", categoria="Alimentari")
        blocco = client.get("/api/home").json()["speseSettimana"]
        assert blocco["budget"] == 120.0
        assert blocco["speso"] == 30.0
        assert blocco["categorie"] == [{"nome": "Alimentari", "importo": 30.0, "quota": 1.0}]
        assert blocco["scontriniInAttesa"] == 0

    def test_gli_scontrini_in_attesa_si_contano(
        self, client: TestClient, db_path: Path, ora: datetime
    ) -> None:
        _scrivi(
            db_path,
            ora,
            centesimi=1000,
            descrizione="Coop",
            fonte=dom.Fonte.SCONTRINO,
            stato=dom.Stato.DA_CONFERMARE,
        )
        blocco = client.get("/api/home").json()["speseSettimana"]
        assert blocco["scontriniInAttesa"] == 1
        # Non è ancora speso: aspetta un sì.
        assert blocco["speso"] == 0.0
