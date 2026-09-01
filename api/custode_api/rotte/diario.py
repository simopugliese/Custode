"""Diario — `GET /api/diario`, `POST /api/diario/{id}/approva|scarta` (§8.4).

La dashboard è il posto in cui si rilegge il diario e si smaltiscono le bozze
rimaste in sospeso; il flusso quotidiano (raccolta, riassunto, approvazione)
vive su Telegram, che è il canale principale (§8.1). Entrambi passano dagli
stessi servizi di dominio in `custode_core.dominio.diario`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_core.dominio import diario as dom
from custode_core.formato import (
    etichetta_giorno,
    etichetta_giorno_voce,
    etichetta_mese,
    etichetta_ora,
    inizio_settimana,
    plurale,
)

router = APIRouter(prefix="/api/diario", tags=["diario"])

Vista = Literal["timeline", "settimane", "mesi"]

# Quante voci mandare alla pagina: il resto è dietro "Carica il mese per
# intero", che nel contratto è `altreVociVecchie`.
MAX_VOCI = 12

# Quante settimane/mesi indietro guardare nelle viste aggregate.
SETTIMANE = 8
MESI = 6


def _periodo(vista: Vista, oggi: date) -> tuple[date, date]:
    """L'intervallo di giorni che la vista richiesta copre."""
    if vista == "settimane":
        return inizio_settimana(oggi) - timedelta(weeks=SETTIMANE - 1), oggi
    if vista == "mesi":
        primo = dom.primo_del_mese(oggi)
        for _ in range(MESI - 1):
            primo = dom.primo_del_mese(primo - timedelta(days=1))
        return primo, oggi
    return dom.primo_del_mese(oggi), oggi


def _voce(voce: dom.Voce) -> schemi.VoceDiario:
    approvata = voce.stato is dom.Stato.APPROVATA
    return schemi.VoceDiario(
        id=str(voce.id),
        dataLabel=etichetta_giorno_voce(voce.giorno),
        stato="approvata" if approvata else "da_approvare",
        approvataAlleLabel=(
            etichetta_ora(voce.approvata_il) if approvata and voce.approvata_il else None
        ),
        testo=voce.riassunto_approvato if approvata else voce.riassunto_proposto,
        tag=voce.tag,
        fonteLabel=_fonte(voce),
    )


def _fonte(voce: dom.Voce) -> str | None:
    """ "da 3 vocali e 11 messaggi" — di cosa è fatta la giornata."""
    pezzi = []
    if voce.n_vocali:
        pezzi.append(plurale(voce.n_vocali, "vocale", "vocali"))
    if voce.n_messaggi:
        pezzi.append(plurale(voce.n_messaggi, "messaggio", "messaggi"))
    return "da " + " e ".join(pezzi) if pezzi else None


def _voce_assente(giorno: date) -> schemi.VoceDiario:
    return schemi.VoceDiario(
        id=f"assente-{giorno.isoformat()}",
        dataLabel=etichetta_giorno_voce(giorno),
        stato="assente",
        tag=[],
    )


def _timeline(voci: list[dom.Voce], oggi: date) -> list[schemi.VoceDiario]:
    """Le voci del periodo più i buchi *fra* di esse, dalla più recente.

    I giorni senza voce si mostrano solo dentro l'intervallo già coperto (più
    oggi, se oggi è vuoto): su un'installazione appena avviata, riempire il mese
    di righe "nessuna voce" direbbe soltanto che il diario è nuovo.
    """
    per_giorno = {v.giorno: v for v in voci}
    if not per_giorno:
        return [_voce_assente(oggi)]

    dal_giorno = min(per_giorno)
    righe: list[schemi.VoceDiario] = []
    corrente = oggi
    while corrente >= dal_giorno:
        esistente = per_giorno.get(corrente)
        righe.append(_voce(esistente) if esistente else _voce_assente(corrente))
        corrente -= timedelta(days=1)
    return righe


