"""Il tipo di un evento proposto dal modello (§6, §8.10).

Il modello è finto: qui si verifica l'elenco numerato che riceve e — soprattutto
— come si rilegge quello che risponde. È la parte delicata, perché un tag letto
per posizione invece che per numero finirebbe sull'evento sbagliato senza che
niente lo segnali: in tabella un tag vale l'altro.
"""

from __future__ import annotations

from typing import Any

import pytest

from custode_core.dominio.calendario import Tipo
from custode_router import calendario as router_calendario
from custode_router.compiti import Compito
from custode_router.errori import RispostaNonValida


class RouterFinto:
    def __init__(self, risposta: dict[str, Any]) -> None:
        self.risposta = risposta
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        return self.risposta


TITOLI = ["Analisi Matematica I", "Palestra", "Treno per Napoli"]


def _tag(
    risposta: dict[str, Any], titoli: list[str] | None = None
) -> tuple[list[router_calendario.Proposta], RouterFinto]:
    router = RouterFinto(risposta)
    proposte = router_calendario.tag_per(
        router,  # type: ignore[arg-type]
        TITOLI if titoli is None else titoli,
    )
    return proposte, router


def _risposta(*coppie: tuple[int, str]) -> dict[str, Any]:
    return {"tag": [{"n": n, "tipo": tipo} for n, tipo in coppie]}


# — il prompt —


def test_il_compito_e_quello_di_sezione_6() -> None:
    """Chi chiama nomina il compito, mai il modello."""
    _, router = _tag(_risposta((1, "lezione"), (2, "palestra"), (3, "viaggio")))
    assert router.chiamate[0]["compito"] is Compito.TAG_CALENDARIO


def test_gli_eventi_arrivano_numerati() -> None:
    """Il numero è ciò su cui si rilegge la risposta: deve essere nel prompt."""
    prompt = router_calendario.componi_prompt(TITOLI)
    assert "1. Analisi Matematica I" in prompt
    assert "2. Palestra" in prompt
    assert "3. Treno per Napoli" in prompt


def test_un_titolo_su_piu_righe_non_diventa_due_eventi() -> None:
    """In un elenco numerato un a capo sembrerebbe un evento in più."""
    prompt = router_calendario.componi_prompt(["Lezione\ndi\tAnalisi", "Palestra"])
    assert prompt.splitlines()[1:] == ["1. Lezione di Analisi", "2. Palestra"]


def test_un_titolo_vuoto_si_dice_a_parole() -> None:
    """Una riga numerata e vuota sembrerebbe un errore di composizione."""
    prompt = router_calendario.componi_prompt(["   ", "Palestra"])
    assert f"1. {router_calendario.SENZA_TITOLO}" in prompt


def test_un_titolo_fluviale_viene_accorciato() -> None:
    prompt = router_calendario.componi_prompt(["a" * 500])
    assert "a" * router_calendario.MAX_CARATTERI_TITOLO in prompt
    assert "a" * (router_calendario.MAX_CARATTERI_TITOLO + 1) not in prompt


def test_i_quattro_tipi_sono_quelli_del_dominio() -> None:
    """Lo schema e `Tipo` non devono poter divergere in silenzio."""
    voci = router_calendario.SCHEMA_TAG["properties"]["tag"]["items"]
    assert voci["properties"]["tipo"]["enum"] == ["lezione", "palestra", "viaggio", "altro"]


# — come si rilegge la risposta —


def test_ogni_titolo_riceve_il_suo_tipo() -> None:
    proposte, _ = _tag(_risposta((1, "lezione"), (2, "palestra"), (3, "viaggio")))
    assert [p.tipo for p in proposte] == [Tipo.LEZIONE, Tipo.PALESTRA, Tipo.VIAGGIO]
    assert all(p.letta for p in proposte)


def test_la_risposta_si_legge_per_numero_non_per_ordine() -> None:
    """Un modello che risponde in ordine sparso non deve spostare i tag."""
    proposte, _ = _tag(_risposta((3, "viaggio"), (1, "lezione"), (2, "palestra")))
    assert [p.tipo for p in proposte] == [Tipo.LEZIONE, Tipo.PALESTRA, Tipo.VIAGGIO]


