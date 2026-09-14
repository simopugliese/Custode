"""Calendario — `GET /api/calendario`, `PATCH /api/calendario/{id}` (§8.10).

La pagina risponde a due domande diverse, ed è la ragione delle tre viste:
*«cosa ho questa settimana»* (settimana, mese) e *«cosa ha capito Custode»*
(da rivedere). La seconda non è una lista di eventi ma di **serie**: il tag si
decide una volta per l'intera ricorrenza, quindi mostrare dodici occorrenze
della stessa lezione sarebbe mostrare dodici volte la stessa correzione.

L'API non legge mai Google — quello è mestiere del worker (§8.10) — ma deve
sapere se le credenziali ci sono: senza, la pagina deve dire «non è collegato»
invece di «non hai impegni», che a calendario scollegato sarebbe falso.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException

from custode_api import schemi
from custode_api.dipendenze import CalendarioDip, ConnDip, OraDip
from custode_api.rotte.presentazione import (
    TIPO_LABEL,
    evento_calendario_taggato,
)
from custode_core.dominio import calendario as dom
from custode_core.formato import (
    etichetta_giorno,
    etichetta_giorno_voce,
    etichetta_mese,
    etichetta_ora,
    inizio_settimana,
    plurale,
)
from custode_core.registro_job import SYNC_CALENDARIO, ultima_esecuzione

router = APIRouter(prefix="/api/calendario", tags=["calendario"])

Vista = Literal["settimana", "mese", "da_rivedere"]

NON_COLLEGATO = (
    "Il calendario non è collegato: mancano le credenziali di Google" " (DEPLOY.md § 3-bis)."
)
NIENTE_IN_PROGRAMMA = "Niente in programma."
MAI_SINCRONIZZATO = "Non ho ancora sincronizzato nessun evento."


def _periodo(vista: Vista, oggi: date, *, giorni_avanti: int) -> tuple[date, date]:
    """I due estremi di cui la vista parla, compresi.

    La settimana è quella **corrente** (lunedì–domenica) e non i sette giorni da
    oggi: è il periodo di cui si parla con gli altri, e l'unico che dopo un
    riavvio della pagina resta lo stesso. Il mese è il mese corrente, come nel
    diario e nelle spese.

    «Da rivedere» non disegna giorni, ma un periodo ce l'ha lo stesso: da oggi
    a dove arriva la finestra sincronizzata. Serve al contatore in cima — un
    «impegni nel periodo: 0» accanto a una lista piena di proposte si
    leggerebbe come «non hai impegni», che è falso.
    """
    if vista == "da_rivedere":
        return oggi, oggi + timedelta(days=giorni_avanti)
    if vista == "mese":
        primo = oggi.replace(day=1)
        return primo, (primo + timedelta(days=31)).replace(day=1) - timedelta(days=1)
    lunedi = inizio_settimana(oggi)
    return lunedi, lunedi + timedelta(days=6)


def _etichetta_periodo(vista: Vista, da: date, a: date, oggi: date) -> str:
    if vista == "da_rivedere":
        return "da oggi in poi"
    if vista == "mese":
        return etichetta_mese(da, oggi)
    fine = f"{a.day} {etichetta_mese(a, oggi)}"
    if da.month == a.month:
        return f"{da.day}–{fine}"
    # «31–6 settembre» sarebbe un intervallo che va all'indietro: quando la
    # settimana scavalca un mese, il mese si dice due volte.
    return f"{da.day} {etichetta_mese(da, oggi)} – {fine}"


def _giorni(
    eventi: list[dom.Evento], *, da: date, a: date, oggi: date, tutti: bool
) -> list[schemi.GiornoCalendario]:
    """Una riga per giorno, con dentro gli eventi che lo **toccano**.

    Un evento lungo compare in ogni giorno che occupa: un viaggio partito
    venerdì è un impegno anche di sabato, e vederlo solo il venerdì vorrebbe
    dire cercarlo all'indietro proprio nel giorno in cui serve.

    `tutti` distingue le due viste: la settimana mostra i sette giorni anche
    vuoti — sette righe si leggono, e un giorno libero è un'informazione —
    mentre il mese manda solo i giorni che hanno qualcosa: trenta righe
    «niente in programma» non direbbero niente.
    """
    righe: list[schemi.GiornoCalendario] = []
    giorno = da
    while giorno <= a:
        del_giorno = [e for e in eventi if e.inizio.date() <= giorno <= e.fine.date()]
        if del_giorno or tutti:
            righe.append(
                schemi.GiornoCalendario(
                    label=etichetta_giorno_voce(giorno),
                    isOggi=True if giorno == oggi else None,
                    eventi=[evento_calendario_taggato(e, giorno) for e in del_giorno],
                    notaVuoto=None if del_giorno else NIENTE_IN_PROGRAMMA,
                )
            )
        giorno += timedelta(days=1)
    return righe


def _da_rivedere(conn: sqlite3.Connection, oggi: date) -> list[schemi.SerieDaRivedere]:
    return [
        schemi.SerieDaRivedere(
            id=str(serie.evento_id),
            titolo=serie.titolo,
            tipo=serie.tipo.value,
            tipoLabel=TIPO_LABEL[serie.tipo],
            quandoLabel=_quando(serie, oggi),
            occorrenzeLabel=(
                f"{plurale(serie.occorrenze, 'occorrenza', 'occorrenze')} in calendario"
                if serie.occorrenze > 1
                else None
            ),
            propostoLabel=f"proposto {etichetta_giorno(serie.proposto_il.date(), oggi)}",
            serie=bool(serie.serie_id),
        )
        for serie in dom.da_rivedere(conn, oggi)
    ]


def _quando(serie: dom.SerieDaRivedere, oggi: date) -> str:
    """ "oggi alle 09:00", "giovedì alle 11:00", "26 set alle 07:00"."""
    return f"{etichetta_giorno(serie.prossima.date(), oggi)} alle {etichetta_ora(serie.prossima)}"


def _titolo(da_rivedere: int, da_guardare: int, eventi: int) -> str:
    """La frase in cima: dice la cosa da fare, se ce n'è una."""
    if da_rivedere:
        quante = plurale(da_rivedere, "proposta da rivedere", "proposte da rivedere")
        return f"{quante[0].upper()}{quante[1:]}."
    if da_guardare:
        return "Ci sono impegni che nessuno ha ancora guardato."
    if not eventi:
        return "Niente in programma."
    return "Tutti gli impegni hanno un tipo."