def _etichetta_settimana(lunedi: date, oggi: date) -> str:
    """ "31 agosto – 6 settembre", oppure "7–13 settembre" dentro lo stesso mese.

    Il mese si ripete solo quando la settimana ne scavalca uno: «31–6 settembre»
    sarebbe un intervallo che va all'indietro.
    """
    domenica = lunedi + timedelta(days=6)
    fine = f"{domenica.day} {etichetta_mese(domenica, oggi)}"
    if lunedi.month == domenica.month:
        return f"{lunedi.day}–{fine}"
    return f"{lunedi.day} {etichetta_mese(lunedi, oggi)} – {fine}"


def _aggregate(voci: list[dom.Voce], vista: Vista, oggi: date) -> list[schemi.VoceDiario]:
    """Le viste "settimane" e "mesi": una riga per periodo, non per giorno.

    La riga di un periodo dice quante giornate contiene e con che temi. Il
    testo narrativo scritto da Claude sta in `riepilogoSettimanale`, che è dove
    il contratto lo colloca: qui servirebbe un riepilogo per *ogni* riga, cioè
    una chiamata al modello per ogni settimana mostrata.
    """
    if not voci:
        return []

    gruppi: dict[date, list[dom.Voce]] = {}
    for voce in voci:
        if voce.stato is not dom.Stato.APPROVATA:
            continue
        chiave = (
            inizio_settimana(voce.giorno)
            if vista == "settimane"
            else dom.primo_del_mese(voce.giorno)
        )
        gruppi.setdefault(chiave, []).append(voce)

    righe: list[schemi.VoceDiario] = []
    for inizio, contenute in sorted(gruppi.items(), reverse=True):
        if vista == "settimane":
            etichetta = _etichetta_settimana(inizio, oggi)
        else:
            etichetta = etichetta_mese(inizio, oggi)
        conteggio = plurale(len(contenute), "giornata scritta", "giornate scritte")
        tag = [t for t, _ in dom.conteggio_tag(contenute)][:4]
        righe.append(
            schemi.VoceDiario(
                id=f"periodo-{inizio.isoformat()}",
                dataLabel=etichetta,
                stato="approvata",
                testo=conteggio + ".",
                tag=tag,
            )
        )
    return righe


def _titolo(approvate: int, in_attesa: int, giorni: int) -> str:
    if not approvate and not in_attesa:
        return "Il diario è ancora vuoto."
    parti = [f"{approvate} {'giornata scritta' if approvate == 1 else 'giornate scritte'}"]
    parti.append(f"su {giorni}")
    frase = " ".join(parti)
    if in_attesa:
        frase += f", {plurale(in_attesa, 'voce da approvare', 'voci da approvare')}"
    return frase[0].upper() + frase[1:] + "."


