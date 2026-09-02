"""Spese — `/api/spese` (§8.5).

La pagina Spese è il posto dove si *rilegge* quello che hai speso: registrare
succede su Telegram, con una frase o una foto di scontrino (§8.1). Qui la
dashboard aggiunge due cose che sul telefono sarebbero scomode — una spesa
inserita a mano e la conferma di uno scontrino letto — e per il resto legge.

Nessun totale di questa pagina passa da un modello: somme, medie e variazioni
sono aritmetica su interi in centesimi, e la conversione a euro avviene solo
qui, al confine col contratto.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_core.dominio import spese as dom
from custode_core.formato import (
    etichetta_giorno,
    etichetta_mese,
    euro,
    inizio_settimana,
    plurale,
)
from custode_router import Router
from custode_router import assistente as dom_assistente

router = APIRouter(prefix="/api/spese", tags=["spese"])

Periodo = Literal["settimana", "mese", "anno"]

# Quanti movimenti mandare alla pagina. Il resto sta dietro il bottone "Carica
# altri movimenti": il contratto non ha un campo per il conteggio, quindi qui
# il tetto serve solo a non spedire un anno intero in una risposta.
MAX_MOVIMENTI = 50

# Quante categorie disegnare nella colonna: sotto la ottava la barretta è
# indistinguibile da zero.
MAX_CATEGORIE = 8

SENZA_CATEGORIA = "Senza categoria"


# — periodi —


def _primo_del_mese(giorno: date) -> date:
    return giorno.replace(day=1)


def _mese_precedente(primo: date) -> date:
    return _primo_del_mese(primo - timedelta(days=1))


def _inizio(periodo: Periodo, giorno: date) -> date:
    if periodo == "settimana":
        return inizio_settimana(giorno)
    if periodo == "anno":
        return date(giorno.year, 1, 1)
    return _primo_del_mese(giorno)


def _inizio_precedente(periodo: Periodo, inizio: date) -> date:
    if periodo == "settimana":
        return inizio - timedelta(weeks=1)
    if periodo == "anno":
        return date(inizio.year - 1, 1, 1)
    return _mese_precedente(inizio)


def _totale_fra(conn: ConnDip, da: date, a: date) -> int:
    return dom.totale(dom.elenco(conn, da=da, a=a))


def _euro(centesimi: float) -> float:
    """Centesimi → euro con due decimali.

    Le conversioni secche tornano già esatte; le **medie** no, e mandare al
    contratto `33.775 €` sarebbe un importo che non esiste.
    """
    return round(centesimi / 100, 2)


def _variazione(conn: ConnDip, periodo: Periodo, inizio: date, oggi: date, corrente: int) -> float:
    """Quanto sei sopra o sotto il periodo precedente, in punti percentuali.

    Il confronto è fra tratti **della stessa lunghezza**: i primi 12 giorni di
    questo mese contro i primi 12 dello scorso. Mettere 12 giorni contro 31
    darebbe sempre un crollo, e a metà mese direbbe solo che il mese non è
    finito.
    """
    trascorsi = (oggi - inizio).days
    inizio_prec = _inizio_precedente(periodo, inizio)
    precedente = _totale_fra(conn, inizio_prec, inizio_prec + timedelta(days=trascorsi))
    if precedente == 0:
        # Nessuna base di confronto: zero è più onesto di una percentuale
        # enorme calcolata su niente.
        return 0.0
    return round((corrente - precedente) / precedente * 100, 1)


def _andamento(spese: list[dom.Spesa], periodo: Periodo, inizio: date, oggi: date) -> list[int]:
    """Le barrette del grafico, in percentuale sulla colonna più alta.

    Un secchiello per giorno su settimana e mese; per l'anno uno per mese,
    altrimenti sarebbero trecento barrette da tre pixel. L'ultima colonna è
    sempre oggi (o questo mese): è quella che la pagina evidenzia.
    """
    if periodo == "anno":
        per_mese = [0] * oggi.month
        for spesa in spese:
            if spesa.giorno.year == oggi.year:
                per_mese[spesa.giorno.month - 1] += spesa.centesimi
        valori = per_mese
    else:
        valori = dom.per_giorno(spese, da=inizio, giorni=(oggi - inizio).days + 1)

    massimo = max(valori, default=0)
    if massimo == 0:
        return [0] * len(valori)
    return [round(v / massimo * 100) for v in valori]


def _confronto(conn: ConnDip, periodo: Periodo, inizio: date) -> list[schemi.ConfrontoSpese]:
    """I periodi *interi* già chiusi, per capire se questo è nella norma."""
    righe: list[schemi.ConfrontoSpese] = []
    if periodo == "settimana":
        scorsa = inizio - timedelta(weeks=1)
        righe.append(
            schemi.ConfrontoSpese(
                label="Settimana scorsa",
                importo=_euro(_totale_fra(conn, scorsa, scorsa + timedelta(days=6))),
            )
        )
        quattro = inizio - timedelta(weeks=4)
        totale = _totale_fra(conn, quattro, inizio - timedelta(days=1))
        righe.append(schemi.ConfrontoSpese(label="Media 4 settimane", importo=_euro(totale / 4)))
    elif periodo == "mese":
        scorso = _mese_precedente(inizio)
        righe.append(
            schemi.ConfrontoSpese(
                label="Mese scorso",
                importo=_euro(_totale_fra(conn, scorso, inizio - timedelta(days=1))),
            )
        )
        tre = _mese_precedente(_mese_precedente(scorso))
        totale = _totale_fra(conn, tre, inizio - timedelta(days=1))
        righe.append(schemi.ConfrontoSpese(label="Media 3 mesi", importo=_euro(totale / 3)))
    else:
        scorso = date(inizio.year - 1, 1, 1)
        righe.append(
            schemi.ConfrontoSpese(
                label="Anno scorso",
                importo=_euro(_totale_fra(conn, scorso, date(inizio.year - 1, 12, 31))),
            )
        )
    # Un confronto con periodi in cui non avevi ancora Custode direbbe solo che
    # il database è nuovo: si mostra ciò che ha davvero qualcosa dietro.
    return [riga for riga in righe if riga.importo > 0]


# — presentazione —


def movimento(spesa: dom.Spesa, oggi: date) -> schemi.Movimento:
    return schemi.Movimento(
        id=str(spesa.id),
        dataLabel=etichetta_giorno(spesa.giorno, oggi),
        descrizione=spesa.descrizione,
        categoria=spesa.categoria or SENZA_CATEGORIA,
        importo=spesa.euro,
        daScontrino=spesa.fonte is dom.Fonte.SCONTRINO or None,
    )


def _in_attesa(conn: ConnDip, oggi: date) -> schemi.ScontrinoInAttesa | None:
    """Il più recente scontrino che aspetta un sì. Assente se non ce n'è."""
    attesa = dom.in_attesa(conn)
    if not attesa:
        return None
    spesa = attesa[0]
    return schemi.ScontrinoInAttesa(
        id=str(spesa.id),
        luogo=spesa.luogo or spesa.descrizione,
        importo=spesa.euro,
        categoriaProposta=spesa.categoria or SENZA_CATEGORIA,
        dataLabel=etichetta_giorno(spesa.giorno, oggi),
    )


