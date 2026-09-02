"""Lista della spesa — `/api/lista-spesa` (§8.3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_api.rotte.presentazione import voce_spesa
from custode_core.dominio import lista_spesa as dom
from custode_core.dominio import spese as dom_spese
from custode_core.formato import etichetta_giorno, etichetta_ora, plurale

router = APIRouter(prefix="/api/lista-spesa", tags=["lista spesa"])

Ordinamento = Literal["reparto", "aggiunta"]

# Quante spese passate mostrare nella colonna di destra.
MAX_ULTIME_SPESE = 5

# Fin dove guardare indietro per "ultime spese" e "ultima spesa": mezzo anno
# copre anche chi registra di rado, senza scorrere l'archivio intero.
GIORNI_STORICO = 180


def _titolo(da_prendere: int, reparti: int) -> str:
    if da_prendere == 0:
        return "Lista della spesa vuota."
    testo = plurale(da_prendere, "voce da prendere", "voci da prendere")
    if reparti > 1:
        return f"{testo} in {plurale(reparti, 'reparto', 'reparti')}."
    return f"{testo}."


def _uscite_con_luogo(conn: ConnDip, oggi: date) -> list[dom_spese.Spesa]:
    """Le spese in cui si sa *dove* sei stato: quelle che somigliano a una spesa fatta.

    Il luogo è il filtro giusto per questa pagina: «40 € alla Coop» e uno
    scontrino sono uscite di casa, «8 € di colazione» detto senza posto no. La
    dashboard mostra proprio il luogo in quella colonna, quindi una spesa che
    non ce l'ha non avrebbe nulla da farci vedere.
    """
    da = oggi - timedelta(days=GIORNI_STORICO)
    return [s for s in dom_spese.elenco(conn, da=da, a=oggi) if s.luogo]


@router.get("", response_model=schemi.ListaSpesaData, response_model_exclude_none=True)
def pagina_lista_spesa(
    conn: ConnDip, ora: OraDip, ordina: Ordinamento = "reparto"
) -> schemi.ListaSpesaData:
    da_prendere = dom.elenco(conn, preso=False)
    presi = dom.elenco(conn, preso=True)

    if ordina == "reparto":
        gruppi = [
            schemi.RepartoListaSpesa(nome=nome, voci=[voce_spesa(v) for v in voci])
            for nome, voci in dom.per_reparto(da_prendere)
        ]
    else:
        # Ordine di aggiunta: una sola sezione, così si legge come la si è scritta.
        gruppi = (
            [
                schemi.RepartoListaSpesa(
                    nome="Da prendere", voci=[voce_spesa(v) for v in da_prendere]
                )
            ]
            if da_prendere
            else []
        )

    oggi = ora.date()
    uscite = _uscite_con_luogo(conn, oggi)

    return schemi.ListaSpesaData(
        aggiornataAlleLabel=etichetta_ora(ora),
        titolo=_titolo(len(da_prendere), len({v.reparto for v in da_prendere})),
        stats=schemi.StatsListaSpesa(
            daPrendere=len(da_prendere),
            presi=len(presi),
            # `stimaCarrello` resta assente: stimare quanto costerà questo
            # carrello vorrebbe i prezzi delle singole voci, e §8.5 ha deciso
            # di tenere degli scontrini solo il totale. Un numero inventato su
            # dei soldi è peggio del trattino che la dashboard mostra al suo
            # posto.
            ultimaSpesaGiorni=dom_spese.giorni_dall_ultima(uscite, oggi),
        ),
        reparti=gruppi,
        presi=[voce_spesa(v) for v in presi],
        # I suggerimenti («ricompri il caffè ogni tre settimane») e i reparti
        # frequenti vogliono lo storico della *lista*, non delle spese: oggi
        # `svuota_presi` cancella le voci prese, quindi non c'è niente da cui
        # ricavare una frequenza. Restano vuoti finché §8.3 non lo conserva.
        suggeriti=[],
        ultimeSpese=[
            schemi.SpesaRecente(
                dataLabel=etichetta_giorno(s.giorno, oggi),
                luogo=s.luogo or s.descrizione,
                importo=s.euro,
            )
            for s in uscite[:MAX_ULTIME_SPESE]
        ],
        repartiFrequenti=[],
    )


@router.post(
    "", response_model=schemi.ShoppingItem, response_model_exclude_none=True, status_code=201
)
def aggiungi_voce(corpo: schemi.NuovaVoceSpesa, conn: ConnDip, ora: OraDip) -> schemi.ShoppingItem:
    try:
        voce = dom.aggiungi(
            conn, nome=corpo.nome, ora=ora, quantita=corpo.quantita, reparto=corpo.reparto
        )
    except ValueError as errore:
        raise HTTPException(status_code=422, detail=str(errore)) from errore
    return voce_spesa(voce)


@router.post("/svuota-presi", status_code=204)
def svuota_presi(conn: ConnDip) -> Response:
    dom.svuota_presi(conn)
    return Response(status_code=204)


@router.patch("/{voce_id}", response_model=schemi.ShoppingItem, response_model_exclude_none=True)
def modifica_voce(
    voce_id: int, corpo: schemi.ModificaVoceSpesa, conn: ConnDip, ora: OraDip
) -> schemi.ShoppingItem:
    try:
        voce = dom.imposta_preso(conn, voce_id, corpo.preso, ora)
    except dom.VoceInesistente as errore:
        raise HTTPException(status_code=404, detail="Voce non trovata.") from errore
    return voce_spesa(voce)
