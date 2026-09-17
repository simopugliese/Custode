"""Scrivere una regola a parole (§8.10), dallo stesso canale del bot.

`crea_regola` è un'azione dell'interprete come le altre, quindi arriva insieme
gratis da Telegram **e** da ogni barra «A Custode» della dashboard: qui si prova
il percorso vero — messaggio, interprete, dominio, database — invece di chiamare
il dominio a mano.

Il modello è finto, come in tutti i test del progetto: quello che si prova non è
che DeepSeek capisca la frase, è che l'intenzione che produce diventi la regola
giusta, e che un'intenzione a metà non diventi una regola sbagliata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from custode_core.db import connessione
from custode_core.dominio import regole as dom
from tests.integration.conftest import RouterFinto

pytestmark = pytest.mark.integration


def _manda(client: TestClient, testo: str = "una cosa") -> Any:
    return client.post("/api/assistente/messaggio", json={"testo": testo})


def _regole(db_path: Path) -> list[dom.Regola]:
    with connessione(db_path) as conn:
        return dom.elenco(conn)


# — il caso normale —


def test_una_regola_a_orario_scritta_a_parole(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": "prendi la creatina",
            "regola_trigger": "orario",
            "regola_ora": "19:00",
        }
    )

    risposta = _manda(client, "ricordami la creatina tutti i giorni alle 19")

    # La conferma ripete cosa ha capito: una regola sbagliata si vedrebbe
    # altrimenti solo la prima volta che scatta, che può essere fra una settimana.
    assert risposta.json()["risposteLabel"] == [
        "Regola attiva: prendi la creatina — tutti i giorni alle 19:00"
    ]
    (regola,) = _regole(db_path)
    assert regola.stato is dom.Stato.ATTIVA
    assert regola.ora == "19:00"
    assert regola.giorni == dom.TUTTI_I_GIORNI


def test_una_regola_solo_di_domenica(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    """È il segnaposto scritto nella barra della pagina Regole."""
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": "cosa vuoi fare la settimana prossima?",
            "regola_trigger": "orario",
            "regola_ora": "21:00",
            "regola_giorni": [7],
        }
    )

    risposta = _manda(client, "ogni domenica sera chiedimi cosa voglio fare")

    assert "la domenica alle 21:00" in risposta.json()["risposteLabel"][0]
    (regola,) = _regole(db_path)
    assert regola.giorni == (7,)


def test_una_regola_agganciata_a_un_tipo_di_impegno(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": "porta il portatile",
            "regola_trigger": "prima_evento",
            "regola_tipo_evento": "lezione",
            "regola_minuti": 30,
        }
    )

    risposta = _manda(client, "mezz'ora prima di lezione dimmi di prendere il portatile")

    assert "30 minuti prima di un impegno «lezione»" in risposta.json()["risposteLabel"][0].replace(
        "di tipo ", ""
    )
    (regola,) = _regole(db_path)
    assert regola.trigger is dom.Trigger.PRIMA_EVENTO
    assert regola.tipo_evento == "lezione"


def test_il_modello_riceve_i_tipi_di_impegno_esistenti(
    client: TestClient, modello: RouterFinto
) -> None:
    """Senza l'elenco nel contesto, il modello inventerebbe uno slug plausibile
    («universita») che la chiave esterna rifiuterebbe."""
    _manda(client, "una cosa qualunque")

    contesto = modello.messaggi_visti[0]
    assert "Tipi di impegno del calendario:" in contesto
    assert "lezione" in contesto
    assert "palestra" in contesto


# — quando il modello capisce a metà —


def test_una_regola_senza_quando_non_si_crea(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    """Fra «alle 19» e «prima di lezione» non si indovina: sono due cose diverse."""
    modello.interpreta_come({"azione": "crea_regola", "titolo": "prendi la creatina"})

    risposta = _manda(client)

    assert risposta.json()["risposteLabel"] == ["Non ho capito quando dovrei dirtelo."]
    assert _regole(db_path) == []


def test_un_ora_valida_senza_trigger_non_diventa_una_regola_a_orario(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    """Il caso che conta davvero fra quelli «a metà».

    Con un'ora storta il risultato è lo stesso comunque; qui l'ora è buona e
    manca solo il tipo di trigger, e indovinare «orario» creerebbe in silenzio
    una regola che nessuno ha chiesto — che poi scatta ogni giorno per sempre.
    """
    modello.interpreta_come(
        {"azione": "crea_regola", "titolo": "prendi la creatina", "regola_ora": "19:00"}
    )

    risposta = _manda(client)

    assert risposta.json()["risposteLabel"] == ["Non ho capito quando dovrei dirtelo."]
    assert _regole(db_path) == []


def test_una_regola_senza_messaggio_non_si_crea(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    modello.interpreta_come(
        {"azione": "crea_regola", "titolo": "", "regola_trigger": "orario", "regola_ora": "19:00"}
    )

    risposta = _manda(client)

    assert risposta.json()["risposteLabel"] == ["Non ho capito cosa dovrei ricordarti."]
    assert _regole(db_path) == []


def test_un_orario_storto_non_si_crea(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": "x",
            "regola_trigger": "orario",
            "regola_ora": "venticinque",
        }
    )

    assert _manda(client).json()["risposteLabel"] == ["Non ho capito quando dovrei dirtelo."]
    assert _regole(db_path) == []


def test_un_tipo_di_impegno_inventato_lo_dice_e_spiega_cosa_fare(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    """La chiave esterna della 011 lo impedisce; qui si prova che il no sia
    una risposta utile invece di un errore tecnico."""
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": "x",
            "regola_trigger": "prima_evento",
            "regola_tipo_evento": "universita",
            "regola_minuti": 30,
        }
    )

    (frase,) = _manda(client).json()["risposteLabel"]

    assert "«universita»" in frase
    assert "pagina Calendario" in frase
    assert _regole(db_path) == []


def test_giorni_inventati_si_scartano_senza_perdere_la_regola(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    """Un giorno fuori scala in mezzo a due buoni non deve portarsi via tutto."""
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": "x",
            "regola_trigger": "orario",
            "regola_ora": "19:00",
            "regola_giorni": [1, 9, 4],
        }
    )

    _manda(client)

    (regola,) = _regole(db_path)
    assert regola.giorni == (1, 4)


# — un messaggio può chiedere due cose —


def test_una_regola_e_un_task_nello_stesso_messaggio(
    client: TestClient, modello: RouterFinto, db_path: Path
) -> None:
    """L'azione nuova non rompe la lista: §8.1 vuole che un messaggio possa
    chiedere più cose, e una regola è una di quelle."""
    modello.interpreta_come(
        {
            "azione": "crea_regola",
            "titolo": "prendi la creatina",
            "regola_trigger": "orario",
            "regola_ora": "19:00",
        },
        {"azione": "aggiungi_task", "titolo": "Chiamare l'officina"},
    )

    frasi = _manda(client).json()["risposteLabel"]

    assert len(frasi) == 2
    assert len(_regole(db_path)) == 1
    pagina = client.get("/api/task").json()
    titoli = [t["titolo"] for s in pagina["sezioni"] for t in s["task"]]
    assert titoli == ["Chiamare l'officina"]
