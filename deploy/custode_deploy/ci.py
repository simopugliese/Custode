"""«La CI di questo commit è tutta verde?» — la seconda barriera.

La prima è il job `deploy` del workflow, che ha `needs` sugli altri tre e quindi
non parte se uno è rosso. Questa serve a un caso che la prima non copre: i
segreti della CI rubati, o una richiesta mandata a mano. Il Pi non si fida di
chi lo chiama e chiede a GitHub com'è andata.

    python3 -m custode_deploy.ci <sha>      # esce 0 se è tutto verde

Se i controlli sono ancora in corso aspetta (fino a due minuti) prima di dire no.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable
from enum import StrEnum
from typing import Any

# Il job `deploy` del workflow: al momento del controllo è *in corso* (è lui che
# ha chiamato il Pi), quindi non può contare tra quelli che devono essere verdi.
JOB_DEPLOY = "Deploy"

# Ogni quanto si richiede lo stato e per quanto al massimo: la gara dura qualche
# secondo, due minuti sono ampi senza tenere appeso il deploy se la CI è davvero
# ancora in corso.
ATTESA_SECONDI = 10.0
ATTESA_MASSIMA_SECONDI = 120.0

REPO_DI_DEFAULT = "simopugliese/Custode"


class Esito(StrEnum):
    VERDE = "verde"
    # Controlli ancora `queued`/`in_progress` (o non ancora comparsi): non è un
    # no, è un «non so ancora». Si distingue dal rosso perché ha senso aspettare.
    IN_ATTESA = "in_attesa"
    ROSSO = "rosso"


def esito_ci(check_runs: list[dict[str, Any]], escludi: str = JOB_DEPLOY) -> tuple[Esito, str]:
    """Verde solo se **ogni** job di GitHub Actions è `completed` e `success`.

    Si guardano solo i controlli di GitHub Actions: un'app terza (Cloudflare
    Pages ne pubblica uno per commit) potrebbe essere in corso o rossa per cause
    che non c'entrano con la qualità del codice. `skipped` e `neutral` non
    passano: «tutto verde» vuol dire che ogni controllo ha detto di sì.

    Un controllo già concluso e non `success` è rosso subito, anche se altri
    girano ancora: aspettarli non cambierebbe la risposta.
    """
    considerati = [
        c
        for c in check_runs
        if (c.get("app") or {}).get("slug") == "github-actions" and c.get("name") != escludi
    ]
    if not considerati:
        return Esito.IN_ATTESA, "nessun controllo trovato per questo commit"
    rossi = [
        f"{c.get('name')} ({c.get('conclusion')})"
        for c in considerati
        if c.get("status") == "completed" and c.get("conclusion") != "success"
    ]
    if rossi:
        return Esito.ROSSO, "non sono verdi: " + ", ".join(rossi)
    in_corso = [
        f"{c.get('name')} ({c.get('status')})"
        for c in considerati
        if c.get("status") != "completed"
    ]
    if in_corso:
        return Esito.IN_ATTESA, "ancora in corso: " + ", ".join(in_corso)
    return Esito.VERDE, f"{len(considerati)} controlli verdi"


def attendi_ci(
    scarica: Callable[[], list[dict[str, Any]]],
    *,
    attesa: float = ATTESA_SECONDI,
    massimo: float = ATTESA_MASSIMA_SECONDI,
    dormi: Callable[[float], None] = time.sleep,
    orologio: Callable[[], float] = time.monotonic,
) -> tuple[bool, str]:
    """Come `esito_ci`, ma aspetta finché i controlli sono solo in corso o in coda.

    Il job `Deploy` parte a CI finita, ma l'API dei check-runs può mostrare per
    qualche secondo lo stato vecchio: rifiutare alla prima lettura bocciava
    commit verdi. Il rosso, invece, ferma subito. Se il tempo finisce si rifiuta
    dicendo cosa girava ancora.
    """
    inizio = orologio()
    while True:
        esito, motivo = esito_ci(scarica())
        aspettato = orologio() - inizio
        if esito is Esito.VERDE:
            if aspettato > 0:
                motivo += f", dopo {aspettato:.0f} s di attesa"
            return True, motivo
        if esito is Esito.ROSSO:
            return False, motivo
        if aspettato + attesa > massimo:
            return False, f"dopo {aspettato:.0f} s {motivo}"
        dormi(attesa)


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
        verde, motivo = attendi_ci(lambda: scarica_check_runs(repo, argv[1]))
    except (OSError, ValueError) as errore:
        # Non riuscire a sapere com'è andata la CI vale come «non verde».
        print(f"impossibile leggere la CI: {errore}")
        return 1
    print(motivo)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
