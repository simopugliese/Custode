"""Trasformazione dal dominio alle risposte del contratto.

Sta a parte dalle rotte perché Home e Task mostrano le stesse righe: la regola
"un task rinviato tre volte si mostra come «rinviato 3×»" va scritta una volta.
"""

from __future__ import annotations

from datetime import datetime

from custode_api import schemi
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import task as dom_task
from custode_core.formato import etichetta_scadenza

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
