"""Backup del database (ARCHITECTURE.md §9, §13).

Il database è un unico file, e questa è la sola cosa che sta fra un diario di
mesi e una microSD che muore. Il job gira una volta al giorno, tiene 7 copie
giornaliere e 4 settimanali, e comprime — e cifra, se gli dai una chiave.

**Copia coerente senza fermare niente.** Non si copia il file con `cp`: in
modalità WAL le scritture stanno in un file a parte, e una copia fatta a mano
può cogliere il database a metà di una transazione. Si usa l'API `.backup()` di
SQLite, che produce uno snapshot consistente mentre bot, API e worker
continuano a scrivere.

**Senza chiave si fa lo stesso, in chiaro.** §9 vuole il backup cifrato, ma il
rischio più probabile in casa non è il furto del disco: è la scheda che si
rompe. Un backup in chiaro protegge da quello, nessun backup no. Si vede a
occhio quale dei due hai — l'estensione cambia — e il worker lo ripete nei log.
"""

from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from custode_core.formato import inizio_settimana

log = logging.getLogger("custode.worker")

PREFISSO = "custode-"
SUFFISSO = ".db.gz"
SUFFISSO_CIFRATO = SUFFISSO + ".enc"

# §9: «retention 7 copie giornaliere + 4 settimanali».
GIORNALIERI = 7
SETTIMANALI = 4


class BackupNonRiuscito(RuntimeError):
    """Il backup non è stato fatto: il motivo è già leggibile."""


@dataclass(frozen=True)
class Esito:
    percorso: Path
    cifrato: bool
    byte: int
    rimossi: list[Path] = field(default_factory=list)


def nome_file(giorno: date, *, cifrato: bool) -> str:
    return f"{PREFISSO}{giorno.isoformat()}{SUFFISSO_CIFRATO if cifrato else SUFFISSO}"


def giorno_di(percorso: Path) -> date | None:
    """La data di un backup dal suo nome, o None se il file non è dei nostri.

    Si legge dal nome e non dalla data di modifica del file: copiare la cartella
    altrove cambia i timestamp, non i nomi — e un backup deve sopravvivere
    all'essere spostato.
    """
    nome = percorso.name
    if not nome.startswith(PREFISSO):
        return None
    for suffisso in (SUFFISSO_CIFRATO, SUFFISSO):
        if nome.endswith(suffisso):
            try:
                return date.fromisoformat(nome[len(PREFISSO) : -len(suffisso)])
            except ValueError:
                return None
    return None


def _cifra(dati: bytes, chiave: str) -> bytes:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(chiave.encode()).encrypt(dati)
    except (ValueError, InvalidToken) as errore:
        raise BackupNonRiuscito(
            "WORKER_BACKUP_CHIAVE non è una chiave valida: generane una con"
            ' python -c "from cryptography.fernet import Fernet;'
            ' print(Fernet.generate_key().decode())"'
        ) from errore


def _decifra(dati: bytes, chiave: str) -> bytes:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(chiave.encode()).decrypt(dati)
    except (ValueError, InvalidToken) as errore:
        raise BackupNonRiuscito(
            "la chiave non apre questo backup: è quella di un'altra installazione,"
            " o è stata cambiata dopo averlo scritto"
        ) from errore


def copia_coerente(db_path: Path, destinazione: Path) -> None:
    """Snapshot di SQLite mentre gli altri servizi continuano a scrivere."""
    if not db_path.exists():
        raise BackupNonRiuscito(f"il database non esiste: {db_path}")
    sorgente = sqlite3.connect(db_path)
    copia = sqlite3.connect(destinazione)
    try:
        sorgente.backup(copia)
    except sqlite3.Error as errore:
        raise BackupNonRiuscito(f"copia del database non riuscita: {errore}") from errore
    finally:
        copia.close()
        sorgente.close()


def da_tenere(giorni: list[date], oggi: date) -> set[date]:
    """Quali backup sopravvivono alla pulizia (§9): 7 giornalieri + 4 settimanali.

    Funzione pura, così la regola di retention — l'unica parte che, sbagliata,
    cancella dati — si prova senza toccare il disco. I settimanali si contano
    per settimana di calendario, tenendo il più recente di ciascuna: dopo un
    mese restano una copia di ieri e una per ognuna delle ultime quattro
    settimane, non undici file dello stesso periodo.
    """
    recenti = sorted((g for g in giorni if g <= oggi), reverse=True)
    tenuti = set(recenti[:GIORNALIERI])

    per_settimana: dict[date, date] = {}
    for giorno in recenti:
        per_settimana.setdefault(inizio_settimana(giorno), giorno)
    tenuti |= set(sorted(per_settimana.values(), reverse=True)[:SETTIMANALI])

    # I backup con una data futura non si toccano: è un orologio storto, non un
    # file da buttare, e cancellare per un fuso sbagliato sarebbe irreparabile.
    tenuti |= {g for g in giorni if g > oggi}
    return tenuti