def _etichetta_periodo(periodo: Periodo, inizio: date, oggi: date) -> str:
    if periodo == "settimana":
        return "questa settimana"
    if periodo == "anno":
        return str(oggi.year)
    return etichetta_mese(inizio, oggi)


def _titolo(centesimi: int, quante: int, periodo: Periodo) -> str:
    if quante == 0:
        return "Nessuna spesa in questo periodo."
    quando = {"settimana": "questa settimana", "mese": "questo mese", "anno": "quest'anno"}
    return f"{euro(centesimi)} {quando[periodo]}, in {plurale(quante, 'spesa', 'spese')}."


def _nota_categorie(spese: list[dom.Spesa]) -> str | None:
    """Detto solo quando c'è qualcosa da sistemare."""
    senza = [s for s in spese if not s.categoria]
    if not senza:
        return None
    return (
        f"{plurale(len(senza), 'spesa non ha', 'spese non hanno')} ancora una categoria:"
        " succede quando il modello non era raggiungibile al momento della registrazione."
    )


@router.get("", response_model=schemi.SpeseData, response_model_exclude_none=True)
def pagina_spese(conn: ConnDip, ora: OraDip, periodo: Periodo = "mese") -> schemi.SpeseData:
    oggi = ora.date()
    inizio = _inizio(periodo, oggi)
    del_periodo = dom.elenco(conn, da=inizio, a=oggi)

    centesimi = dom.totale(del_periodo)
    giorni = (oggi - inizio).days + 1
    per_categoria = dom.per_categoria(del_periodo)

    return schemi.SpeseData(
        periodoLabel=_etichetta_periodo(periodo, inizio, oggi),
        titolo=_titolo(centesimi, len(del_periodo), periodo),
        scontrinoInAttesa=_in_attesa(conn, oggi),
        stats=schemi.StatsSpese(
            totaleMese=_euro(centesimi),
            # Sui giorni *trascorsi*, non su quelli del mese: a inizio mese
            # dividere per 31 darebbe una media che non è ancora un dato.
            mediaGiorno=_euro(centesimi / giorni),
            categoriaMaggiore=per_categoria[0][0] if per_categoria else "—",
            variazioneMesePrecedente=_variazione(conn, periodo, inizio, oggi, centesimi),
        ),
        andamentoGiorni=_andamento(del_periodo, periodo, inizio, oggi),
        movimenti=[movimento(s, oggi) for s in del_periodo[:MAX_MOVIMENTI]],
        categorie=[
            schemi.CategoriaSpesa(nome=nome, importo=_euro(cent), quota=cent / centesimi)
            for nome, cent in per_categoria[:MAX_CATEGORIE]
        ]
        if centesimi
        else [],
        categoriaNota=_nota_categorie(del_periodo),
        confronto=_confronto(conn, periodo, inizio),
    )


