"""«Tutto verde» vuol dire tutto: un solo controllo non verde ferma il deploy."""

from __future__ import annotations

from typing import Any

from custode_deploy.ci import esito_ci


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
    verde, motivo = esito_ci(TUTTI_VERDI)
    assert verde
    assert "3" in motivo


def test_un_controllo_rosso_ferma_tutto() -> None:
    verde, motivo = esito_ci([*TUTTI_VERDI, _run("Dashboard (lint, build)", "failure")])
    assert not verde
    assert "Dashboard" in motivo


def test_un_controllo_ancora_in_corso_non_e_verde() -> None:
    verde, _ = esito_ci([*TUTTI_VERDI, _run("Immagini Docker", None, "in_progress")])
    assert not verde


def test_skipped_e_neutral_non_contano_come_verdi() -> None:
    assert not esito_ci([*TUTTI_VERDI, _run("Qualcosa", "skipped")])[0]
    assert not esito_ci([*TUTTI_VERDI, _run("Qualcosa", "neutral")])[0]


def test_il_job_deploy_non_conta_perche_e_lui_che_ci_ha_chiamato() -> None:
    chiamante = _run("Deploy", None, "in_progress")
    assert esito_ci([*TUTTI_VERDI, chiamante])[0]


def test_un_controllo_di_unaltra_app_non_decide() -> None:
    cloudflare = {
        "name": "Cloudflare Pages",
        "status": "in_progress",
        "conclusion": None,
        "app": {"slug": "cloudflare-workers-and-pages"},
    }
    assert esito_ci([*TUTTI_VERDI, cloudflare])[0]


def test_nessun_controllo_non_e_verde() -> None:
    # Un commit appena pushato, o un'API che non risponde bene, non vale «verde».
    assert not esito_ci([])[0]
    assert not esito_ci([_run("Deploy", None, "in_progress")])[0]
