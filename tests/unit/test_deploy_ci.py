"""«Tutto verde» vuol dire tutto: un solo controllo non verde ferma il deploy."""

from __future__ import annotations

from typing import Any

import pytest

from custode_deploy.ci import Esito, attendi_ci, esito_ci


def _run(
    nome: str, conclusione: str | None = "success", stato: str = "completed"
) -> dict[str, Any]:
    return {
        "name": nome,
        "status": stato,
        "conclusion": conclusione,
        "app": {"slug": "github-actions"},
    }


TUTTI_VERDI = [
    _run("Backend (lint, tipi, test)"),
    _run("Immagini Docker (build + import) (api)"),
    _run("Dashboard (lint, build)"),
]


def test_tutto_verde_passa() -> None:
    esito, motivo = esito_ci(TUTTI_VERDI)
    assert esito is Esito.VERDE
    assert "3" in motivo


def test_un_controllo_rosso_ferma_tutto() -> None:
    esito, motivo = esito_ci([*TUTTI_VERDI, _run("Dashboard (lint, build)", "failure")])
    assert esito is Esito.ROSSO
    assert "Dashboard" in motivo


def test_un_controllo_in_corso_o_in_coda_e_in_attesa_non_rosso() -> None:
    for stato in ("in_progress", "queued"):
        esito, motivo = esito_ci([*TUTTI_VERDI, _run("Immagini Docker", None, stato)])
        assert esito is Esito.IN_ATTESA
        assert f"Immagini Docker ({stato})" in motivo


def test_un_rosso_conta_anche_se_un_altro_e_ancora_in_corso() -> None:
    esito, motivo = esito_ci(
        [*TUTTI_VERDI, _run("Dashboard", "failure"), _run("Immagini", None, "in_progress")]
    )
    assert esito is Esito.ROSSO
    assert "Dashboard" in motivo


def test_skipped_e_neutral_non_contano_come_verdi() -> None:
    assert esito_ci([*TUTTI_VERDI, _run("Qualcosa", "skipped")])[0] is Esito.ROSSO
    assert esito_ci([*TUTTI_VERDI, _run("Qualcosa", "neutral")])[0] is Esito.ROSSO


def test_il_job_deploy_non_conta_perche_e_lui_che_ci_ha_chiamato() -> None:
    chiamante = _run("Deploy", None, "in_progress")
    assert esito_ci([*TUTTI_VERDI, chiamante])[0] is Esito.VERDE


def test_un_controllo_di_unaltra_app_non_decide() -> None:
    cloudflare = {
        "name": "Cloudflare Pages",
        "status": "in_progress",
        "conclusion": None,
        "app": {"slug": "cloudflare-workers-and-pages"},
    }
    assert esito_ci([*TUTTI_VERDI, cloudflare])[0] is Esito.VERDE


def test_nessun_controllo_non_e_verde() -> None:
    # Un commit appena pushato, o un'API che non risponde bene, non vale «verde»:
    # ma nemmeno «rosso», perché i controlli possono ancora comparire.
    assert esito_ci([])[0] is Esito.IN_ATTESA
    assert esito_ci([_run("Deploy", None, "in_progress")])[0] is Esito.IN_ATTESA


class _Tempo:
    """Orologio e sonno finti: l'attesa avanza senza far passare tempo vero."""

    def __init__(self) -> None:
        self.ora = 0.0
        self.pause: list[float] = []

    def dormi(self, secondi: float) -> None:
        self.pause.append(secondi)
        self.ora += secondi

    def orologio(self) -> float:
        return self.ora


def _attendi(*letture: list[dict[str, Any]]) -> tuple[bool, str, _Tempo]:
    """Ogni lettura è una risposta di GitHub; l'ultima si ripete."""
    tempo = _Tempo()
    coda = list(letture)

    def scarica() -> list[dict[str, Any]]:
        return coda.pop(0) if len(coda) > 1 else coda[0]

    ok, motivo = attendi_ci(scarica, dormi=tempo.dormi, orologio=tempo.orologio)
    return ok, motivo, tempo


IN_CORSO = [*TUTTI_VERDI, _run("Immagini Docker", None, "in_progress")]


def test_verde_al_primo_colpo_non_aspetta() -> None:
    ok, motivo, tempo = _attendi(TUTTI_VERDI)
    assert ok
    assert tempo.pause == []
    assert "attesa" not in motivo


def test_in_corso_poi_verde_passa_dopo_aver_aspettato() -> None:
    # La gara di GitHub: lo stato vecchio per qualche secondo, poi quello giusto.
    ok, motivo, tempo = _attendi(IN_CORSO, IN_CORSO, TUTTI_VERDI)
    assert ok
    assert tempo.pause == [10.0, 10.0]
    assert "20 s di attesa" in motivo


def test_in_corso_poi_rosso_rifiuta_subito() -> None:
    ok, motivo, tempo = _attendi(IN_CORSO, [*TUTTI_VERDI, _run("Immagini Docker", "failure")])
    assert not ok
    assert "Immagini Docker (failure)" in motivo
    assert tempo.pause == [10.0]


def test_sempre_in_corso_scade_e_dice_cosa_girava() -> None:
    ok, motivo, tempo = _attendi(IN_CORSO)
    assert not ok
    assert "ancora in corso" in motivo
    assert "Immagini Docker (in_progress)" in motivo
    assert sum(tempo.pause) <= 120.0
    assert len(tempo.pause) == 12


def test_un_errore_di_rete_non_viene_ingoiato() -> None:
    def scarica() -> list[dict[str, Any]]:
        raise OSError("rete giù")

    with pytest.raises(OSError):
        attendi_ci(scarica, dormi=lambda _: None)
