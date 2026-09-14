"""Quando un job è dovuto — logica pura, nessun orologio e nessun database.

Tutto ciò che decide *se* è il momento sta qui e prende `adesso` come
parametro: la differenza fra un test che gira in un millesimo di secondo e uno
che aspetterebbe fino a domenica sera.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from custode_core.formato import inizio_settimana

RIEPILOGO_SETTIMANALE = "riepilogo_settimanale"
BACKUP = "backup"
REPORT_MENSILE_ABITUDINI = "report_mensile_abitudini"
SYNC_CALENDARIO = "sync_calendario"
AVVISO_CALENDARIO_FERMO = "avviso_calendario_fermo"

MINUTI_SYNC_CALENDARIO = 15
"""Ogni quanto risincronizzare il calendario (§8.10).

Un quarto d'ora perché la granularità più fine che §8.10 prevede è «dimmelo
trenta minuti prima dell'evento»: un impegno aggiunto adesso arriva comunque
in tempo per la sua stessa regola. Più stretto sarebbero chiamate a Google per
niente, più largo un evento aggiunto all'ultimo perderebbe il suo promemoria.

Non è configurabile: è una costante che discende da una scelta di progetto, non
un gusto della macchina su cui gira.
"""

SENZA_PERIODO = "-"
"""La chiave delle cose che il registro ricorda ma che non hanno un periodo.

«Ti ho già avvisato che il calendario è fermo» vale finché non si ripara, non
per un giorno o una settimana. Tenerle in `job_runs` lascia al worker un posto
solo in cui ricordare cosa ha già fatto; a distinguerle è che la loro riga si
**cancella** quando finisce lo stato che la giustificava, invece di accumularsi
un periodo dopo l'altro.
"""


def momento_previsto(lunedi: date, giorno: str, ore: int, minuti: int) -> datetime:
    """Quando va chiusa la settimana che comincia il `lunedi` indicato.

    Con `domenica` è la sera dell'ultimo giorno della settimana stessa; con
    `lunedi` è il giorno dopo, cioè il lunedì successivo — in entrambi i casi
    la settimana è finita quando la si riepiloga.
    """
    scarto = 6 if giorno == "domenica" else 7
    return datetime.combine(lunedi + timedelta(days=scarto), time(hour=ore, minute=minuti))


def settimana_dovuta(adesso: datetime, *, giorno: str, ore: int, minuti: int) -> date | None:
    """Il lunedì della settimana da riepilogare adesso, o None se non è ora.

    Si guarda indietro di due settimane invece di controllare solo «è oggi il
    giorno giusto?»: se il Pi era spento all'ora prevista, il job deve partire
    appena torna acceso invece di saltare la settimana. Due e non di più perché
    dopo un'assenza lunga ha senso riprendere dall'ultima settimana, non
    rovesciare addosso quattro revisioni tutte insieme.
    """
    lunedi = inizio_settimana(adesso.date())
    for candidato in (lunedi, lunedi - timedelta(days=7)):
        if adesso >= momento_previsto(candidato, giorno, ore, minuti):
            return candidato
    return None


def giorno_dovuto(adesso: datetime, *, ore: int, minuti: int) -> date:
    """Il giorno per cui un job *giornaliero* è dovuto adesso.

    Stessa forma del settimanale: prima dell'ora di oggi si guarda a ieri,
    perché se il Pi era spento a quell'ora il backup di ieri non è stato fatto e
    va recuperato appena torna su. Ritorna sempre una data — sarà il registro a
    dire se quel giorno è già stato coperto.
    """
    if adesso >= datetime.combine(adesso.date(), time(hour=ore, minute=minuti)):
        return adesso.date()
    return adesso.date() - timedelta(days=1)


def fascia_dovuta(adesso: datetime, *, ogni_minuti: int) -> datetime:
    """L'inizio della fascia di `ogni_minuti` in cui cade `adesso`.

    È la forma che prende «cosa è dovuto adesso?» per un job che gira più volte
    al giorno: la fascia fa da periodo, esattamente come il lunedì per il
    riepilogo settimanale, e il registro dice se quella è già stata coperta. Il
    worker si sveglia più spesso di così, quindi una fascia può essere
    interrogata più volte e coperta una sola.

    **Non si guarda indietro**, al contrario del settimanale e del giornaliero.
    Se il Pi era spento non c'è niente da recuperare: le fasce perse non
    contengono lavoro arretrato, contengono lo stesso lavoro di adesso. Rifarle
    una per una vorrebbe dire risincronizzare novantasei volte di fila per
    ottenere ciò che un solo giro ottiene subito.

    Le fasce sono ancorate all'ora, non al momento dell'avvio: con quindici
    minuti sono :00, :15, :30, :45, uguali dopo ogni riavvio. Se `ogni_minuti`
    non divide 60 l'ultima fascia dell'ora resta più corta — accettabile, e la
    ragione per cui i divisori di 60 sono gli unici valori sensati.
    """
    if not 1 <= ogni_minuti <= 60:
        raise ValueError(f"la fascia dev'essere fra 1 e 60 minuti, non {ogni_minuti}")
    return adesso.replace(
        minute=(adesso.minute // ogni_minuti) * ogni_minuti, second=0, microsecond=0
    )


def mese_dovuto(adesso: datetime, *, ore: int, minuti: int) -> date | None:
    """Il primo giorno del mese da raccontare adesso, o None se non è ora.

    Il mese si chiude quando è finito: il resoconto di settembre parte il primo
    di ottobre, alla stessa ora del riepilogo settimanale. Come per la
    settimana si guarda anche a quello prima, così un Pi spento il primo del
    mese recupera appena torna acceso invece di saltare un mese intero —
    e più indietro no, perché un resoconto di due mesi fa non lo legge nessuno.
    """
    primo = adesso.date().replace(day=1)
    scorso = (primo - timedelta(days=1)).replace(day=1)
    for candidato in (scorso, (scorso - timedelta(days=1)).replace(day=1)):
        fine = _primo_del_mese_dopo(candidato)
        if adesso >= datetime.combine(fine, time(hour=ore, minute=minuti)):
            return candidato
    return None


def _primo_del_mese_dopo(primo: date) -> date:
    return (primo.replace(day=28) + timedelta(days=4)).replace(day=1)


# — registro delle esecuzioni —


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
