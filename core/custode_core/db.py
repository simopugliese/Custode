"""Accesso a SQLite in modalità WAL (ARCHITECTURE.md §3).

Un solo file su disco, nessun processo DB separato: il volume Docker che lo
contiene è l'unica cosa da backuppare (§9). Le PRAGMA sono applicate ad ogni
connessione perché `foreign_keys` e `busy_timeout` sono per-connessione;
`journal_mode=WAL` è invece una proprietà persistente del file e riapplicarla
è un'operazione innocua.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from custode_core.config import get_settings


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Apre una connessione a SQLite pronta all'uso.

    Se `db_path` è omesso usa quello delle impostazioni. La cartella che
    contiene il file viene creata se manca, così il primo avvio su un volume
    vuoto funziona senza passi manuali.
    """
    percorso = Path(db_path) if db_path is not None else get_settings().db_path
    percorso.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(percorso, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    # Bot, API e job schedulati scrivono sullo stesso file: invece di fallire
    # subito su "database is locked", si attende fino a 5 secondi.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def connessione(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Connessione usa-e-getta, chiusa in ogni caso all'uscita dal blocco."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transazione(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Tutto o niente attorno a più scritture: o passano tutte, o non è successo niente.

    Le connessioni del progetto sono in autocommit (`isolation_level=None`),
    quindi ogni `execute` si consolida da sé. Va benissimo per una scrittura
    sola; non va per una funzione che ne fa tre validando ogni campo appena
    prima di scriverlo, perché il terzo campo storto lascia i primi due scritti
    — e la risposta, che è un errore, dice il contrario di quello che c'è in
    tabella. È lo stesso ragionamento del runner delle migrazioni, che apre la
    sua transazione per la stessa ragione.

    `BEGIN IMMEDIATE` e non `BEGIN`: prende subito il lock di scrittura invece
    di scoprire a metà che qualcun altro ce l'ha.

    **Si apre nella rotta, non nella funzione di dominio**, ed è una scelta e
    non una comodità: i domini si chiamano fra loro — `abitudini.crea` ricade
    su `abitudini.modifica` quando il nome esiste già — e una transazione per
    funzione diventerebbe una transazione dentro l'altra, che su SQLite è un
    errore. La rotta è l'unico punto che sa dov'è il confine della richiesta.

    **Non va messa attorno a una chiamata di rete.** Tenere il lock di
    scrittura per i decine di secondi di una risposta del modello farebbe
    scadere il `busy_timeout` di API e bot: lì una riga della lista della spesa
    comincerebbe a fallire per colpa del calendario. Vedi
    `custode_worker.calendario.tagga`, dove il punto è spiegato per esteso.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def db_raggiungibile(db_path: Path | str | None = None) -> bool:
    """True se il file SQLite si apre e risponde a una query banale.

    Usata dall'health check dell'API (§10): se torna False il deploy va
    considerato fallito.
    """
    try:
        with connessione(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return False
    return True
