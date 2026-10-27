"""La prosa del digest (§6, §8.13): il modello compone, il codice controlla.

Il modello è finto. Quello che conta è la guardia: un testo a cui manca un
orario o un titolo non è una composizione, è un fatto cambiato.
"""

from __future__ import annotations

from typing import Any

import pytest

from custode_router import digest
from custode_router.compiti import Compito
from custode_router.errori import RispostaNonValida

FATTI = ["09:00 Analisi", "Pioggia probabile (70%): porta l'ombrello."]
OBBLIGATORI = ["09:00", "Analisi", "Pioggia probabile (70%): porta l'ombrello."]


class RouterFinto:
    def __init__(self, risposta: dict[str, Any]) -> None:
        self.risposta = risposta
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Compito, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        return self.risposta


def test_il_prompt_elenca_i_fatti() -> None:
    prompt = digest.componi_prompt(FATTI)
    assert "- 09:00 Analisi" in prompt
    assert prompt.startswith("Fatti di oggi:")


def test_il_compito_e_il_digest_di_deepseek() -> None:
    router = RouterFinto(
        {"testo": "Alle 09:00 hai Analisi. Pioggia probabile (70%): porta l'ombrello."}
    )
    testo = digest.componi(router, FATTI, obbligatori=OBBLIGATORI)  # type: ignore[arg-type]
    assert router.chiamate[0]["compito"] is Compito.DIGEST_MATTUTINO
    assert "Analisi" in testo


def test_un_testo_buono_passa() -> None:
    testo = "Alle 09:00 hai Analisi. Pioggia probabile (70%): porta l'ombrello."
    assert digest.leggi_risposta({"testo": testo}, obbligatori=OBBLIGATORI) == testo


@pytest.mark.parametrize(
    "testo",
    [
        "",
        "Hai Analisi. Pioggia probabile (70%): porta l'ombrello.",  # manca l'orario
        "Alle 09:00 hai Analisi. Prendi un k-way.",  # la frase dell'ombrello è cambiata
        "Alle 09:00 hai Analisi. Pioggia probabile (70%): porta l'ombrello. " + "x" * 1300,
    ],
)
def test_un_testo_che_perde_un_fatto_o_e_troppo_lungo_si_rifiuta(testo: str) -> None:
    with pytest.raises(RispostaNonValida):
        digest.leggi_risposta({"testo": testo}, obbligatori=OBBLIGATORI)
