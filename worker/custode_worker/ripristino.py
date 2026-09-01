"""Ripristinare un backup: `python -m custode_worker.ripristino`.

Un runbook che chiede di incollare un one-liner con dentro decompressione e
decifratura è un runbook che si sbaglia proprio nel momento in cui non si può
sbagliare. Qui il restore è un comando, con gli stessi controlli del job che ha
scritto il backup — e non tocca mai il database in esercizio.

    python -m custode_worker.ripristino --elenco
    python -m custode_worker.ripristino /backup/custode-2026-09-06.db.gz.enc /data/ripristinato.db

Mettere il file al posto di quello vivo resta un passo tuo, a servizi fermi:
è l'unico modo perché non succeda per sbaglio.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from custode_worker import backup
from custode_worker.config import get_impostazioni_worker

log = logging.getLogger("custode.ripristino")


def _elenca(cartella: Path) -> int:
    trovati = backup.elenco(cartella)
    if not trovati:
        print(f"Nessun backup in {cartella}.")
        return 1
    print(f"Backup in {cartella}, dal più recente:\n")
    for giorno, percorso, byte in trovati:
        cifrato = "cifrato" if percorso.name.endswith(backup.SUFFISSO_CIFRATO) else "in chiaro"
        print(f"  {giorno}  {byte / 1024:8.1f} kB  {cifrato:10}  {percorso.name}")
    print(f"\nSpazio libero: {backup.spazio_libero(cartella) / 1024**2:.0f} MB")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level="INFO", format="%(message)s")
    impostazioni = get_impostazioni_worker()

    analizzatore = argparse.ArgumentParser(
        prog="python -m custode_worker.ripristino",
        description="Ripristina un backup del database di Custode (§9).",
    )
    analizzatore.add_argument("archivio", nargs="?", type=Path, help="il file di backup")
    analizzatore.add_argument(
        "destinazione", nargs="?", type=Path, help="dove scrivere il database ripristinato"
    )
    analizzatore.add_argument(
        "--elenco", action="store_true", help="elenca i backup disponibili ed esci"
    )
    argomenti = analizzatore.parse_args(argv)

    if argomenti.elenco:
        return _elenca(impostazioni.backup_cartella)

    if argomenti.archivio is None or argomenti.destinazione is None:
        analizzatore.print_help()
        return 2

    try:
        scritto = backup.ripristina(
            argomenti.archivio,
            argomenti.destinazione,
            chiave=impostazioni.backup_chiave or None,
        )
    except backup.BackupNonRiuscito as errore:
        log.error("Ripristino non riuscito: %s", errore)
        return 1

    print(f"Ripristinato in {scritto} ({scritto.stat().st_size / 1024:.1f} kB), integrità ok.")
    print(
        "\nOra, a servizi fermi:\n"
        "  docker compose stop api bot worker\n"
        f"  # sostituisci il database con {scritto}\n"
        "  docker compose up -d && curl -s localhost:8000/api/health"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
