"""La tabella di §6: è una decisione di progetto, non un dettaglio."""

from __future__ import annotations

import pytest

from custode_router.compiti import CON_IMMAGINI, TABELLA, Compito, Provider, motivo, provider_per


def test_ogni_compito_e_instradato() -> None:
    # Una voce mancante significherebbe un KeyError al primo uso, in produzione.
    assert set(TABELLA) == set(Compito)


def test_ogni_riga_ha_un_motivo() -> None:
    for compito in Compito:
        assert motivo(compito).strip(), compito


@pytest.mark.parametrize(
    "compito",
    [
        Compito.PARSING_LISTA_SPESA,
        Compito.CRUD_TASK,
        Compito.LOG_ABITUDINI,
        Compito.CATEGORIZZAZIONE_SPESA,
        Compito.SEGNALE_PROFILO,
        Compito.CHIARIMENTO_SEGNALE,
        Compito.DIGEST_MATTUTINO,
    ],
)
def test_i_task_semplici_e_ad_alto_volume_vanno_a_deepseek(compito: Compito) -> None:
    """§1: massima resa, minima spesa."""
    assert provider_per(compito) is Provider.DEEPSEEK


@pytest.mark.parametrize(
    "compito",
    [
        Compito.LETTURA_SCONTRINO,
        Compito.RIASSUNTO_DIARIO,
        Compito.RIEPILOGO_SETTIMANALE_DIARIO,
        Compito.RIFUSIONE_PROFILO,
        Compito.CATEGORIE_SPESA,
        Compito.PROPOSTA_REGOLE,
        Compito.PIANO_RIPASSO,
        Compito.REPORT_ABITUDINI,
        Compito.RIASSUNTO_EMAIL,
    ],
)
def test_qualita_visione_e_ragionamento_vanno_a_claude(compito: Compito) -> None:
    assert provider_per(compito) is Provider.CLAUDE


def test_solo_lo_scontrino_richiede_immagini() -> None:
    assert {Compito.LETTURA_SCONTRINO} == CON_IMMAGINI
