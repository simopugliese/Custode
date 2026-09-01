"""Il riassunto del diario: instradamento, prompt, validazione della risposta.

Senza chiave non si può chiamare Claude davvero. Quello che si può verificare —
e che conta — è che il compito finisca su Claude come vuole §6, che il prompt
contenga il materiale e non altro, e che ogni modo in cui la risposta può
arrivare storta produca un errore comprensibile invece di una voce di diario
sbagliata.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from custode_router import diario
from custode_router.compiti import Compito, Provider, provider_per
from custode_router.errori import (
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)

GIORNO = date(2026, 8, 31)


class RouterFinto:
    def __init__(self, risposta: dict[str, Any] | None = None, errore: Exception | None = None):
        self.risposta = risposta or {"riassunto": "Hai studiato.", "tag": ["studio"]}
        self.errore = errore
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.risposta


def _riassumi(router: RouterFinto, grezzo: str = "materiale", **extra: Any) -> diario.Riassunto:
    return diario.riassumi(router, giorno=GIORNO, grezzo=grezzo, **extra)  # type: ignore[arg-type]


# — instradamento (§6) —


def test_il_riassunto_del_diario_va_a_claude() -> None:
    """La riga di §6: «qualità del linguaggio, sfumature»."""
    assert provider_per(Compito.RIASSUNTO_DIARIO) is Provider.CLAUDE


def test_nomina_il_compito_non_il_modello() -> None:
    router = RouterFinto()
    _riassumi(router)
    assert router.chiamate[0]["compito"] is Compito.RIASSUNTO_DIARIO


# — il prompt —


def test_il_prompt_porta_il_materiale_e_la_data() -> None:
    router = RouterFinto()
    _riassumi(router, "mattina in biblioteca\npoi palestra")

    utente = router.chiamate[0]["utente"]
    assert "mattina in biblioteca" in utente
    assert "poi palestra" in utente
    assert "2026-08-31" in utente


def test_il_prompt_porta_la_versione_gia_approvata_quando_c_e() -> None:
    """Aggiungere qualcosa a sera non deve far ripartire il riassunto da zero."""
    router = RouterFinto()
    _riassumi(router, "poi è successo altro", precedente="Prima versione approvata.")

    assert "Prima versione approvata." in router.chiamate[0]["utente"]


def test_senza_versione_precedente_il_prompt_non_ne_parla() -> None:
    router = RouterFinto()
    _riassumi(router)
    assert "già approvata" not in router.chiamate[0]["utente"]


def test_il_sistema_vieta_di_inventare() -> None:
    """È la regola che rende il diario affidabile: niente dedotto."""
    assert "Non inventare niente" in diario.SISTEMA
    assert "dandogli del tu" in diario.SISTEMA


def test_lo_schema_e_chiuso() -> None:
    """`additionalProperties: false` è ciò che structured outputs fa rispettare."""
    assert diario.SCHEMA_RIASSUNTO["additionalProperties"] is False
    assert set(diario.SCHEMA_RIASSUNTO["required"]) == {"riassunto", "tag"}


# — validazione della risposta —


def test_legge_riassunto_e_tag() -> None:
    esito = diario.leggi_riassunto({"riassunto": "  Hai studiato.  ", "tag": ["Studio", " "]})
    assert esito.testo == "Hai studiato."
    assert esito.tag == ["studio"]


@pytest.mark.parametrize("dati", [{}, {"riassunto": ""}, {"riassunto": "   ", "tag": []}])
def test_un_riassunto_vuoto_non_diventa_una_bozza(dati: dict[str, Any]) -> None:
    """Lo schema garantisce la forma, non che il campo sia pieno."""
    with pytest.raises(RispostaNonValida):
        diario.leggi_riassunto(dati)


def test_tag_di_forma_sbagliata_non_fanno_fallire_il_riassunto() -> None:
    """Il testo è la cosa che conta: i tag sono un di più."""
    esito = diario.leggi_riassunto({"riassunto": "Hai studiato.", "tag": "studio"})
    assert esito.testo == "Hai studiato."
    assert esito.tag == []


def test_senza_materiale_non_si_chiama_nessuno() -> None:
    """Una chiamata a Claude per una giornata vuota è spesa buttata (§1)."""
    router = RouterFinto()
    with pytest.raises(diario.RiassuntoNonRiuscito):
        _riassumi(router, "   ")
    assert router.chiamate == []


# — cosa si dice all'utente quando il riassunto non arriva —


@pytest.mark.parametrize(
    ("errore", "atteso"),
    [
        (ProviderNonConfigurato("x"), "chiave di Claude"),
        (ProviderNonRaggiungibile("x"), "riprova fra poco"),
        (RispostaNonValida("x"), "materiale della giornata è salvo"),
    ],
)
def test_ogni_guasto_ha_la_sua_frase(errore: Exception, atteso: str) -> None:
    assert atteso in diario.messaggio_errore(errore)


def test_il_messaggio_rassicura_sul_materiale() -> None:
    """Il punto: un guasto del modello non deve far perdere ciò che hai detto."""
    for errore in (ProviderNonRaggiungibile("x"), RispostaNonValida("x")):
        testo = diario.messaggio_errore(errore)
        assert "salv" in testo
