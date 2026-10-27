"""«La CI di questo commit è tutta verde?» — la seconda barriera.

La prima è il job `deploy` del workflow, che ha `needs` sugli altri tre e quindi
non parte se uno è rosso. Questa serve a un caso che la prima non copre: i
segreti della CI rubati, o una richiesta mandata a mano. Il Pi non si fida di
chi lo chiama e chiede a GitHub com'è andata.

    python3 -m custode_deploy.ci <sha>      # esce 0 se è tutto verde
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any

# Il job `deploy` del workflow: al momento del controllo è *in corso* (è lui che
# ha chiamato il Pi), quindi non può contare tra quelli che devono essere verdi.
JOB_DEPLOY = "Deploy"

REPO_DI_DEFAULT = "simopugliese/Custode"


def esito_ci(check_runs: list[dict[str, Any]], escludi: str = JOB_DEPLOY) -> tuple[bool, str]:
    """Verde solo se **ogni** job di GitHub Actions è `completed` e `success`.

    Si guardano solo i controlli di GitHub Actions: un'app terza (Cloudflare
    Pages ne pubblica uno per commit) potrebbe essere in corso o rossa per cause
    che non c'entrano con la qualità del codice. `skipped` e `neutral` non
    passano: «tutto verde» vuol dire che ogni controllo ha detto di sì.
    """
    considerati = [
        c
        for c in check_runs
        if (c.get("app") or {}).get("slug") == "github-actions" and c.get("name") != escludi
    ]
    if not considerati:
        return False, "nessun controllo trovato per questo commit"
    non_verdi = [
        f"{c.get('name')} ({c.get('conclusion') or c.get('status')})"
        for c in considerati
        if c.get("status") != "completed" or c.get("conclusion") != "success"
    ]
    if non_verdi:
        return False, "non sono verdi: " + ", ".join(non_verdi)
    return True, f"{len(considerati)} controlli verdi"


def scarica_check_runs(repo: str, sha: str, timeout: float = 20.0) -> list[dict[str, Any]]:
    """I controlli di un commit, dall'API pubblica di GitHub (repo pubblico)."""
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?per_page=100"
    richiesta = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "custode-deploy"},
    )
    with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
        corpo = json.load(risposta)
    runs = corpo.get("check_runs", [])
    if not isinstance(runs, list):
        raise ValueError("risposta di GitHub inattesa: check_runs non è una lista")
    return runs


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python3 -m custode_deploy.ci <sha>", file=sys.stderr)
        return 2
    repo = os.environ.get("CUSTODE_DEPLOY_REPO", REPO_DI_DEFAULT)
    try:
        verde, motivo = esito_ci(scarica_check_runs(repo, argv[1]))
    except (OSError, ValueError) as errore:
        # Non riuscire a sapere com'è andata la CI vale come «non verde».
        print(f"impossibile leggere la CI: {errore}")
        return 1
    print(motivo)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
