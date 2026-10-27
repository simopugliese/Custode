"""`deploy/deploy.sh` provato per davvero, su un repo git vero in una cartella temporanea.

`docker` e `curl` sono finti (stanno in una cartella messa in testa al PATH):
non serve Docker e non si tocca la rete. Quello che si controlla è il percorso
delle decisioni — chi viene rifiutato, quando si torna indietro, quando no —
che è il pezzo che non deve sbagliare mai.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from custode_deploy.listener import STATI_PER_CODICE

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="serve git e bash (non ci sono nell'immagine di test)",
)

# `docker` finto: ricorda ogni chiamata e basta.
DOCKER = '#!/bin/sh\necho "$*" >> "$FINTO_LOG"\nexit 0\n'

# `curl` finto per /api/health: fallisce se il commit in esecuzione è nella lista
# dei «cattivi», risponde bene altrimenti. È la stessa cosa che vedrebbe il Pi
# con un'API che non parte.
CURL = """#!/bin/sh
attuale=$(git rev-parse HEAD)
if grep -qx "$attuale" "$FINTO_CATTIVI" 2>/dev/null; then exit 22; fi
exit 0
"""

CI_VERDE = '#!/bin/sh\necho "tutto verde"\nexit 0\n'
CI_ROSSA = '#!/bin/sh\necho "Dashboard (failure)"\nexit 1\n'


def _git(cartella: Path, *argomenti: str) -> str:
    return subprocess.run(
        ["git", *argomenti], cwd=cartella, check=True, capture_output=True, text=True
    ).stdout.strip()


def _scrivi(percorso: Path, contenuto: str, eseguibile: bool = False) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(contenuto)
    if eseguibile:
        percorso.chmod(0o755)


@dataclass
class Scenario:
    cartella: Path  # il checkout del «Pi»
    remoto: Path  # il suo origin
    prima: str  # il commit su cui sta il Pi
    log: Path  # le chiamate a docker
    cattivi: Path  # i commit per cui /api/health non risponde
    ci: Path

    def lancia(self) -> subprocess.CompletedProcess[str]:
        finti = self.cartella.parent / "finti"
        ambiente = {
            **os.environ,
            "PATH": f"{finti}{os.pathsep}{os.environ['PATH']}",
            "CUSTODE_DEPLOY_DIR": str(self.cartella),
            "CUSTODE_DEPLOY_CI_CMD": str(self.ci),
            "CUSTODE_DEPLOY_SMOKE_TENTATIVI": "2",
            "CUSTODE_DEPLOY_SMOKE_PAUSA": "0",
            "FINTO_LOG": str(self.log),
            "FINTO_CATTIVI": str(self.cattivi),
        }
        return subprocess.run(
            ["bash", str(SCRIPT)], env=ambiente, capture_output=True, text=True, check=False
        )

    def pubblica(self, file: str, contenuto: str, *, cattivo: bool = False) -> str:
        """Un commit nuovo su origin/main (da un secondo checkout), come un push."""
        altro = self.cartella.parent / "altro"
        if not altro.exists():
            subprocess.run(["git", "clone", "-q", str(self.remoto), str(altro)], check=True)
            _git(altro, "config", "user.email", "t@t")
            _git(altro, "config", "user.name", "t")
        _scrivi(altro / file, contenuto)
        _git(altro, "add", "-A")
        _git(altro, "commit", "-q", "-m", "nuovo")
        _git(altro, "push", "-q", "origin", "HEAD:main")
        nuovo = _git(altro, "rev-parse", "HEAD")
        if cattivo:
            with self.cattivi.open("a") as f:
                f.write(nuovo + "\n")
        return nuovo

    def chiamate_docker(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    remoto = tmp_path / "origin.git"
    cartella = tmp_path / "pi"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remoto)], check=True)
    subprocess.run(["git", "clone", "-q", str(remoto), str(cartella)], check=True)
    _git(cartella, "config", "user.email", "t@t")
    _git(cartella, "config", "user.name", "t")
    _git(cartella, "checkout", "-q", "-b", "main")
    _scrivi(cartella / "core" / "custode_core" / "migrazioni" / "001.sql", "-- uno\n")
    _git(cartella, "add", "-A")
    _git(cartella, "commit", "-q", "-m", "base")
    _git(cartella, "push", "-q", "origin", "main")

    finti = tmp_path / "finti"
    _scrivi(finti / "docker", DOCKER, eseguibile=True)
    _scrivi(finti / "curl", CURL, eseguibile=True)
    ci = tmp_path / "ci_verde"
    _scrivi(ci, CI_VERDE, eseguibile=True)
    return Scenario(
        cartella=cartella,
        remoto=remoto,
        prima=_git(cartella, "rev-parse", "HEAD"),
        log=tmp_path / "docker.log",
        cattivi=tmp_path / "cattivi.txt",
        ci=ci,
    )


def test_tutto_verde_e_in_piedi_il_pi_si_aggiorna(scenario: Scenario) -> None:
    nuovo = scenario.pubblica("novita.txt", "ciao\n")
    risultato = scenario.lancia()
    assert risultato.returncode == 0, risultato.stdout
    assert _git(scenario.cartella, "rev-parse", "HEAD") == nuovo
    assert scenario.chiamate_docker() == ["compose up --build -d"]


def test_con_la_ci_rossa_non_si_tocca_nulla(scenario: Scenario) -> None:
    _scrivi(scenario.ci, CI_ROSSA, eseguibile=True)
    scenario.pubblica("novita.txt", "ciao\n")
    risultato = scenario.lancia()
    assert risultato.returncode == 10, risultato.stdout
    assert "Dashboard (failure)" in risultato.stdout
    assert _git(scenario.cartella, "rev-parse", "HEAD") == scenario.prima
    assert scenario.chiamate_docker() == []


def test_se_il_nuovo_non_risponde_si_torna_al_precedente(scenario: Scenario) -> None:
    scenario.pubblica("novita.txt", "rotta\n", cattivo=True)
    risultato = scenario.lancia()
    assert risultato.returncode == 11, risultato.stdout
    assert _git(scenario.cartella, "rev-parse", "HEAD") == scenario.prima
    # Una `up` per il nuovo, una per il ritorno.
    assert scenario.chiamate_docker() == ["compose up --build -d"] * 2
    # E il ramo è ancora `main`, non una testa staccata: il deploy dopo funziona.
    assert _git(scenario.cartella, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_con_una_migrazione_nuova_non_si_torna_indietro_da_soli(scenario: Scenario) -> None:
    nuovo = scenario.pubblica("core/custode_core/migrazioni/002.sql", "-- due\n", cattivo=True)
    risultato = scenario.lancia()
    assert risultato.returncode == 12, risultato.stdout
    assert "migrazione" in risultato.stdout
    # Il codice nuovo è rimasto: tornare al vecchio con lo schema nuovo è peggio.
    assert _git(scenario.cartella, "rev-parse", "HEAD") == nuovo
    assert scenario.chiamate_docker() == ["compose up --build -d"]


def test_una_migrazione_nuova_ma_che_funziona_passa_normalmente(scenario: Scenario) -> None:
    scenario.pubblica("core/custode_core/migrazioni/002.sql", "-- due\n")
    assert scenario.lancia().returncode == 0


def test_se_anche_il_ritorno_non_risponde_serve_una_mano(scenario: Scenario) -> None:
    scenario.pubblica("novita.txt", "rotta\n", cattivo=True)
    with scenario.cattivi.open("a") as f:
        f.write(scenario.prima + "\n")
    risultato = scenario.lancia()
    assert risultato.returncode == 12, risultato.stdout


def test_un_checkout_con_modifiche_locali_non_si_aggiorna(scenario: Scenario) -> None:
    # È già successo sul Pi (docker-compose.yml toccato a mano): il merge si
    # ferma, e non si fa nemmeno la `up`.
    scenario.pubblica("file.txt", "dal remoto\n")
    _scrivi(scenario.cartella / "file.txt", "locale\n")
    risultato = scenario.lancia()
    assert risultato.returncode == 1, risultato.stdout
    assert scenario.chiamate_docker() == []


def test_gli_exit_code_dello_script_sono_quelli_che_il_listener_conosce() -> None:
    usati = {int(n) for n in re.findall(r"chiudi (\d+) ", SCRIPT.read_text())}
    sconosciuti = usati - set(STATI_PER_CODICE) - {1}
    assert not sconosciuti, f"deploy.sh esce con {sconosciuti}, che il listener non conosce"
