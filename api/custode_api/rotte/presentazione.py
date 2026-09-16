"""Trasformazione dal dominio alle risposte del contratto.

Sta a parte dalle rotte perché Home e Task mostrano le stesse righe: la regola
"un task rinviato tre volte si mostra come «rinviato 3×»" va scritta una volta.
"""

from __future__ import annotations

from collections.abc import Mapping
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


# Le etichette dei tipi non stanno più qui (pezzo 6): un tipo è una riga di
# `calendar_tags`, e il suo nome lo si cambia quando si vuole. Chi compone una
# pagina legge la mappa una volta — `dom_calendario.mappa_tag` — e la passa a
# ogni riga: una JOIN per evento costerebbe una query ogni riga per una tabella
# che ne ha cinque.

# I tre stati del tag (§8.10), e come si dicono. «Da guardare» non è un difetto:
# è il minuto fra la sincronizzazione e il giro di tagging — o tutto il tempo in
# cui manca la chiave del modello.
STATO_DA_GUARDARE = ("da_guardare", "da guardare")
STATO_PROPOSTO = ("proposto", "proposto dall'IA")
STATO_CORRETTO = ("corretto", "corretto da te")


def stato_tag(evento: dom_calendario.Evento) -> tuple[str, str]:
    """Chi ha deciso il tipo di questo evento, se qualcuno l'ha deciso.

    `tipo` da solo non basta: `'altro'` è sia il default di un evento appena
    sincronizzato sia un esito legittimo del modello, e distinguerli è proprio
    la domanda «cosa ha capito» a cui la pagina risponde.
    """
    if evento.tag_proposto_il is None:
        return STATO_DA_GUARDARE
    return STATO_CORRETTO if evento.tag_confermato_da_te else STATO_PROPOSTO


def evento_calendario_taggato(
    evento: dom_calendario.Evento, oggi: date, tag: Mapping[str, dom_calendario.Tag]
) -> schemi.EventoCalendario:
    """La riga della pagina Calendario: quella di Home, più il tag e il suo stato.

    `tag` è la mappa slug → tipo letta una volta per richiesta: un evento porta
    lo slug, l'etichetta sta nella tabella dei tipi, e nel mezzo può esserci una
    rinomina fatta un minuto fa.
    """
    base = evento_calendario(evento, oggi)
    stato, stato_label = stato_tag(evento)
    return schemi.EventoCalendario(
        **base.model_dump(),
        tipo=evento.tipo,
        tipoLabel=dom_calendario.etichette(tag, evento.tipo),
        statoTag=stato,
        statoTagLabel=stato_label,
        serie=bool(evento.serie_id),
    )
