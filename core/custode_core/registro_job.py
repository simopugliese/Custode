"""Il registro di cosa i job hanno già fatto (`job_runs`, ARCHITECTURE.md §5).

Sta in `core` e non in `worker/` perché la tabella è definita da una migrazione
di `core` e da qui in poi la leggono in due: il worker per non rifare un job già
fatto, e l'API per sapere se il calendario ha mai sincronizzato — che è la
differenza fra «oggi non hai impegni» e «non ho ancora guardato». L'alternativa
sarebbe stata far dipendere l'API dal worker, cioè far dipendere ciò che
risponde alle richieste da ciò che gira di notte.

Qui non c'è nessuna decisione su *quando* un job è dovuto: quella è logica pura
e sta in `custode_worker.pianificazione`, senza database e senza orologio.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

RIEPILOGO_SETTIMANALE = "riepilogo_settimanale"
BACKUP = "backup"
REPORT_MENSILE_ABITUDINI = "report_mensile_abitudini"
SYNC_CALENDARIO = "sync_calendario"
AVVISO_CALENDARIO_FERMO = "avviso_calendario_fermo"

SENZA_PERIODO = "-"
"""La chiave delle cose che il registro ricorda ma che non hanno un periodo.

«Ti ho già avvisato che il calendario è fermo» vale finché non si ripara, non
per un giorno o una settimana. Tenerle qui lascia al worker un posto solo in cui
ricordare cosa ha già fatto; a distinguerle è che la loro riga si **cancella**
quando finisce lo stato che la giustificava, invece di accumularsi un periodo
dopo l'altro.
"""


def _chiave(valore: date | datetime | str) -> str:
    """Il periodo come sta in `job_runs`.

    Un periodo può essere un giorno (`2026-09-14`), una fascia oraria
    (`2026-09-14T10:15`) o niente (`SENZA_PERIODO`). Al minuto e non al secondo
    per le fasce: due secondi diversi dentro la stessa fascia sono lo stesso
    periodo, e lasciarceli renderebbe la chiave diversa ad ogni giro.
    """
    if isinstance(valore, datetime):
        return valore.isoformat(timespec="minutes")
    if isinstance(valore, date):
        return valore.isoformat()
    return valore


def gia_eseguito(conn: sqlite3.Connection, nome: str, chiave: date | datetime | str) -> bool:
    riga = conn.execute(
        "SELECT 1 FROM job_runs WHERE nome = ? AND chiave = ?", (nome, _chiave(chiave))
    ).fetchone()
    return riga is not None


def segna_eseguito(
    conn: sqlite3.Connection, nome: str, chiave: date | datetime | str, ora: datetime
) -> None:
    """Registra che il job è stato fatto per quel periodo.

    Si segna anche quando il job non ha prodotto niente (una settimana senza
    voci approvate): senza, il worker ci riproverebbe ad ogni giro per sempre.
    """
    conn.execute(
        "INSERT OR IGNORE INTO job_runs (nome, chiave, eseguito_il) VALUES (?, ?, ?)",
        (nome, _chiave(chiave), ora.isoformat(timespec="seconds")),
    )


def dimentica(conn: sqlite3.Connection, nome: str, chiave: date | datetime | str) -> None:
    """Toglie dal registro una cosa segnata, così potrà succedere di nuovo.

    Serve alle righe `SENZA_PERIODO`: l'avviso «il calendario è fermo» si
    dimentica quando il calendario riparte, e solo allora potrà tornare.
    """
    conn.execute("DELETE FROM job_runs WHERE nome = ? AND chiave = ?", (nome, _chiave(chiave)))


def dimentica_prima_di(conn: sqlite3.Connection, nome: str, limite: date | datetime) -> int:
    """Pota le esecuzioni di un job più vecchie di `limite`. Ritorna quante.

    Serve ai job a fascia e non a quelli settimanali: il riepilogo lascia
    cinquantadue righe all'anno, la sincronizzazione del calendario ne
    lascerebbe trentacinquemila. E non servono a niente, perché `fascia_dovuta`
    guarda solo la fascia corrente: il passato del registro è materiale da
    leggere quando qualcosa non torna, non un dato su cui si decide. Se ne
    tiene quindi una finestra breve invece di far crescere senza fine la
    tabella più scritta del database — che è anche quella che ogni notte
    finisce nel backup (§9).

    Il confronto è lessicografico sull'ISO, che per chiavi della stessa forma è
    l'ordine cronologico.
    """
    cursore = conn.execute(
        "DELETE FROM job_runs WHERE nome = ? AND chiave < ?", (nome, _chiave(limite))
    )
    return cursore.rowcount


def ultima_esecuzione(conn: sqlite3.Connection, nome: str) -> datetime | None:
    """Quando il job è stato eseguito l'ultima volta, o `None` se mai.

    `None` non è «non ha prodotto niente»: è «non è mai partito». Serve all'API
    per non dire «nessun evento oggi» prima che il calendario abbia guardato
    anche solo una volta — una frase che a calendario appena collegato sarebbe
    semplicemente falsa.
    """
    riga = conn.execute(
        "SELECT MAX(eseguito_il) AS quando FROM job_runs WHERE nome = ?", (nome,)
    ).fetchone()
    if riga is None or riga["quando"] is None:
        return None
    quando: str = riga["quando"]
    return datetime.fromisoformat(quando)