@router.get("", response_model=schemi.DiarioData, response_model_exclude_none=True)
def pagina_diario(conn: ConnDip, ora: OraDip, vista: Vista = "timeline") -> schemi.DiarioData:
    oggi = ora.date()
    da, a = _periodo(vista, oggi)
    voci = dom.elenco(conn, da=da, a=a)

    # Le bozze si contano e si mostrano tutte: sono cose da sbrigare, e una
    # lasciata in sospeso il 31 non deve sparire dalla pagina il giorno dopo
    # solo perché è cambiato il mese.
    in_attesa = dom.in_attesa(conn)

    # Le statistiche e la copertura restano sempre sul mese corrente, come i
    # nomi del contratto dicono (`vociDelMese`, `coperturaMese`): la vista
    # cambia cosa si legge nella colonna, non il periodo di riferimento.
    primo = dom.primo_del_mese(oggi)
    del_mese = [v for v in voci if v.giorno >= primo]
    approvate_mese = [v for v in del_mese if v.stato is dom.Stato.APPROVATA]
    giorni_mese = dom.giorni_nel_mese(oggi)

    if vista == "timeline":
        # La timeline mostra già le bozze del periodo: qui si aggiungono solo
        # quelle rimaste indietro.
        righe = _timeline(voci, oggi) + [_voce(v) for v in in_attesa if v.giorno < da]
    else:
        # Le viste aggregate raccontano le settimane e i mesi *scritti*, quindi
        # non contengono bozze: ci vanno tutte in coda, altrimenti passando a
        # «Settimane» le cose da approvare sparirebbero dallo schermo.
        righe = _aggregate(voci, vista, oggi) + [_voce(v) for v in in_attesa]
    temi = dom.conteggio_tag(del_mese)
    massimo = temi[0][1] if temi else 0

    return schemi.DiarioData(
        periodoLabel=(
            etichetta_mese(oggi, oggi)
            if vista == "timeline"
            else f"ultime {SETTIMANE} settimane"
            if vista == "settimane"
            else f"ultimi {MESI} mesi"
        ),
        titolo=_titolo(len(approvate_mese), len(in_attesa), giorni_mese),
        vociApprovate=len(approvate_mese),
        giorniTotali=giorni_mese,
        vociInAttesa=len(in_attesa),
        stats=schemi.StatsDiario(
            vociDelMese=len(approvate_mese),
            giorniConsecutivi=dom.giorni_consecutivi(voci, oggi),
            paroleMedia=dom.parole_media(del_mese),
            temaPiuRicorrente=temi[0][0] if temi else "—",
        ),
        voci=righe[:MAX_VOCI],
        altreVociVecchie=max(len(righe) - MAX_VOCI, 0),
        temiDelMese=[
            schemi.TemaRicorrente(nome=nome, occorrenze=n, quota=n / massimo)
            for nome, n in temi[:6]
        ],
        riepilogoSettimanale=_riepilogo(conn, oggi),
        coperturaMese=dom.copertura(del_mese, da=primo, giorni=giorni_mese),
        coperturaNota=_nota_copertura(len(approvate_mese), giorni_mese, oggi),
    )


def _riepilogo(conn: ConnDip, oggi: date) -> schemi.RiepilogoDiario | None:
    """L'ultimo riepilogo scritto dal job settimanale (§8.4 punto 7).

    Assente finché il job non ne ha scritto uno: campo omesso, non vuoto, e la
    dashboard non disegna il blocco. `riepilogoMensile` resta invece sempre
    assente — un job mensile non esiste, e §8.4 non lo prevede.
    """
    ultimo = dom.ultimo_riepilogo(conn)
    if ultimo is None:
        return None
    return schemi.RiepilogoDiario(
        label=_etichetta_settimana(ultimo.settimana_inizio, oggi),
        testo=ultimo.testo,
        generatoLabel=etichetta_giorno(ultimo.generato_il.date(), oggi),
    )


def _nota_copertura(approvate: int, giorni_mese: int, oggi: date) -> str:
    trascorsi = plurale(oggi.day, "giorno passato", "giorni passati")
    if not approvate:
        return f"Nessuna giornata scritta, su {trascorsi}."
    scritte = plurale(approvate, "giornata scritta", "giornate scritte")
    return f"{scritte} su {trascorsi} — il mese ne ha {giorni_mese}."


@router.post(
    "/{voce_id}/approva", response_model=schemi.VoceDiario, response_model_exclude_none=True
)
def approva_voce(voce_id: int, conn: ConnDip, ora: OraDip) -> schemi.VoceDiario:
    try:
        voce = dom.approva(conn, voce_id, ora)
    except dom.VoceInesistente as errore:
        raise HTTPException(status_code=404, detail="Voce di diario non trovata.") from errore
    except ValueError as errore:
        raise HTTPException(
            status_code=409, detail="Questa voce non ha una bozza da approvare."
        ) from errore
    return _voce(voce)


@router.post("/{voce_id}/scarta", status_code=204)
def scarta_voce(voce_id: int, conn: ConnDip) -> Response:
    try:
        dom.scarta(conn, voce_id)
    except dom.VoceInesistente as errore:
        raise HTTPException(status_code=404, detail="Voce di diario non trovata.") from errore
    return Response(status_code=204)
