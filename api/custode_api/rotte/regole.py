"""Regole di contesto — la pagina, la pausa e lo scarto (§8.10).

`GET /api/regole`, `PATCH /api/regole/{id}`, `POST /api/regole/{id}/approva`,
`POST /api/regole/{id}/scarta`.

**Da qui non si creano.** Una regola si scrive a parole, dalla barra «A Custode»
in fondo a questa pagina o dal bot: è lo stesso interprete, quindi è la stessa
regola, e una form con cinque campi accanto a una barra che accetta «ricordami
la creatina tutti i giorni alle 19» sarebbe un secondo modo di fare la stessa
cosa, da tenere allineato al primo per sempre. Qui si guarda cosa c'è e si
decide se deve continuare a valere.

**`approva` esiste e non ha ancora niente da approvare.** Le proposte le
scriverà il job delle auto-proposte; la rotta c'è perché la transizione
`proposta → attiva` è parte della stessa macchina a stati delle altre, e
tenerla fuori vorrebbe dire spezzare un modulo su due file per una riga. Su una
regola che non è una proposta risponde `409`, che è la verità.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Response

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_core.dominio import regole as dom
from custode_core.formato import etichetta_giorno, inizio_settimana, plurale
from custode_core.registro_job import conteggi_da

router = APIRouter(prefix="/api/regole", tags=["regole"])

SPIEGAZIONE = (
    "Le regole le scrivi a parole, qui sotto o dal bot: «ricordami la creatina tutti"
    " i giorni alle 19», «mezz'ora prima di lezione dimmi di prendere il portatile»."
    " Custode le valuta da solo ogni cinque minuti, senza chiedere niente a nessun"
    " modello."
)

TIPI_TRIGGER: tuple[tuple[str, str], ...] = (
    ("orario", "a un'ora del giorno, tutti i giorni o solo in quelli che scegli"),
    ("prima_evento", "quanto vuoi prima di un impegno di un certo tipo"),
    ("dopo_evento", "appena finisce un impegno di un certo tipo, o poco dopo"),
)
"""I tre che esistono. §8.10 ne elenca un quarto, `pattern`, e non compare qui
perché non compare nemmeno nel database: sarà il trigger delle auto-proposte, e
mostrarlo adesso prometterebbe una cosa che non si può scegliere."""


def _attiva(regola: dom.Regola) -> schemi.RegolaAttiva:
    in_pausa = regola.stato is dom.Stato.PAUSA
    return schemi.RegolaAttiva(
        id=str(regola.id),
        triggerTipo=regola.trigger.value,
        nome=regola.messaggio,
        stato="pausa" if in_pausa else "attiva",
        descrizione=dom.descrizione(regola),
        # La pagina la disegna più in sordina: è lì, ma non fa niente.
        attenuata=True if in_pausa else None,
    )


def _attivita(
    conn: sqlite3.Connection, regole: list[dom.Regola], oggi: date
) -> tuple[list[schemi.VoceAttivita], int]:
    """Quante volte ha scattato ognuna questa settimana, e il totale.

    Il conto arriva da `job_runs`, la stessa tabella in cui il worker segna ogni
    scatto per non ripetersi: non c'è un secondo registro da tenere allineato, e
    il numero che leggi qui è letteralmente ciò che è stato mandato.

    La settimana è quella **corrente**, da lunedì, come nel diario e nelle
    spese: è il periodo di cui si parla, e dopo un ricaricamento della pagina
    resta lo stesso invece di scorrere.
    """
    conteggi = conteggi_da(
        conn, "regola:", datetime.combine(inizio_settimana(oggi), datetime.min.time())
    )
    voci = [
        schemi.VoceAttivita(nome=regola.messaggio, conteggio=conteggi[dom.nome_job(regola.id)])
        for regola in regole
        if conteggi.get(dom.nome_job(regola.id))
    ]
    voci.sort(key=lambda v: (-v.conteggio, v.nome))
    # Il totale conta **tutto** ciò che è scattato, anche di regole nel
    # frattempo scartate: il numero risponde a «quanto ti ha scritto Custode
    # questa settimana», e quella roba te l'ha scritta davvero.
    return voci, sum(conteggi.values())


def _titolo(attive: int, in_pausa: int) -> str:
    """La frase in cima: dice lo stato delle cose, non un saluto."""
    if not attive and not in_pausa:
        return "Non hai ancora nessuna regola."
    if not attive:
        return "Le tue regole sono tutte in pausa."
    quante = plurale(attive, "regola attiva", "regole attive")
    return f"{quante[0].upper()}{quante[1:]}."


def _nota_attivita(voci: list[schemi.VoceAttivita], regole: int) -> str | None:
    """Perché l'elenco dell'attività è vuoto, quando lo è.

    Due vuoti che si somigliano: nessuna regola scritta, e regole che
    semplicemente non sono ancora scattate in questa settimana. Dire il secondo
    al posto del primo lascerebbe a chiedersi se il motore stia funzionando.
    """
    if voci:
        return None
    if not regole:
        return None
    return "Nessuna delle tue regole è scattata da lunedì."


@router.get("", response_model=schemi.RegoleData, response_model_exclude_none=True)
def pagina_regole(conn: ConnDip, ora: OraDip) -> schemi.RegoleData:
    tutte = dom.elenco(conn)
    attive = [r for r in tutte if r.stato is dom.Stato.ATTIVA]
    in_pausa = [r for r in tutte if r.stato is dom.Stato.PAUSA]
    scartate = [r for r in tutte if r.stato is dom.Stato.SCARTATA]
    proposte = [r for r in tutte if r.stato is dom.Stato.PROPOSTA]

    voci, totale = _attivita(conn, tutte, ora.date())

    return schemi.RegoleData(
        titolo=_titolo(len(attive), len(in_pausa)),
        spiegazione=SPIEGAZIONE,
        stats=schemi.StatsRegole(
            attive=len(attive),
            daApprovare=len(proposte),
            scattateSettimana=totale,
            inPausa=len(in_pausa),
        ),
        # Le proposte hanno bisogno del job che ancora non c'è: una lista vuota
        # dice «il modulo c'è e non ha niente da dire», che è diverso da un
        # campo omesso.
        proposte=[],
        # Attive e in pausa nella stessa lista, come le disegna la pagina: sono
        # le regole che hai, e la pausa è un interruttore su ognuna, non un
        # posto diverso dove stanno.
        regoleAttive=[_attiva(r) for r in attive + in_pausa],
        attivitaSettimana=voci,
        attivitaNota=_nota_attivita(voci, len(tutte)),
        tipiTrigger=[schemi.TipoTrigger(tipo=t, descrizione=d) for t, d in TIPI_TRIGGER],
        scartate=[
            schemi.RegolaScartata(
                nome=r.messaggio,
                dataLabel=etichetta_giorno(r.creata_il.date(), ora.date()),
            )
            for r in scartate
        ],
    )


def _cambia(conn: sqlite3.Connection, regola_id: int, stato: dom.Stato) -> dom.Regola:
    try:
        return dom.imposta_stato(conn, regola_id, stato)
    except dom.RegolaInesistente as errore:
        raise HTTPException(status_code=404, detail="Regola non trovata.") from errore
    except dom.TransizioneNonValida as errore:
        # 409 e non 422: la richiesta è scritta bene, è lo stato delle cose a
        # impedirla — lo stesso codice con cui l'API rifiuta di decidere due
        # volte la stessa proposta di abitudine.
        raise HTTPException(status_code=409, detail=f"{errore}.") from errore


@router.patch("/{regola_id}", response_model=schemi.RegolaAttiva, response_model_exclude_none=True)
def modifica_regola(
    regola_id: int, corpo: schemi.ModificaRegola, conn: ConnDip
) -> schemi.RegolaAttiva:
    """Mette in pausa una regola, o la rimette in piedi.

    In pausa e non cancellata: una regola che ti ha dato fastidio questa
    settimana può servirti la prossima, e rifarla vorrebbe dire ricordarsi come
    l'avevi scritta.
    """
    stato = dom.Stato.ATTIVA if corpo.stato == "attiva" else dom.Stato.PAUSA
    return _attiva(_cambia(conn, regola_id, stato))


@router.post(
    "/{regola_id}/approva", response_model=schemi.RegolaAttiva, response_model_exclude_none=True
)
def approva_regola(regola_id: int, conn: ConnDip) -> schemi.RegolaAttiva:
    """Accetta una regola che Custode ha proposto.

    Non ha ancora niente da approvare: le proposte le scriverà il job delle
    auto-proposte. Su qualunque altra regola risponde `409`, perché approvare
    una cosa già attiva non vuol dire niente.

    Lo stato di partenza si controlla **qui e non nel dominio**: là «rimettere
    lo stato che ha già» è di proposito una non-operazione, perché due tap sullo
    stesso segmento della pagina non devono dare un errore. Approvare è un'altra
    domanda, e merita un'altra risposta.
    """
    try:
        regola = dom.per_id(conn, regola_id)
    except dom.RegolaInesistente as errore:
        raise HTTPException(status_code=404, detail="Regola non trovata.") from errore
    if regola.stato is not dom.Stato.PROPOSTA:
        raise HTTPException(
            status_code=409,
            detail=f"Questa regola non è una proposta: è «{regola.stato}».",
        )
    return _attiva(_cambia(conn, regola_id, dom.Stato.ATTIVA))


@router.post("/{regola_id}/scarta", status_code=204)
def scarta_regola(regola_id: int, conn: ConnDip) -> Response:
    """Toglie di mezzo una regola: smette di valere e non torna.

    Vale sia per una proposta che non ti interessa sia per una tua che non ti
    serve più — è la sola strada per **toglierne** una, visto che la pausa la
    lascia lì. Non si cancella: §8.10 promette che una scartata non venga
    riproposta, e mantenerla richiede che la riga resti.
    """
    _cambia(conn, regola_id, dom.Stato.SCARTATA)
    return Response(status_code=204)
