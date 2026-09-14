"""Home — `GET /api/home`: il riepilogo di oggi.

La Home incrocia tutti i moduli. Qui compaiono solo quelli attivi: task,
lista della spesa, spese e calendario. Le abitudini non vengono messe a zero,
ma omesse — la dashboard non disegna il blocco finché non c'è il modulo dietro.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter

from custode_api import schemi
from custode_api.dipendenze import CalendarioDip, ConnDip, ImpostazioniDip, OraDip
from custode_api.rotte.presentazione import evento_calendario, task_item, voce_spesa
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import spese as dom_spese
from custode_core.dominio import task as dom_task
from custode_core.formato import etichetta_data_ora, inizio_settimana, plurale
from custode_core.registro_job import SYNC_CALENDARIO, ultima_esecuzione

router = APIRouter(prefix="/api/home", tags=["home"])

# La Home è un riepilogo: una lista della spesa lunghissima la trasformerebbe
# in una seconda pagina "Lista spesa". Il resto si vede nella sua pagina.
MAX_VOCI_SPESA = 8

# Le categorie della settimana sono una barra a segmenti: oltre la quinta i
# segmenti diventano sottili come una linea.
MAX_CATEGORIE_SETTIMANA = 5


def _titolo(in_ritardo: int, oggi: int, da_prendere: int) -> str:
    parti: list[str] = []
    if in_ritardo:
        parti.append(plurale(in_ritardo, "task in ritardo", "task in ritardo"))
    if oggi:
        parti.append(f"{oggi} per oggi" if in_ritardo else plurale(oggi, "task oggi", "task oggi"))
    if da_prendere:
        parti.append(plurale(da_prendere, "voce sulla lista", "voci sulla lista"))
    if not parti:
        return "Niente in sospeso."
    frase = ", ".join(parti)
    return frase[0].upper() + frase[1:] + "."


def _spese_settimana(
    spese: list[dom_spese.Spesa], budget: float | None, in_attesa: int
) -> schemi.SpeseSettimanaHome | None:
    """Il blocco «Spese · settimana», che esiste solo se hai un budget.

    Senza budget la barra non avrebbe un tetto rispetto a cui riempirsi, e
    inventarne uno sarebbe un giudizio su come spendi: il blocco resta assente
    e la Home non lo disegna (§5, campo omesso ≠ campo a zero). Il totale
    speso rimane comunque fra le statistiche in cima.
    """
    if budget is None:
        return None
    speso = dom_spese.totale(spese)
    return schemi.SpeseSettimanaHome(
        categorie=[
            schemi.CategoriaSpesa(
                nome=nome, importo=cent / 100, quota=cent / speso if speso else 0.0
            )
            for nome, cent in dom_spese.per_categoria(spese)[:MAX_CATEGORIE_SETTIMANA]
        ],
        budget=budget,
        speso=speso / 100,
        scontriniInAttesa=in_attesa,
    )


# Le due frasi che spiegano una lista vuota. Stanno qui e non nella dashboard
# perché le etichette le compone il backend (§ Convenzioni del contratto): la
# stessa distinzione servirà al digest mattutino di §8.13.
NIENTE_OGGI = "Nessun evento oggi."
NON_ANCORA_SINCRONIZZATO = "Non ho ancora sincronizzato gli eventi di oggi."


def _calendario_oggi(
    conn: sqlite3.Connection, oggi: date, configurato: bool
) -> tuple[list[schemi.CalendarEventItem] | None, str | None]:
    """Gli impegni di oggi, e la frase da mettere se non ce ne sono.

    Il blocco esiste appena ci sono le credenziali, non appena c'è un evento:
    aspettare il primo sync vorrebbe dire far comparire il blocco quindici
    minuti dopo averlo collegato, senza che niente spieghi l'attesa. Ma finché
    il worker non ha guardato nemmeno una volta, «nessun evento oggi» sarebbe
    falso — non sappiamo se la giornata è libera o se non abbiamo ancora
    chiesto — e la nota lo dice.
    """
    if not configurato:
        return None, None

    eventi = [evento_calendario(e, oggi) for e in dom_calendario.del_giorno(conn, oggi)]
    if eventi:
        return eventi, None

    mai_sincronizzato = ultima_esecuzione(conn, SYNC_CALENDARIO) is None
    return eventi, NON_ANCORA_SINCRONIZZATO if mai_sincronizzato else NIENTE_OGGI


@router.get("", response_model=schemi.HomeData, response_model_exclude_none=True)
def home(
    conn: ConnDip, ora: OraDip, impostazioni: ImpostazioniDip, calendario: CalendarioDip
) -> schemi.HomeData:
    oggi = ora.date()
    task = dom_task.elenco(conn)
    aperti = [t for t in task if not t.fatto]

    # "Oggi" include anche gli scaduti: sono la cosa che serve vedere per prima,
    # e la loro etichetta di scadenza ("ieri", "26 ago") li distingue comunque.
    in_ritardo = [t for t in aperti if dom_task.in_ritardo(t, oggi)]
    per_oggi = [t for t in aperti if dom_task.per_oggi(t, oggi)]

    da_prendere = dom_lista.elenco(conn, preso=False)

    della_settimana = dom_spese.elenco(conn, da=inizio_settimana(oggi), a=oggi)
    scontrini_in_attesa = len(dom_spese.in_attesa(conn))

    eventi_oggi, nota_calendario = _calendario_oggi(conn, oggi, calendario.configurato())

    return schemi.HomeData(
        dataLabel=etichetta_data_ora(ora),
        titolo=_titolo(len(in_ritardo), len(per_oggi), len(da_prendere)),
        stats=schemi.StatsHome(
            taskAperti=len(aperti),
            listaSpesaDaPrendere=len(da_prendere),
            spesaSettimana=dom_spese.totale(della_settimana) / 100,
        ),
        taskOggi=[task_item(t, ora) for t in in_ritardo + per_oggi],
        calendarioOggi=eventi_oggi,
        calendarioNotaVuoto=nota_calendario,
        listaSpesa=[voce_spesa(v) for v in da_prendere[:MAX_VOCI_SPESA]],
        speseSettimana=_spese_settimana(
            della_settimana, impostazioni.budget_settimanale, scontrini_in_attesa
        ),
    )
