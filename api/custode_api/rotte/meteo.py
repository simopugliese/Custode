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
from custode_core.dominio import meteo as dom_meteo
from custode_core.dominio import posizione as dom_posizione
from custode_core.formato import etichetta_giorno
from custode_meteo import MeteoNonRaggiungibile
from custode_meteo.testo import descrizione, frase_ombrello, icona

router = APIRouter(tags=["meteo"])

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
    dove = dom_meteo.punto(conn, casa.casa(), ora)
    if dove is None:
        return schemi.MeteoData(notaLabel=NON_SO_DOVE_SEI)
    lat, lon, posizione = dove

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
            icona=icona(p.codice),
            minima=round(p.minima),
            massima=round(p.massima),
            probPioggia=p.prob_pioggia,
        )
        for p in previsioni
    ]
    prob_oggi = next((p.prob_pioggia for p in previsioni if p.giorno == oggi), None)
    return schemi.MeteoData(
        previsioni=righe,
        consiglioLabel=frase_ombrello(prob_oggi, dom_meteo.prossimo_impegno(conn, ora)),
        posizioneLabel=posizione,
    )