@router.post("", response_model=schemi.Movimento, response_model_exclude_none=True)
def registra_spesa(
    corpo: schemi.NuovaSpesa, richiesta: Request, conn: ConnDip, ora: OraDip
) -> schemi.Movimento:
    """Una spesa scritta a mano dalla dashboard: entra subito nei conti (§8.5)."""
    try:
        spesa = dom.registra(
            conn,
            centesimi=dom.in_centesimi(corpo.importo),
            descrizione=corpo.descrizione,
            ora=ora,
            categoria=corpo.categoria,
            # Il nome l'hai scritto tu nella dashboard, non l'ha proposto un
            # modello: la differenza si vede quando si fa ordine fra le
            # categorie.
            categoria_da_utente=True,
        )
    except ValueError as errore:
        raise HTTPException(status_code=422, detail=str(errore)) from errore

    if not corpo.categoria:
        # Stessa strada del bot: la categoria la propone Claude confrontando
        # con quelle che già usi. Se non risponde la spesa resta lì, senza.
        instradatore: Router = richiesta.app.state.router
        dom_assistente.categorizza_se_serve(conn, ora, spesa.id, instradatore)
        spesa = dom.leggi(conn, spesa.id)
    return movimento(spesa, ora.date())


@router.post(
    "/{spesa_id}/conferma", response_model=schemi.Movimento, response_model_exclude_none=True
)
def conferma_scontrino(
    spesa_id: int, corpo: schemi.ConfermaScontrino, conn: ConnDip, ora: OraDip
) -> schemi.Movimento:
    """Fa entrare nei conti uno scontrino letto da foto, con l'ultima parola sulla categoria."""
    try:
        spesa = dom.conferma(conn, spesa_id, ora, categoria=corpo.categoria)
    except dom.SpesaInesistente as errore:
        raise HTTPException(status_code=404, detail="Spesa non trovata.") from errore
    except ValueError as errore:
        raise HTTPException(status_code=409, detail=str(errore)) from errore
    return movimento(spesa, ora.date())