def _orizzonte(calendario: CalendarioDip, oggi: date) -> str:
    """Fin dove arriva l'archivio, quando la vista guarda oltre.

    Un mese che finisce dopo la finestra sincronizzata è vuoto in fondo perché
    nessuno ha ancora guardato là, non perché quei giorni siano liberi: senza
    dirlo, la pagina mentirebbe per omissione.
    """
    ultimo = oggi + timedelta(days=calendario.giorni_avanti)
    return f"Gli eventi arrivano fino al {etichetta_giorno_voce(ultimo).lower()}."


@router.get("", response_model=schemi.CalendarioData, response_model_exclude_none=True)
def pagina_calendario(
    conn: ConnDip,
    ora: OraDip,
    impostazioni_calendario: CalendarioDip,
    vista: Vista = "settimana",
) -> schemi.CalendarioData:
    oggi = ora.date()
    if not impostazioni_calendario.configurato():
        return _scollegato(vista, oggi)

    da, a = _periodo(vista, oggi, giorni_avanti=impostazioni_calendario.giorni_avanti)
    eventi = dom.fra(conn, da, a)
    righe = (
        _giorni(eventi, da=da, a=a, oggi=oggi, tutti=vista == "settimana")
        if vista != "da_rivedere"
        else []
    )
    coda = _da_rivedere(conn, oggi)

    # La coda e ciò che resta da guardare parlano di tutto l'archivio da oggi in
    # poi, non della vista: «due proposte da rivedere» deve restare vero anche
    # mentre guardi una settimana in cui non ce n'è nessuna, o non ci si
    # arriverebbe mai — è la riga che porta sulla terza vista.
    da_guardare = len(dom.gruppi_senza_tag(conn))

    return schemi.CalendarioData(
        periodoLabel=_etichetta_periodo(vista, da, a, oggi),
        titolo=_titolo(len(coda), da_guardare, len(eventi)),
        stats=schemi.StatsCalendario(
            eventiPeriodo=len(eventi),
            daRivedere=len(coda),
            daGuardare=da_guardare,
        ),
        tipi=_tipi(),
        giorni=righe,
        daRivedere=coda,
        notaVuoto=_nota_vuoto(conn, vista, righe=righe, coda=coda),
        orizzonteLabel=_orizzonte(impostazioni_calendario, oggi),
    )


