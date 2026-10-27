"""Meteo — `PUT /api/posizione`, `GET /api/meteo` (§8.12).

**Niente archivio.** La previsione si chiede a Open-Meteo quando la pagina la
chiede; di ieri non resta niente. Resta solo l'ultima posizione (tabella
`posizione`), perché il digest del mattino gira sul Pi senza nessun browser e
deve sapere dove sei.

**Se il servizio non risponde, la pagina lo dice** (`502`) invece di mostrare un
meteo vecchio o inventato: è la stessa regola della dashboard, nessun dato finto.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from custode_api import schemi
from custode_api.dipendenze import ConnDip, ImpostazioniDip, MeteoDip, OraDip, SorgenteMeteoDip
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import posizione as dom_posizione
from custode_core.formato import etichetta_da_quando, etichetta_giorno, etichetta_ora
from custode_meteo import MeteoNonRaggiungibile
from custode_meteo.testo import descrizione, frase_ombrello

router = APIRouter(tags=["meteo"])

DOPO_QUANTE_ORE_E_VECCHIA = 48
"""Oltre due giorni la posizione resta quella che usiamo, ma la pagina lo dice:
potresti essere altrove."""

NON_SO_DOVE_SEI = (
    "Non so dove sei: apri la dashboard e concedi la posizione al browser,"
    " oppure imposta METEO_CASA_LAT e METEO_CASA_LON."
)


@router.put("/api/posizione", status_code=204)
def imposta_posizione(corpo: schemi.PosizioneIn, conn: ConnDip, ora: OraDip) -> Response:
    dom_posizione.salva(conn, corpo.lat, corpo.lon, ora)
    return Response(status_code=204)


@router.get("/api/meteo", response_model=schemi.MeteoData, response_model_exclude_none=True)
def meteo(
    conn: ConnDip,
    ora: OraDip,
    impostazioni: ImpostazioniDip,
    casa: MeteoDip,
    sorgente: SorgenteMeteoDip,
) -> schemi.MeteoData:
    salvata = dom_posizione.leggi(conn)
    punto = (salvata.lat, salvata.lon) if salvata is not None else casa.casa()
    if punto is None:
        return schemi.MeteoData(notaLabel=NON_SO_DOVE_SEI)
    lat, lon = punto

    try:
        previsioni = sorgente.previsioni(lat, lon, casa.giorni, impostazioni.timezone)
    except MeteoNonRaggiungibile as errore:
        raise HTTPException(
            status_code=502, detail="Il servizio meteo non risponde: riprova fra poco."
        ) from errore

    oggi = ora.date()
    righe = [
        schemi.PrevisioneGiorno(
            giornoLabel=etichetta_giorno(p.giorno, oggi),
            descrizione=descrizione(p.codice),
            minima=round(p.minima),
            massima=round(p.massima),
            probPioggia=p.prob_pioggia,
        )
        for p in previsioni
    ]

    prob_oggi = next((p.prob_pioggia for p in previsioni if p.giorno == oggi), None)
    impegno = next(
        (
            (etichetta_ora(e.inizio), e.titolo)
            for e in dom_calendario.del_giorno(conn, oggi)
            if not e.tutto_il_giorno and e.inizio >= ora
        ),
        None,
    )

    # Fresca, la posizione non ha bisogno di una riga: è dove sei. Le altre due
    # dicono di che posto parla il meteo, perché potrebbe non essere il tuo.
    posizione = None
    if salvata is None:
        posizione = "casa"
    elif salvata.eta(ora) > DOPO_QUANTE_ORE_E_VECCHIA:
        posizione = f"ultima posizione: {etichetta_da_quando(salvata.aggiornata_il, ora)}"
    return schemi.MeteoData(
        previsioni=righe,
        consiglioLabel=frase_ombrello(prob_oggi, impegno),
        posizioneLabel=posizione,
    )
