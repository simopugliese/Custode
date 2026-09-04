"""Il report narrativo delle abitudini (§6, §8.6).

Il modello è sostituito da un finto: qui si verifica il prompt che riceve — i
numeri devono arrivargli già calcolati, perché §8.6 li vuole fatti in codice —
e la validazione di ciò che risponde, che è l'unica difesa fra una proposta
inventata e una riga sul database.
"""

from __future__ import annotations

from typing import Any

import pytest

from custode_router import abitudini as router_abitudini
from custode_router.compiti import Compito
from custode_router.errori import (
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)


class RouterFinto:
    def __init__(self, risposta: dict[str, Any]) -> None:
        self.risposta = risposta
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        return self.risposta


ABITUDINI = [
    {"nome": "Palestra", "target": 3, "fatte": 2, "attese": 3.0, "aderenza": 67, "striscia": 1},
    {"nome": "Lettura", "target": 5, "fatte": 5, "attese": 5.0, "aderenza": 100, "striscia": 5},
]


def _report(risposta: dict[str, Any]) -> tuple[router_abitudini.Rapporto, RouterFinto]:
    router = RouterFinto(risposta)
    rapporto = router_abitudini.report(
        router,  # type: ignore[arg-type]
        periodo="settimanale",
        intervallo="Lun 31 agosto – Dom 6 settembre",
        abitudini=ABITUDINI,
        diario=["Giornata in biblioteca fino a tardi."],
        spese="120,00 € in 8 spese, soprattutto Alimentari",
    )
    return rapporto, router


# — il prompt —


def test_i_numeri_arrivano_gia_calcolati() -> None:
    """§8.6 li vuole in codice: il modello li deve solo raccontare."""
    _, router = _report({"report": "Settimana solida."})
    prompt = router.chiamate[0]["utente"]
    assert "Palestra: obiettivo 3 volte a settimana, fatta 2 volte su 3.0 attese (67%" in prompt
    assert "striscia attuale 5 giorni" in prompt


def test_il_prompt_porta_diario_e_spese() -> None:
    """È l'incrocio a rendere utile il report, non l'elenco delle percentuali."""
    _, router = _report({"report": "x"})
    prompt = router.chiamate[0]["utente"]
    assert "biblioteca" in prompt
    assert "120,00 €" in prompt


def test_senza_diario_e_spese_il_prompt_lo_dice() -> None:
    """Un campo assente non deve sembrare un dato mancante da inventare."""
    prompt = router_abitudini.componi_prompt(
        periodo="mensile", intervallo="settembre", abitudini=[], diario=[], spese=None
    )
    assert "nessuna abitudine attiva" in prompt
    assert "Nel diario non c'è niente" in prompt
    assert "Spese del periodo: nessuna." in prompt


def test_il_compito_e_quello_di_claude() -> None:
    """§6: «sintesi che incrocia più segnali» è una riga di Claude."""
    _, router = _report({"report": "x"})
    assert router.chiamate[0]["compito"] is Compito.REPORT_ABITUDINI


# — la risposta —


def test_un_report_senza_proposta_e_il_caso_normale() -> None:
    rapporto, _ = _report({"report": "Settimana solida.", "proposta_abitudine": ""})
    assert rapporto.testo == "Settimana solida."
    assert rapporto.proposta is None


def test_una_proposta_valida_passa() -> None:
    rapporto, _ = _report(
        {
            "report": "x",
            "proposta_abitudine": "Palestra",
            "proposta_target": 2,
            "proposta_motivazione": "sei a 2,1 di media da sei settimane",
        }
    )
    assert rapporto.proposta == router_abitudini.PropostaTarget(
        abitudine="Palestra",
        target_proposto=2,
        motivazione="sei a 2,1 di media da sei settimane",
    )


def test_una_proposta_su_un_abitudine_inventata_si_scarta() -> None:
    """Finirebbe sul database come una riga che non si può nemmeno accettare."""
    rapporto, _ = _report(
        {
            "report": "x",
            "proposta_abitudine": "Chitarra",
            "proposta_target": 2,
            "proposta_motivazione": "perché sì",
        }
    )
    assert rapporto.proposta is None


@pytest.mark.parametrize("target", [0, 8, -1, "due", True, None])
def test_un_target_fuori_scala_si_scarta(target: Any) -> None:
    rapporto, _ = _report(
        {
            "report": "x",
            "proposta_abitudine": "Palestra",
            "proposta_target": target,
            "proposta_motivazione": "perché",
        }
    )
    assert rapporto.proposta is None


def test_una_proposta_senza_motivazione_si_scarta() -> None:
    """Senza il perché non è una proposta: è un bottone «Accetta» muto."""
    rapporto, _ = _report(
        {
            "report": "x",
            "proposta_abitudine": "Palestra",
            "proposta_target": 2,
            "proposta_motivazione": "   ",
        }
    )
    assert rapporto.proposta is None


def test_il_nome_si_riallinea_a_quello_vero() -> None:
    """Il modello può cambiare le maiuscole: il nome salvato resta il nostro."""
    rapporto, _ = _report(
        {
            "report": "x",
            "proposta_abitudine": "palestra",
            "proposta_target": 4,
            "proposta_motivazione": "la superi sempre",
        }
    )
    assert rapporto.proposta is not None
    assert rapporto.proposta.abitudine == "Palestra"


def test_un_report_vuoto_e_un_errore() -> None:
    with pytest.raises(RispostaNonValida):
        _report({"report": "   "})


def test_un_report_lunghissimo_viene_tagliato() -> None:
    """Il limite è nel prompt, ma un prompt è una richiesta, non un vincolo."""
    rapporto, _ = _report({"report": "a" * 5000})
    assert len(rapporto.testo) == router_abitudini.MAX_CARATTERI_REPORT


# — errori raccontati in italiano —


@pytest.mark.parametrize(
    ("errore", "atteso"),
    [
        (ProviderNonConfigurato("x"), "chiave di Claude"),
        (ProviderNonRaggiungibile("x"), "prossimo giro"),
        (RuntimeError("x"), "Non sono riuscito"),
    ],
)
def test_messaggio_errore(errore: Exception, atteso: str) -> None:
    assert atteso in router_abitudini.messaggio_errore(errore)