def _tipi() -> list[schemi.TipoEvento]:
    return [schemi.TipoEvento(valore=tipo.value, label=TIPO_LABEL[tipo]) for tipo in dom.Tipo]


def _scollegato(vista: Vista, oggi: date) -> schemi.CalendarioData:
    """La pagina senza credenziali: esiste, ed è l'unica cosa che ha da dire.

    Niente eventi e niente numeri, nemmeno se in archivio è rimasto qualcosa da
    quando era collegato: mostrarli come «i tuoi impegni» direbbe che il
    calendario sta funzionando, mentre è fermo all'ultima sincronizzazione. I
    quattro tipi restano — sono il contratto della pagina, non un dato del
    calendario.
    """
    da, a = _periodo(vista, oggi, giorni_avanti=0)
    return schemi.CalendarioData(
        periodoLabel=_etichetta_periodo(vista, da, a, oggi),
        titolo="Il calendario non è collegato.",
        stats=schemi.StatsCalendario(eventiPeriodo=0, daRivedere=0, daGuardare=0),
        tipi=_tipi(),
        notaVuoto=NON_COLLEGATO,
    )


def _nota_vuoto(
    conn: sqlite3.Connection,
    vista: Vista,
    *,
    righe: list[schemi.GiornoCalendario],
    coda: list[schemi.SerieDaRivedere],
) -> str | None:
    """Cosa scrivere al posto della lista, e *perché* è vuota.

    Due vuoti che si somigliano e non vogliono dire la stessa cosa: il
    calendario collegato che non ha ancora sincronizzato, e il periodo davvero
    libero. Dire il secondo al posto del primo sarebbe falso, visto che il
    worker sincronizza ogni cinque minuti.
    """
    if vista == "da_rivedere" and coda:
        return None
    if vista != "da_rivedere" and any(giorno.eventi for giorno in righe):
        return None
    if ultima_esecuzione(conn, SYNC_CALENDARIO) is None:
        return MAI_SINCRONIZZATO
    return "Nessuna proposta da rivedere." if vista == "da_rivedere" else NIENTE_IN_PROGRAMMA


@router.patch("/{evento_id}", response_model=schemi.CorrezioneTag, response_model_exclude_none=True)
def correggi(
    evento_id: int, corpo: schemi.CorreggiTag, conn: ConnDip, ora: OraDip
) -> schemi.CorrezioneTag:
    """Il «tu correggi se serve» di §8.10.

    Tocca tutta la serie, non la sola occorrenza che hai davanti: il tipo è una
    proprietà della ricorrenza, e correggere il martedì lasciando sbagliati gli
    altri martedì sarebbe una correzione che non regge fino alla settimana dopo.
    """
    try:
        toccate = dom.correggi_tag(conn, evento_id, dom.Tipo(corpo.tipo), ora)
    except dom.EventoInesistente as errore:
        raise HTTPException(status_code=404, detail="Evento non trovato.") from errore

    evento = dom.per_id(conn, evento_id)
    return schemi.CorrezioneTag(
        evento=evento_calendario_taggato(evento, ora.date()),
        occorrenze=toccate,
        label=(
            f"Corretto: {TIPO_LABEL[evento.tipo].lower()}."
            if toccate <= 1
            else f"Corretto su {plurale(toccate, 'occorrenza', 'occorrenze')}"
            f" della serie: {TIPO_LABEL[evento.tipo].lower()}."
        ),
    )
