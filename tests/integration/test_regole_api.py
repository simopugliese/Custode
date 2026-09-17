"""La pagina Regole (§8.10): `GET /api/regole` e le tre mutazioni.

Le regole si scrivono a parole, non da qui: questi test le creano passando
dall'interprete, che è la strada vera, e provano cosa la pagina ne fa.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from custode_core.db import connessione
from custode_core.dominio import regole as dom
from custode_core.registro_job import segna_eseguito
from tests.integration.conftest import RouterFinto

pytestmark = pytest.mark.integration


def _scrivi(
    client: TestClient,
    modello: RouterFinto,
    messaggio: str = "prendi la creatina",
    **campi: Any,
) -> str:
    """Una regola creata dalla strada vera: la barra «A Custode»."""
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": messaggio,
            "regola_trigger": "orario",
            "regola_ora": "19:00",
            **campi,
        }
    )
    client.post("/api/assistente/messaggio", json={"testo": "x"})
    identificatore: str = _pagina(client)["regoleAttive"][0]["id"]
    return identificatore


def _pagina(client: TestClient) -> dict[str, Any]:
    risposta = client.get("/api/regole")
    assert risposta.status_code == 200
    corpo: dict[str, Any] = risposta.json()
    return corpo


# — la pagina non risponde più 501 —


def test_la_pagina_esiste_e_dice_che_non_hai_regole(client: TestClient) -> None:
    corpo = _pagina(client)

    assert corpo["titolo"] == "Non hai ancora nessuna regola."
    assert corpo["regoleAttive"] == []
    assert corpo["stats"] == {
        "attive": 0,
        "daApprovare": 0,
        "scattateSettimana": 0,
        "inPausa": 0,
    }


def test_i_tre_tipi_di_trigger_che_esistono_davvero(client: TestClient) -> None:
    """`pattern` è il quarto di §8.10 e non compare: sarà delle auto-proposte, e
    mostrarlo prometterebbe una cosa che non si può scegliere."""
    tipi = [t["tipo"] for t in _pagina(client)["tipiTrigger"]]
    assert tipi == ["orario", "prima_evento", "dopo_evento"]


def test_una_regola_scritta_si_vede_subito(client: TestClient, modello: RouterFinto) -> None:
    _scrivi(client, modello)

    corpo = _pagina(client)

    (riga,) = corpo["regoleAttive"]
    assert riga["nome"] == "prendi la creatina"
    # La stessa frase del promemoria: sta nel dominio, in un posto solo.
    assert riga["descrizione"] == "tutti i giorni alle 19:00"
    assert riga["stato"] == "attiva"
    assert "attenuata" not in riga
    assert corpo["titolo"] == "1 regola attiva."
    assert corpo["stats"]["attive"] == 1


# — pausa e ritorno —


def test_mettere_in_pausa_e_rimettere_in_piedi(client: TestClient, modello: RouterFinto) -> None:
    regola_id = _scrivi(client, modello)

    risposta = client.patch(f"/api/regole/{regola_id}", json={"stato": "pausa"})

    assert risposta.status_code == 200
    assert risposta.json()["stato"] == "pausa"
    # Resta nella stessa lista, più in sordina: è lì, ma non fa niente.
    corpo = _pagina(client)
    (riga,) = corpo["regoleAttive"]
    assert riga["attenuata"] is True
    assert corpo["stats"] == {
        "attive": 0,
        "daApprovare": 0,
        "scattateSettimana": 0,
        "inPausa": 1,
    }
    assert corpo["titolo"] == "Le tue regole sono tutte in pausa."

    assert client.patch(f"/api/regole/{regola_id}", json={"stato": "attiva"}).status_code == 200
    assert _pagina(client)["stats"]["attive"] == 1


def test_una_regola_che_non_esiste(client: TestClient) -> None:
    assert client.patch("/api/regole/999", json={"stato": "pausa"}).status_code == 404
    assert client.post("/api/regole/999/scarta").status_code == 404


# — scartare —


def test_scartare_toglie_la_regola_e_la_lascia_nell_elenco_delle_scartate(
    client: TestClient, modello: RouterFinto
) -> None:
    """È la sola strada per **togliere** una regola: la pausa la lascia lì."""
    regola_id = _scrivi(client, modello)

    assert client.post(f"/api/regole/{regola_id}/scarta").status_code == 204

    corpo = _pagina(client)
    assert corpo["regoleAttive"] == []
    assert [s["nome"] for s in corpo["scartate"]] == ["prendi la creatina"]


def test_una_scartata_non_torna_indietro(client: TestClient, modello: RouterFinto) -> None:
    """§8.10 promette che Custode non riproponga una regola scartata."""
    regola_id = _scrivi(client, modello)
    client.post(f"/api/regole/{regola_id}/scarta")

    risposta = client.patch(f"/api/regole/{regola_id}", json={"stato": "attiva"})

    assert risposta.status_code == 409


def test_una_scartata_smette_di_scattare(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    """Il controllo che conta: la pagina dice una cosa e il worker ne fa un'altra
    è esattamente il difetto che questo progetto ha già avuto una volta."""
    regola_id = _scrivi(client, modello)
    client.post(f"/api/regole/{regola_id}/scarta")

    with connessione(db_path) as conn:
        assert dom.attive(conn) == []


# — approvare, che non ha ancora niente da approvare —


def test_approvare_una_regola_gia_attiva_e_409(client: TestClient, modello: RouterFinto) -> None:
    """Approvare una cosa già attiva non vuol dire niente: la rotta serve alle
    proposte, non alle regole che hai scritto tu."""
    regola_id = _scrivi(client, modello)

    assert client.post(f"/api/regole/{regola_id}/approva").status_code == 409


# — l'attività della settimana —


def test_l_attivita_arriva_dal_registro_degli_scatti(
    client: TestClient, modello: RouterFinto, db_path: Path, ora: datetime
) -> None:
    """Il conto non ha un registro suo: è la stessa tabella in cui il worker
    segna ogni scatto per non ripetersi, quindi il numero è ciò che ti è
    arrivato davvero."""
    regola_id = _scrivi(client, modello)
    with connessione(db_path) as conn:
        for giorno in range(3):
            segna_eseguito(
                conn,
                dom.nome_job(int(regola_id)),
                f"scatto-{giorno}",
                ora - timedelta(hours=giorno),
            )

    corpo = _pagina(client)

    assert corpo["stats"]["scattateSettimana"] == 3
    assert corpo["attivitaSettimana"] == [{"nome": "prendi la creatina", "conteggio": 3}]
    assert "attivitaNota" not in corpo


def test_senza_scatti_la_pagina_dice_perche_e_vuota(
    client: TestClient, modello: RouterFinto
) -> None:
    _scrivi(client, modello)

    corpo = _pagina(client)

    assert corpo["attivitaSettimana"] == []
    assert corpo["attivitaNota"] == "Nessuna delle tue regole è scattata da lunedì."


def test_senza_regole_non_c_e_nessuna_nota_da_dare(client: TestClient) -> None:
    """Due vuoti diversi: «non ne hai scritte» lo dice già il titolo."""
    assert "attivitaNota" not in _pagina(client)


# — le proposte, che adesso si riempiono (§8.10) —


def _proponi(db_path: Path, ora: datetime, **campi: Any) -> int:
    """Una proposta come la scrive il job, dalla strada vera del dominio."""
    with connessione(db_path) as conn:
        proposta = dom.crea_da_evento(
            conn,
            trigger=dom.Trigger.DOPO_EVENTO,
            tipo_evento="palestra",
            minuti=0,
            messaggio=campi.get("messaggio", "prendi la creatina"),
            creata_il=campi.get("creata_il", ora),
            origine=dom.Origine.IA,
            stato=dom.Stato.PROPOSTA,
            confidenza=campi.get("confidenza", dom.Confidenza.ALTA),
            motivazione="15 giornate con palestra su 16, e quasi mai negli altri giorni.",
        )
        return proposta.id


def test_una_proposta_arriva_in_pagina_con_tutto_quello_che_serve_a_decidere(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    """Cosa dirà, quando scatterebbe, quanto ci crede e perché: senza uno di
    questi, «Approva» è un bottone da premere al buio."""
    _proponi(db_path, ora)

    corpo = _pagina(client)

    assert len(corpo["proposte"]) == 1
    proposta = corpo["proposte"][0]
    assert proposta["testo"] == "prendi la creatina"
    assert proposta["triggerTipo"] == "dopo_evento"
    assert proposta["confidenza"] == "alta"
    assert "15 giornate" in proposta["motivazione"]
    # La stessa frase che sta sotto una regola attiva e nel promemoria.
    assert proposta["descrizione"] == "appena finisce un impegno di tipo «palestra»"
    assert corpo["stats"]["daApprovare"] == 1
    # Una proposta non è ancora una regola: non conta fra le attive.
    assert corpo["stats"]["attive"] == 0
    assert corpo["regoleAttive"] == []


def test_approvare_una_proposta_la_rende_una_regola(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    """Il `409` di prima era la verità, non un difetto: adesso che una proposta
    esiste, la stessa rotta funziona."""
    proposta_id = _proponi(db_path, ora)

    risposta = client.post(f"/api/regole/{proposta_id}/approva")

    assert risposta.status_code == 200
    assert risposta.json()["stato"] == "attiva"
    corpo = _pagina(client)
    assert corpo["proposte"] == []
    assert corpo["stats"]["attive"] == 1
    assert corpo["regoleAttive"][0]["nome"] == "prendi la creatina"


def test_scartare_una_proposta_la_manda_fra_le_scartate(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    """Ed è lì che resta: §8.10 promette che Custode non la riproponga, e
    mantenerlo richiede che la riga non sparisca."""
    proposta_id = _proponi(db_path, ora)

    assert client.post(f"/api/regole/{proposta_id}/scarta").status_code == 204

    corpo = _pagina(client)
    assert corpo["proposte"] == []
    assert [s["nome"] for s in corpo["scartate"]] == ["prendi la creatina"]
    # E non torna indietro.
    assert client.post(f"/api/regole/{proposta_id}/approva").status_code == 409


def test_una_proposta_da_sola_non_fa_dire_che_le_regole_non_scattano(
    client: TestClient, db_path: Path, ora: datetime
) -> None:
    """Trovato guidando la pagina vera, non dai test.

    Con una sola proposta la pagina diceva insieme «Non hai ancora nessuna
    regola» e «Nessuna delle tue regole è scattata da lunedì»: il motore fermo
    travestito da motore che gira a vuoto. Una proposta non è mai stata attiva,
    quindi non può non essere scattata.
    """
    _proponi(db_path, ora)

    corpo = _pagina(client)

    # Il titolo nomina la domanda che aspetta: dire «non hai ancora nessuna
    # regola» sopra un «da approvare: 1» lasciava la pagina a contraddirsi.
    assert corpo["titolo"] == "Custode ti propone una regola."
    assert "attivitaNota" not in corpo


def test_una_regola_vera_che_non_e_scattata_lo_dice_ancora(
    client: TestClient, modello: RouterFinto, db_path: Path, ora: datetime
) -> None:
    """L'altro verso: la nota serve, e non deve sparire insieme al difetto."""
    _scrivi(client, modello)
    _proponi(db_path, ora)

    assert _pagina(client)["attivitaNota"] == "Nessuna delle tue regole è scattata da lunedì."


def test_con_delle_regole_attive_il_titolo_resta_il_loro(
    client: TestClient, modello: RouterFinto, db_path: Path, ora: datetime
) -> None:
    """La proposta la conta già la barra dei numeri: il titolo dice lo stato
    delle cose, e le regole che hai sono quello."""
    _scrivi(client, modello)
    _proponi(db_path, ora)

    corpo = _pagina(client)

    assert corpo["titolo"] == "1 regola attiva."
    assert corpo["stats"]["daApprovare"] == 1