def _ripulisci(cartella: Path, oggi: date) -> list[Path]:
    presenti = {p: giorno_di(p) for p in cartella.iterdir() if p.is_file()}
    nostri = {p: g for p, g in presenti.items() if g is not None}
    tenuti = da_tenere(list(nostri.values()), oggi)

    rimossi: list[Path] = []
    for percorso, giorno in sorted(nostri.items()):
        if giorno not in tenuti:
            percorso.unlink()
            rimossi.append(percorso)
    return rimossi


def esegui(db_path: Path, cartella: Path, ora: datetime, *, chiave: str | None = None) -> Esito:
    """Fa il backup del giorno e ripulisce i vecchi. Ritorna cosa ha scritto."""
    cartella.mkdir(parents=True, exist_ok=True)
    cifrato = bool(chiave)
    destinazione = cartella / nome_file(ora.date(), cifrato=cifrato)

    with tempfile.TemporaryDirectory() as temporanea:
        grezzo = Path(temporanea) / "custode.db"
        copia_coerente(db_path, grezzo)
        compresso = gzip.compress(grezzo.read_bytes())

    dati = _cifra(compresso, chiave) if chiave else compresso
    # Si scrive a fianco e poi si rinomina: un backup interrotto a metà non
    # deve prendere il posto — né il nome — di uno buono.
    parziale = destinazione.with_suffix(destinazione.suffix + ".parziale")
    parziale.write_bytes(dati)
    parziale.replace(destinazione)

    # Il gemello con l'altra estensione (hai messo o tolto la chiave oggi)
    # sarebbe una copia dello stesso giorno che la retention non riconosce
    # come doppione: va via adesso.
    gemello = cartella / nome_file(ora.date(), cifrato=not cifrato)
    if gemello.exists():
        gemello.unlink()

    rimossi = _ripulisci(cartella, ora.date())
    return Esito(percorso=destinazione, cifrato=cifrato, byte=len(dati), rimossi=rimossi)


def ripristina(archivio: Path, destinazione: Path, *, chiave: str | None = None) -> Path:
    """Riporta un backup a database utilizzabile. Ritorna il file scritto.

    Non tocca il database in esercizio: scrive dove gli dici, e sei tu a
    metterlo al suo posto a servizi fermi. Un restore che sovrascrive da solo il
    file vivo è il modo più rapido di trasformare un problema in due.
    """
    if not archivio.exists():
        raise BackupNonRiuscito(f"il backup non esiste: {archivio}")
    if destinazione.exists():
        raise BackupNonRiuscito(
            f"{destinazione} esiste già: scegli un altro percorso invece di sovrascriverlo"
        )

    dati = archivio.read_bytes()
    if archivio.name.endswith(SUFFISSO_CIFRATO):
        if not chiave:
            raise BackupNonRiuscito(
                "questo backup è cifrato: serve la chiave (WORKER_BACKUP_CHIAVE)"
            )
        dati = _decifra(dati, chiave)

    try:
        db = gzip.decompress(dati)
    except (OSError, EOFError) as errore:
        raise BackupNonRiuscito(f"l'archivio non si apre: {errore}") from errore

    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_bytes(db)

    # Verifica che sia davvero un database e non un file qualsiasi: scoprirlo
    # adesso è meglio che scoprirlo dopo averlo messo al posto di quello vivo.
    try:
        conn = sqlite3.connect(destinazione)
        esito = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
    except sqlite3.Error as errore:
        destinazione.unlink(missing_ok=True)
        raise BackupNonRiuscito(f"il file ripristinato non è un database: {errore}") from errore
    if esito != "ok":
        destinazione.unlink(missing_ok=True)
        raise BackupNonRiuscito(f"il database ripristinato è corrotto: {esito}")

    return destinazione


def elenco(cartella: Path) -> list[tuple[date, Path, int]]:
    """I backup presenti, dal più recente: data, file, byte."""
    if not cartella.exists():
        return []
    trovati = [
        (giorno, p, p.stat().st_size)
        for p in cartella.iterdir()
        if p.is_file() and (giorno := giorno_di(p)) is not None
    ]
    return sorted(trovati, reverse=True)


def spazio_libero(cartella: Path) -> int:
    """Byte liberi dove finiscono i backup. Zero se la cartella non c'è."""
    if not cartella.exists():
        return 0
    return shutil.disk_usage(cartella).free
