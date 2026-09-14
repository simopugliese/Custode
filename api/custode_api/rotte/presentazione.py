"""Trasformazione dal dominio alle risposte del contratto.

Sta a parte dalle rotte perché Home e Task mostrano le stesse righe: la regola
"un task rinviato tre volte si mostra come «rinviato 3×»" va scritta una volta.
"""

from __future__ import annotations

from datetime import date, datetime

from custode_api import schemi
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import task as dom_task
from custode_core.formato import etichetta_ora, etichetta_scadenza

META_ORIGINE = {
    "piano_ripasso": "da piano di ripasso",
    "regola": "da una regola",
}


def task_item(task: dom_task.Task, ora: datetime) -> schemi.TaskItem:
    return schemi.TaskItem(
        id=str(task.id),
        titolo=task.titolo,
        fatto=task.fatto,
        scadenzaLabel=etichetta_scadenza(task.scadenza, ora),
        meta=META_ORIGINE.get(task.origine),
        tag=f"rinviato {task.rinvii}×" if task.rinvii else None,
        rinvii=task.rinvii or None,
    )


def voce_spesa(voce: dom_lista.Voce) -> schemi.ShoppingItem:
    return schemi.ShoppingItem(
        id=str(voce.id),
        nome=voce.nome,
        preso=voce.preso,
        quantita=voce.quantita,
        reparto=voce.reparto,
    )


# La colonna dell'ora in Home è larga quanto «09:00». Un evento che un'ora non
# ce l'ha ci mette un trattino e dice a parole cos'è, nella colonna di destra:
# allargare la colonna per la minoranza degli eventi spaierebbe tutti gli altri.
SENZA_ORA = "—"


def evento_calendario(evento: dom_calendario.Evento, oggi: date) -> schemi.CalendarEventItem:
    """Una riga del calendario di oggi.

    Tre casi, e tutti e tre dicono la verità su quando l'evento sta:
    - comincia oggi a un'ora → l'ora, e il luogo resta visibile;
    - è di giornata → «tutto il giorno», che vale anche per il giorno di mezzo
      di una vacanza di tre;
    - è cominciato prima di oggi ed è ancora in corso → «in corso», perché
      l'ora d'inizio è di un altro giorno e mostrarla qui direbbe una cosa falsa.
    """
    if evento.tutto_il_giorno:
        ora, meta = SENZA_ORA, "tutto il giorno"
    elif evento.giorno < oggi:
        ora, meta = SENZA_ORA, "in corso"
    else:
        ora, meta = etichetta_ora(evento.inizio), None

    return schemi.CalendarEventItem(
        id=str(evento.id),
        ora=ora,
        titolo=evento.titolo,
        luogo=evento.luogo or None,
        meta=meta,
    )