def test_una_voce_saltata_non_fa_slittare_le_altre() -> None:
    """È la ragione per cui la risposta porta il numero e non solo il tipo.

    Letta per posizione, qui il «viaggio» finirebbe sulla palestra.
    """
    proposte, _ = _tag(_risposta((1, "lezione"), (3, "viaggio")))
    assert [p.tipo for p in proposte] == [Tipo.LEZIONE, Tipo.ALTRO, Tipo.VIAGGIO]
    assert [p.letta for p in proposte] == [True, False, True]


def test_un_tipo_inventato_diventa_altro_di_ripiego() -> None:
    """«sport» non è uno dei quattro: quella serie esce comunque dalla coda.

    Lasciarla dentro vorrebbe dire richiamare il modello su quel titolo ad ogni
    sincronizzazione, per sempre.
    """
    proposte, _ = _tag(_risposta((1, "lezione"), (2, "sport"), (3, "viaggio")))
    assert proposte[1] == router_calendario.Proposta(tipo=Tipo.ALTRO, letta=False)


def test_le_maiuscole_non_fanno_perdere_una_classificazione_giusta() -> None:
    proposte, _ = _tag(_risposta((1, " Lezione "), (2, "PALESTRA"), (3, "viaggio")))
    assert [p.tipo for p in proposte] == [Tipo.LEZIONE, Tipo.PALESTRA, Tipo.VIAGGIO]
    assert all(p.letta for p in proposte)


@pytest.mark.parametrize(
    "voce",
    [
        {"n": 0, "tipo": "lezione"},
        {"n": 4, "tipo": "lezione"},
        {"n": -1, "tipo": "lezione"},
        {"n": "2", "tipo": "lezione"},
        {"n": True, "tipo": "lezione"},
        {"tipo": "lezione"},
        {"n": 2},
        {"n": 2, "tipo": None},
        "palestra",
    ],
)
def test_una_voce_storta_non_travolge_le_altre(voce: Any) -> None:
    """Un numero fuori elenco o assente vale come voce mancante, non come errore."""
    proposte, _ = _tag({"tag": [{"n": 1, "tipo": "lezione"}, voce]})
    assert proposte[0].tipo is Tipo.LEZIONE
    assert [p.letta for p in proposte] == [True, False, False]


def test_il_primo_tipo_su_un_numero_vince() -> None:
    """Un ripensamento del modello non è più credibile della prima risposta."""
    proposte, _ = _tag(_risposta((1, "lezione"), (1, "palestra"), (2, "palestra"), (3, "altro")))
    assert proposte[0].tipo is Tipo.LEZIONE


def test_se_non_si_legge_niente_e_un_guasto_non_una_classificazione() -> None:
    """Tre serie tutte «altro» per una risposta storta le seppellirebbe.

    Sollevare invece lascia la coda intatta: al sync dopo si riprova.
    """
    with pytest.raises(RispostaNonValida):
        _tag({"errore": "non ho capito"})
    with pytest.raises(RispostaNonValida):
        _tag({"tag": []})
    with pytest.raises(RispostaNonValida):
        _tag(_risposta((9, "lezione")))


def test_senza_titoli_non_si_chiama_nessuno() -> None:
    """Una chiamata a vuoto si pagherebbe comunque."""
    proposte, router = _tag(_risposta((1, "lezione")), titoli=[])
    assert proposte == []
    assert router.chiamate == []


def test_oltre_il_tetto_la_chiamata_non_parte() -> None:
    """Il tetto sta nella risposta: oltre, arriverebbe troncata e illeggibile."""
    troppi = ["Lezione"] * (router_calendario.MAX_TITOLI_PER_CHIAMATA + 1)
    with pytest.raises(ValueError, match="massimo"):
        _tag(_risposta((1, "lezione")), titoli=troppi)
