"""Task e promemoria — `GET/POST /api/task`, `PATCH /api/task/{id}` (§8.2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_api.rotte.presentazione import task_item
from custode_core.dominio import task as dom
from custode_core.formato import (
    etichetta_data_lunga,
    inizio_settimana,
    plurale,
)

router = APIRouter(prefix="/api/task", tags=["task"])

Vista = Literal["scadenza", "progetto", "completati"]


def _leggi_scadenza_richiesta(testo: str | None) -> date | datetime | None:
    if not testo:
        return None
    try:
        return dom.leggi_scadenza(testo)
    except ValueError as errore:
        raise HTTPException(
            status_code=422,
            detail="Scadenza non valida: usa 2026-09-04 oppure 2026-09-04T18:00.",
        ) from errore


def _sezioni_per_scadenza(task: list[dom.Task], ora: datetime) -> list[schemi.SezioneTask]:
    oggi = ora.date()
    aperti = [t for t in task if not t.fatto]

    def sezione(titolo: str, voci: list[dom.Task], nota: str | None = None) -> schemi.SezioneTask:
        return schemi.SezioneTask(
            titolo=titolo,
            task=[task_item(t, ora) for t in voci],
            notaVuoto=nota if not voci else None,
        )

    sezioni = [
        sezione("In ritardo", [t for t in aperti if dom.in_ritardo(t, oggi)]),
        sezione("Oggi", [t for t in aperti if dom.per_oggi(t, oggi)], "Niente per oggi."),
        sezione("Prossimi sette giorni", [t for t in aperti if dom.entro_giorni(t, oggi, 7)]),
        sezione("Senza scadenza", [t for t in aperti if t.scadenza is None]),
    ]
    # Le sezioni vuote non si mostrano, tranne "Oggi" che ha una sua nota: la
    # colonna resta leggibile invece di riempirsi di intestazioni senza righe.
    return [s for s in sezioni if s.task or s.notaVuoto]


def _sezioni_completati(task: list[dom.Task], ora: datetime) -> list[schemi.SezioneTask]:
    oggi = ora.date()
    lunedi = inizio_settimana(oggi)
    chiusi = sorted(
        (t for t in task if t.fatto and t.completato_il is not None),
        key=lambda t: t.completato_il or datetime.min,
        reverse=True,
    )

    gruppi: dict[str, list[dom.Task]] = {"Chiusi oggi": [], "Questa settimana": [], "Prima": []}
    for t in chiusi:
        giorno = (t.completato_il or datetime.min).date()
        if giorno == oggi:
            gruppi["Chiusi oggi"].append(t)
        elif giorno >= lunedi:
            gruppi["Questa settimana"].append(t)
        else:
            gruppi["Prima"].append(t)

    sezioni = [
        schemi.SezioneTask(titolo=titolo, task=[task_item(t, ora) for t in voci])
        for titolo, voci in gruppi.items()
        if voci
    ]
    if not sezioni:
        return [
            schemi.SezioneTask(titolo="Completati", task=[], notaVuoto="Nessun task ancora chiuso.")
        ]
    return sezioni


def _sezioni_per_provenienza(task: list[dom.Task], ora: datetime) -> list[schemi.SezioneTask]:
    """Raggruppa gli aperti per provenienza.

    Nel modello dati non esiste (ancora) un concetto di progetto: la
    provenienza — dashboard, Telegram, piano di ripasso, regola — è l'unico
    raggruppamento che i dati permettono davvero, invece di inventarne uno.
    """
    aperti = [t for t in task if not t.fatto]
    gruppi: dict[str, list[dom.Task]] = {}
    for t in aperti:
        gruppi.setdefault(dom.ETICHETTE_ORIGINE.get(t.origine, t.origine), []).append(t)

    sezioni = [
        schemi.SezioneTask(titolo=titolo, task=[task_item(t, ora) for t in voci])
        for titolo, voci in sorted(gruppi.items(), key=lambda c: (-len(c[1]), c[0]))
    ]
    if not sezioni:
        return [schemi.SezioneTask(titolo="Aperti", task=[], notaVuoto="Nessun task aperto.")]
    return sezioni


def _titolo(aperti: int, in_ritardo: int, oggi: int) -> str:
    if aperti == 0:
        return "Nessun task aperto."
    parti = [plurale(aperti, "task aperto", "task aperti")]
    if in_ritardo:
        parti.append(f"{in_ritardo} in ritardo")
    if oggi:
        parti.append(f"{oggi} per oggi")
    return ", ".join(parti) + "."


def _avviso(task: list[dom.Task]) -> str | None:
    """Segnala i task che si continuano a rinviare invece di affrontarli."""
    ostinati = [t for t in task if not t.fatto and t.rinvii >= 3]
    if not ostinati:
        return None
    if len(ostinati) == 1:
        return f"«{ostinati[0].titolo}» è stato rinviato {ostinati[0].rinvii} volte."
    return f"{len(ostinati)} task rinviati almeno tre volte: forse vanno riformulati."


@router.get("", response_model=schemi.TaskData, response_model_exclude_none=True)
def pagina_task(conn: ConnDip, ora: OraDip, vista: Vista = "scadenza") -> schemi.TaskData:
    tutti = dom.elenco(conn)
    oggi = ora.date()
    aperti = [t for t in tutti if not t.fatto]

    if vista == "completati":
        sezioni = _sezioni_completati(tutti, ora)
    elif vista == "progetto":
        sezioni = _sezioni_per_provenienza(tutti, ora)
    else:
        sezioni = _sezioni_per_scadenza(tutti, ora)

    n_ritardo = sum(1 for t in aperti if dom.in_ritardo(t, oggi))
    n_oggi = sum(1 for t in aperti if dom.per_oggi(t, oggi))
    chiusi_settimana = dom.chiusi_per_giorno(conn, inizio_settimana(oggi))

    return schemi.TaskData(
        dataLabel=etichetta_data_lunga(ora),
        titolo=_titolo(len(aperti), n_ritardo, n_oggi),
        avviso=_avviso(tutti),
        stats=schemi.StatsTask(
            aperti=len(aperti),
            oggi=n_oggi,
            inRitardo=n_ritardo,
            chiusiSettimana=sum(chiusi_settimana),
        ),
        sezioni=sezioni,
        chiusiPerGiorno=chiusi_settimana,
        # I task ricorrenti hanno bisogno di una regola di ricorrenza, che non
        # esiste ancora: lista vuota, la dashboard non mostra il blocco.
        ricorrenti=[],
        provenienza=[
            schemi.ProvenienzaTask(origine=nome, conteggio=n)
            for nome, n in dom.conteggio_per_origine(conn)
        ],
    )


@router.post("", response_model=schemi.TaskItem, response_model_exclude_none=True, status_code=201)
def crea_task(corpo: schemi.NuovoTask, conn: ConnDip, ora: OraDip) -> schemi.TaskItem:
    titolo = corpo.titolo.strip()
    if not titolo:
        raise HTTPException(status_code=422, detail="Il titolo del task non può essere vuoto.")

    task = dom.crea(
        conn,
        titolo=titolo,
        ora=ora,
        scadenza=_leggi_scadenza_richiesta(corpo.scadenza),
    )
    return task_item(task, ora)


@router.patch("/{task_id}", response_model=schemi.TaskItem, response_model_exclude_none=True)
def modifica_task(
    task_id: int, corpo: schemi.ModificaTask, conn: ConnDip, ora: OraDip
) -> schemi.TaskItem:
    if corpo.fatto is None and corpo.rinviaGiorni is None:
        raise HTTPException(status_code=422, detail="Indica almeno `fatto` o `rinviaGiorni`.")

    try:
        task = dom.leggi(conn, task_id)
        if corpo.fatto is not None:
            task = dom.imposta_fatto(conn, task_id, corpo.fatto, ora)
        if corpo.rinviaGiorni is not None:
            task = dom.rinvia(conn, task_id, corpo.rinviaGiorni, ora)
    except dom.TaskInesistente as errore:
        raise HTTPException(status_code=404, detail="Task non trovato.") from errore
    except ValueError as errore:
        raise HTTPException(status_code=422, detail=str(errore)) from errore

    return task_item(task, ora)
