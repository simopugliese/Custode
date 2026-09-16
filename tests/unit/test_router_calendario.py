"""Il tipo di un evento proposto dal modello (§6, §8.10).

Il modello è finto: qui si verifica l'elenco numerato che riceve e — soprattutto
— come si rilegge quello che risponde. È la parte delicata, perché un tag letto
per posizione invece che per numero finirebbe sull'evento sbagliato senza che
niente lo segnali: in tabella un tag vale l'altro.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from custode_core.dominio.calendario import Tag
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


def _tipo(slug: str, nome: str, descrizione: str = "roba.") -> Tag:
    return Tag(
        id=0,
        slug=slug,
        nome=nome,
        descrizione=descrizione,
        di_sistema=slug == "altro",
        attivo=True,
        creato_il=datetime(2026, 9, 15, 8, 0),
    )


# I quattro di sempre, come li semina la migrazione 009: da qui in poi sono un
# dato che entra, non una costante di questo modulo.
TIPI = [
    _tipo("lezione", "Lezione", "l'università: lezioni, laboratori, esami."),
    _tipo("palestra", "Palestra", "allenamento e sport."),
    _tipo("viaggio", "Viaggio", "treni, voli, trasferte."),
    _tipo("altro", "Altro", "tutto il resto."),
]


def _tag(
    risposta: dict[str, Any],
    titoli: list[str] | None = None,
    tipi: list[Tag] | None = None,
) -> tuple[list[router_calendario.Proposta], RouterFinto]:
    router = RouterFinto(risposta)
    proposte = router_calendario.tag_per(
        router,  # type: ignore[arg-type]
        TITOLI if titoli is None else titoli,
        TIPI if tipi is None else tipi,
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


def test_l_enum_sono_i_tipi_che_esistono_adesso() -> None:
    """Lo schema si ricostruisce ad ogni chiamata, coi tag che ci sono."""
    voci = router_calendario.schema_tag(TIPI)["properties"]["tag"]["items"]
    assert voci["properties"]["tipo"]["enum"] == ["lezione", "palestra", "viaggio", "altro"]

    miei = [*TIPI, _tipo("spesa", "Spesa", "fare la spesa al supermercato.")]
    voci = router_calendario.schema_tag(miei)["properties"]["tag"]["items"]
    assert voci["properties"]["tipo"]["enum"] == [
        "lezione",
        "palestra",
        "viaggio",
        "altro",
        "spesa",
    ]


def test_il_prompt_porta_gli_slug_con_le_loro_descrizioni() -> None:
    """È la descrizione a fare il lavoro, non il nome del tipo."""
    prompt = router_calendario.sistema(
        [*TIPI, _tipo("spesa", "Spesa", "il supermercato, non le uscite di denaro in generale.")]
    )
    assert "- **spesa** — il supermercato, non le uscite di denaro in generale." in prompt
    assert "- **lezione** — l'università: lezioni, laboratori, esami." in prompt
    # Il ripiego si nomina per slug: è la parola che il modello deve scrivere.
    assert "Nel dubbio **altro**" in prompt


def test_il_prompt_dice_il_nome_nuovo_quando_rinomini() -> None:
    """Rinominare un tipo cambia ciò che il modello legge, non il suo slug.

    Lo slug resta `palestra` perché è l'identificatore scritto negli eventi; ciò
    che il modello legge per decidere è la descrizione, ed è lì che si aggiusta
    il tiro.
    """
    rinominato = _tipo("palestra", "Allenamento", "allenamento, corsa, piscina, partite.")
    prompt = router_calendario.sistema([rinominato, TIPI[-1]])
    assert "- **palestra** — allenamento, corsa, piscina, partite." in prompt
    assert "Allenamento" not in prompt


def test_con_un_tipo_solo_non_si_chiama_nessuno() -> None:
    """Ogni risposta possibile sarebbe «altro»: la chiamata si pagherebbe a vuoto."""
    with pytest.raises(ValueError, match="almeno"):
        _tag(_risposta((1, "altro")), tipi=[TIPI[-1]])


# — come si rilegge la risposta —


def test_ogni_titolo_riceve_il_suo_tipo() -> None:
    proposte, _ = _tag(_risposta((1, "lezione"), (2, "palestra"), (3, "viaggio")))
    assert [p.tipo for p in proposte] == ["lezione", "palestra", "viaggio"]
    assert all(p.letta for p in proposte)


def test_la_risposta_si_legge_per_numero_non_per_ordine() -> None:
    """Un modello che risponde in ordine sparso non deve spostare i tag."""
    proposte, _ = _tag(_risposta((3, "viaggio"), (1, "lezione"), (2, "palestra")))
    assert [p.tipo for p in proposte] == ["lezione", "palestra", "viaggio"]


def test_una_voce_saltata_non_fa_slittare_le_altre() -> None:
    """È la ragione per cui la risposta porta il numero e non solo il tipo.

    Letta per posizione, qui il «viaggio» finirebbe sulla palestra.
    """
    proposte, _ = _tag(_risposta((1, "lezione"), (3, "viaggio")))
    assert [p.tipo for p in proposte] == ["lezione", "altro", "viaggio"]
    assert [p.letta for p in proposte] == [True, False, True]


def test_un_tipo_inventato_diventa_altro_di_ripiego() -> None:
    """«sport» non è uno dei tipi che esistono: quella serie esce comunque dalla coda.

    Lasciarla dentro vorrebbe dire richiamare il modello su quel titolo ad ogni
    sincronizzazione, per sempre.
    """
    proposte, _ = _tag(_risposta((1, "lezione"), (2, "sport"), (3, "viaggio")))
    assert proposte[1] == router_calendario.Proposta(tipo="altro", letta=False)


def test_le_maiuscole_non_fanno_perdere_una_classificazione_giusta() -> None:
    proposte, _ = _tag(_risposta((1, " Lezione "), (2, "PALESTRA"), (3, "viaggio")))
    assert [p.tipo for p in proposte] == ["lezione", "palestra", "viaggio"]
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
    assert proposte[0].tipo == "lezione"
    assert [p.letta for p in proposte] == [True, False, False]


def test_il_primo_tipo_su_un_numero_vince() -> None:
    """Un ripensamento del modello non è più credibile della prima risposta."""
    proposte, _ = _tag(_risposta((1, "lezione"), (1, "palestra"), (2, "palestra"), (3, "altro")))
    assert proposte[0].tipo == "lezione"


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
