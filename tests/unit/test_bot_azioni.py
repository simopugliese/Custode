"""Codifica/decodifica dei `callback_data` dei bottoni inline."""

from __future__ import annotations

import pytest

from custode_bot import azioni


def test_andata_e_ritorno() -> None:
    dato = azioni.task_fatto(12, "oggi")
    letta = azioni.leggi(dato)
    assert letta.dominio == "t"
    assert letta.nome == "fatto"
    assert letta.argomento == "12"
    assert letta.vista == "oggi"


@pytest.mark.parametrize(
    "dato",
    [
        azioni.task_fatto(1, "task"),
        azioni.task_rinvia(1, "task"),
        azioni.task_scadenza(1, "domani"),
        azioni.voce_presa(1, "lista"),
        azioni.svuota(True),
        azioni.svuota(False),
    ],
)
def test_ogni_azione_sta_nel_limite_di_telegram(dato: str) -> None:
    # Telegram taglia i callback_data oltre i 64 byte: meglio accorgersene qui.
    assert len(dato.encode("utf-8")) <= 64
    azioni.leggi(dato)  # e resta rileggibile


@pytest.mark.parametrize("dato", ["", "boh", "t:fatto:1", "z:fatto:1:t", "t:fatto:1:zzz"])
def test_dati_non_validi(dato: str) -> None:
    with pytest.raises(azioni.AzioneNonValida):
        azioni.leggi(dato)
