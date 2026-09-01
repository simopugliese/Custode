"""La rifusione del profilo: instradamento, prompt, validazione.

Il criterio che questi test difendono è quello di §8.4: il profilo si
**riscrive**, non si accoda — e quindi il modello deve ricevere sia la versione
attuale sia le novità, e la risposta va validata prima di diventare una nuova
versione.
"""

from __future__ import annotations

from typing import Any

import pytest

from custode_router import profilo
from custode_router.compiti import Compito, Provider, provider_per
from custode_router.errori import (
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)


class RouterFinto:
    def __init__(self, risposta: dict[str, Any] | None = None, errore: Exception | None = None):
        self.risposta = risposta or {
            "profilo": "Preferisce il backend.",
            "cambiamenti": ["aggiunta la preferenza per il backend"],
        }
        self.errore = errore
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.risposta


def _rifondi(router: RouterFinto, **extra: Any) -> tuple[str, list[str]]:
    argomenti: dict[str, Any] = {
        "profilo": None,
        "riepilogo": None,
        "candidati": ["Preferisce il backend"],
    }
    argomenti.update(extra)
    return profilo.rifondi(router, **argomenti)  # type: ignore[arg-type]


# — instradamento (§6) —


def test_la_rifusione_va_a_claude() -> None:
    """§6: «va integrato con giudizio, non concatenato» — non è un lavoro da
    modello economico."""
    assert provider_per(Compito.RIFUSIONE_PROFILO) is Provider.CLAUDE


def test_nomina_il_compito_non_il_modello() -> None:
    router = RouterFinto()
    _rifondi(router)
    assert router.chiamate[0]["compito"] is Compito.RIFUSIONE_PROFILO


# — il prompt —


def test_il_prompt_porta_il_profilo_attuale_e_le_novita() -> None:
    """Senza il vecchio non si può fondere: si può solo riscrivere da zero."""
    router = RouterFinto()
    _rifondi(
        router,
        profilo="Studia meglio la mattina.",
        riepilogo="Settimana passata sul capitolo 3.",
        candidati=["Preferisce il backend", "Si stanca col frontend"],
    )

    utente = router.chiamate[0]["utente"]
    assert "Studia meglio la mattina." in utente
    assert "Settimana passata sul capitolo 3." in utente
    assert "Preferisce il backend" in utente
    assert "Si stanca col frontend" in utente


def test_senza_profilo_il_prompt_lo_dice() -> None:
    router = RouterFinto()
    _rifondi(router)
    assert "non esiste ancora un profilo" in router.chiamate[0]["utente"].lower()


def test_il_sistema_vieta_l_accodamento_e_impone_di_tagliare() -> None:
    assert "Non è un accodamento" in profilo.SISTEMA
    assert "Taglia." in profilo.SISTEMA
    assert "Non inventare" in profilo.SISTEMA


def test_lo_schema_e_chiuso() -> None:
    assert profilo.SCHEMA_PROFILO["additionalProperties"] is False
    assert set(profilo.SCHEMA_PROFILO["required"]) == {"profilo", "cambiamenti"}


def test_senza_niente_di_nuovo_non_si_chiama_nessuno() -> None:
    """Rifondere senza novità produrrebbe la stessa versione, a pagamento (§1)."""
    router = RouterFinto()
    with pytest.raises(profilo.RifusioneNonRiuscita):
        _rifondi(router, profilo="Qualcosa.", candidati=[])
    assert router.chiamate == []


def test_il_solo_riepilogo_basta_a_giustificare_una_rifusione() -> None:
    router = RouterFinto()
    _rifondi(router, candidati=[], riepilogo="È successo questo.")
    assert len(router.chiamate) == 1


# — validazione —


def test_legge_profilo_e_cambiamenti() -> None:
    testo, cambiamenti = profilo.leggi_rifusione(
        {"profilo": "  Preferisce il backend.  ", "cambiamenti": ["aggiunto backend", " "]}
    )
    assert testo == "Preferisce il backend."
    assert cambiamenti == ["aggiunto backend"]


@pytest.mark.parametrize("dati", [{}, {"profilo": ""}, {"profilo": "   ", "cambiamenti": []}])
def test_un_profilo_vuoto_non_diventa_una_versione(dati: dict[str, Any]) -> None:
    with pytest.raises(RispostaNonValida):
        profilo.leggi_rifusione(dati)


def test_cambiamenti_di_forma_sbagliata_non_buttano_via_il_profilo() -> None:
    testo, cambiamenti = profilo.leggi_rifusione({"profilo": "Testo.", "cambiamenti": "boh"})
    assert testo == "Testo."
    assert cambiamenti == []


# — cosa si dice quando non si riesce —


@pytest.mark.parametrize(
    ("errore", "atteso"),
    [
        (ProviderNonConfigurato("x"), "chiave di Claude"),
        (ProviderNonRaggiungibile("x"), "resta com'era"),
        (RispostaNonValida("x"), "non si perdono"),
    ],
)
def test_ogni_guasto_ha_la_sua_frase(errore: Exception, atteso: str) -> None:
    assert atteso in profilo.messaggio_errore(errore)
