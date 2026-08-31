"""Lista della spesa — `/api/lista-spesa` (§8.3)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_api.rotte.presentazione import voce_spesa
from custode_core.dominio import lista_spesa as dom
from custode_core.formato import etichetta_ora, plurale

router = APIRouter(prefix="/api/lista-spesa", tags=["lista spesa"])

Ordinamento = Literal["reparto", "aggiunta"]


def _titolo(da_prendere: int, reparti: int) -> str:
    if da_prendere == 0:
        return "Lista della spesa vuota."
    testo = plurale(da_prendere, "voce da prendere", "voci da prendere")
    if reparti > 1:
        return f"{testo} in {plurale(reparti, 'reparto', 'reparti')}."
    return f"{testo}."


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

    return schemi.ListaSpesaData(
        aggiornataAlleLabel=etichetta_ora(ora),
        titolo=_titolo(len(da_prendere), len({v.reparto for v in da_prendere})),
        stats=schemi.StatsListaSpesa(daPrendere=len(da_prendere), presi=len(presi)),
        reparti=gruppi,
        presi=[voce_spesa(v) for v in presi],
        # Suggerimenti, ultime spese e reparti frequenti hanno bisogno dello
        # storico degli acquisti (§8.5): finché non c'è, niente da mostrare.
        suggeriti=[],
        ultimeSpese=[],
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
