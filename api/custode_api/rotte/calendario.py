"""Calendario — la pagina, la correzione dei tag e i tipi che decidi tu (§8.10).

`GET /api/calendario`, `PATCH /api/calendario/{id}`, e le tre rotte dei tipi:
`POST /api/calendario/tipi`, `PATCH|DELETE /api/calendario/tipi/{slug}`.

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
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from custode_api import schemi
from custode_api.dipendenze import CalendarioDip, ConnDip, OraDip, RouterDip
from custode_api.rotte.presentazione import evento_calendario_taggato
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
from custode_router.compiti import Compito

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
    eventi: list[dom.Evento],
    *,
    da: date,
    a: date,
    oggi: date,
    tutti: bool,
    tag: Mapping[str, dom.Tag],
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
                    eventi=[evento_calendario_taggato(e, giorno, tag) for e in del_giorno],
                    notaVuoto=None if del_giorno else NIENTE_IN_PROGRAMMA,
                )
            )
        giorno += timedelta(days=1)
    return righe


def _da_rivedere(
    conn: sqlite3.Connection, oggi: date, tag: Mapping[str, dom.Tag]
) -> list[schemi.SerieDaRivedere]:
    return [
        schemi.SerieDaRivedere(
            id=str(serie.evento_id),
            titolo=serie.titolo,
            tipo=serie.tipo,
            tipoLabel=dom.etichette(tag, serie.tipo),
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


def _da_guardare_label(quanti: int, *, tagging_acceso: bool) -> str | None:
    """Cosa aspetta gli impegni senza tipo — e se davvero li aspetta qualcosa.

    La pagina diceva «Custode li guarda al prossimo giro, che è entro cinque
    minuti» in ogni caso. È vero solo finché il compito `tag_calendario` ha una
    chiave dietro: senza, non li guarda nessuno, il numero non scende mai, e la
    frase resta lì a promettere un'attesa che non finisce. Chi legge non ha
    modo di distinguere i due casi — l'unico che lo sa è il backend, ed è il
    posto dove il contratto vuole le etichette.
    """
    if not quanti:
        return None
    quanti_label = plurale(quanti, "impegno non ha", "impegni non hanno")
    # Il pronome segue il numero: «1 impegno … Custode li guarda» è la frase
    # che viene da sé mettendo insieme due pezzi scritti in momenti diversi, e
    # si legge come una frase generata invece che scritta.
    pronome = "lo" if quanti == 1 else "li"
    if not tagging_acceso:
        return (
            f"{quanti_label} ancora un tipo, e per ora non {pronome} guarda nessuno:"
            " manca la chiave del modello (ROUTER_DEEPSEEK_API_KEY, DEPLOY.md)."
            " Il tipo puoi metterlo a mano da qui, o dalla vista di un giorno."
        )
    return (
        f"{quanti_label} ancora un tipo:"
        f" Custode {pronome} guarda al prossimo giro, entro cinque minuti."
    )


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
    instradatore: RouterDip,
    vista: Vista = "settimana",
) -> schemi.CalendarioData:
    oggi = ora.date()
    # I tipi si leggono anche a calendario scollegato: sono il contratto della
    # pagina, non un dato del calendario — e sono anche l'unica cosa che si può
    # ancora sistemare mentre le credenziali mancano.
    tipi = _tipi(conn)
    if not impostazioni_calendario.configurato():
        return _scollegato(vista, oggi, tipi)

    tag = dom.mappa_tag(conn)
    da, a = _periodo(vista, oggi, giorni_avanti=impostazioni_calendario.giorni_avanti)
    eventi = dom.fra(conn, da, a)
    righe = (
        _giorni(eventi, da=da, a=a, oggi=oggi, tutti=vista == "settimana", tag=tag)
        if vista != "da_rivedere"
        else []
    )
    coda = _da_rivedere(conn, oggi, tag)

    # La coda e ciò che resta da guardare parlano di tutto l'archivio da oggi in
    # poi, non della vista: «due proposte da rivedere» deve restare vero anche
    # mentre guardi una settimana in cui non ce n'è nessuna, o non ci si
    # arriverebbe mai — è la riga che porta sulla terza vista.
    #
    # `dal=oggi` come per la coda, e per la stessa ragione: un impegno di marzo
    # rimasto senza tipo non è una cosa da sbrigare, e tenerlo nel contatore lo
    # lascerebbe sopra zero per sempre. Il *lavoro* del worker resta su tutto
    # l'archivio — lì il passato serve al motore di contesto — ma quello che si
    # mostra qui è una cosa da fare, e una cosa da fare che non finisce mai
    # smette di essere guardata.
    da_guardare = len(dom.gruppi_senza_tag(conn, dal=oggi))

    return schemi.CalendarioData(
        periodoLabel=_etichetta_periodo(vista, da, a, oggi),
        titolo=_titolo(len(coda), da_guardare, len(eventi)),
        stats=schemi.StatsCalendario(
            eventiPeriodo=len(eventi),
            daRivedere=len(coda),
            daGuardare=da_guardare,
        ),
        tipi=tipi,
        giorni=righe,
        daRivedere=coda,
        notaVuoto=_nota_vuoto(conn, vista, righe=righe, coda=coda),
        daGuardareLabel=_da_guardare_label(
            da_guardare,
            tagging_acceso=instradatore.configurato_per(Compito.TAG_CALENDARIO),
        ),
        orizzonteLabel=_orizzonte(impostazioni_calendario, oggi),
    )


def _tipi(conn: sqlite3.Connection) -> list[schemi.TipoEvento]:
    """I tipi come li vede la pagina: archiviati compresi, e con i loro numeri.

    Gli archiviati ci sono perché un impegno di marzo può portarne uno, e la
    sua etichetta va comunque mostrata; è il menu a offrire solo gli attivi.
    """
    quanti = dom.eventi_per_tag(conn)
    return [_tipo_evento(tag, quanti.get(tag.slug, 0)) for tag in dom.elenco_tag(conn)]


def _tipo_evento(tag: dom.Tag, eventi: int) -> schemi.TipoEvento:
    return schemi.TipoEvento(
        valore=tag.slug,
        label=tag.nome,
        descrizione=tag.descrizione,
        attivo=tag.attivo,
        diSistema=tag.di_sistema,
        eventi=eventi,
        eliminabile=not tag.di_sistema and eventi == 0,
        notaLabel=_nota_tipo(tag, eventi),
    )


def _nota_tipo(tag: dom.Tag, eventi: int) -> str:
    """Quanti impegni lo usano, e cosa se ne può fare di conseguenza.

    Una riga sola invece di un numero nudo accanto al nome: «3» in un angolo non
    dice di cosa è il conto, e uno «0» ancora meno. Detto a parole, lo stesso
    numero spiega anche perché i bottoni sono quelli che sono — il mancato
    «Elimina» su un tipo che degli impegni usano, o la mancata archiviazione su
    «Altro». Un bottone assente senza spiegazione si legge come un guasto della
    pagina.
    """
    if tag.di_sistema:
        return "Ci finisce ogni impegno appena sincronizzato: si rinomina, non si archivia."
    if not tag.attivo:
        if eventi:
            quanti = plurale(eventi, "impegno ce l'ha", "impegni ce l'hanno")
            return f"Archiviato: fuori dal menu e dal modello, ma {quanti} ancora."
        return "Archiviato: fuori dal menu e dal modello."
    if eventi:
        quanti = plurale(eventi, "impegno lo usa", "impegni lo usano")
        return f"{quanti[0].upper()}{quanti[1:]}: si archivia, non si cancella."
    return "Non lo usa nessun impegno: si può ancora cancellare."


def _scollegato(vista: Vista, oggi: date, tipi: list[schemi.TipoEvento]) -> schemi.CalendarioData:
    """La pagina senza credenziali: esiste, ed è l'unica cosa che ha da dire.

    Niente eventi e niente numeri, nemmeno se in archivio è rimasto qualcosa da
    quando era collegato: mostrarli come «i tuoi impegni» direbbe che il
    calendario sta funzionando, mentre è fermo all'ultima sincronizzazione. I
    tipi restano — sono il contratto della pagina, non un dato del calendario, e
    sono anche l'unica cosa che si può ancora sistemare da qui.
    """
    da, a = _periodo(vista, oggi, giorni_avanti=0)
    return schemi.CalendarioData(
        periodoLabel=_etichetta_periodo(vista, da, a, oggi),
        titolo="Il calendario non è collegato.",
        stats=schemi.StatsCalendario(eventiPeriodo=0, daRivedere=0, daGuardare=0),
        tipi=tipi,
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
        toccate = dom.correggi_tag(conn, evento_id, corpo.tipo, ora)
    except dom.EventoInesistente as errore:
        raise HTTPException(status_code=404, detail="Evento non trovato.") from errore
    except dom.TagInesistente as errore:
        # 422 e non 404: il 404 parla dell'evento nell'URL, questo parla del
        # corpo della richiesta — ed è lo stesso codice con cui l'API rifiuta
        # ogni altro valore che non sta nel contratto.
        raise HTTPException(
            status_code=422, detail=f"Il tipo «{corpo.tipo}» non esiste."
        ) from errore

    tag = dom.mappa_tag(conn)
    evento = dom.per_id(conn, evento_id)
    etichetta = dom.etichette(tag, evento.tipo).lower()
    return schemi.CorrezioneTag(
        evento=evento_calendario_taggato(evento, ora.date(), tag),
        occorrenze=toccate,
        label=(
            f"Corretto: {etichetta}."
            if toccate <= 1
            else f"Corretto su {plurale(toccate, 'occorrenza', 'occorrenze')}"
            f" della serie: {etichetta}."
        ),
    )


# — i tipi, adesso che li decidi tu (§8.10, pezzo 6) —
#
# Stanno qui e non in Impostazioni, ed è una scelta: i tipi si guardano dove si
# vedono gli impegni. Il menu di correzione è il posto in cui ci si accorge che
# un tipo manca, e la vista «da rivedere» è quella in cui si vede il modello
# sbagliare perché non ce l'ha. Impostazioni parla di come e quando Custode ti
# scrive, e non ha nessun blocco che parli di dati del calendario.


@router.post("/tipi", response_model=schemi.TipoEventoSalvato, response_model_exclude_none=True)
def crea_tipo(
    corpo: schemi.NuovoTipoEvento, conn: ConnDip, ora: OraDip
) -> schemi.TipoEventoSalvato:
    """Un tipo nuovo. Se lo slug esisteva archiviato, lo **riprende**.

    Ripreso e non duplicato: `palestra` e `palestra_2` spaccherebbero in due gli
    eventi già taggati, e riprenderlo lo restituisce a tutti i suoi impegni
    nello stesso istante — non l'avevano mai perso. La risposta lo dice in
    `label`, perché è una cosa diversa da quella che hai chiesto.
    """
    esistevano = {tag.slug for tag in dom.elenco_tag(conn)}
    try:
        tag = dom.crea_tag(conn, nome=corpo.nome, descrizione=corpo.descrizione, ora=ora)
    except dom.NomeTagGiaUsato as errore:
        raise HTTPException(status_code=422, detail=f"{errore}.") from errore
    except ValueError as errore:
        raise HTTPException(status_code=422, detail=f"{errore}.") from errore

    ripreso = tag.slug in esistevano
    eventi = dom.eventi_per_tag(conn).get(tag.slug, 0)
    return schemi.TipoEventoSalvato(
        tipo=_tipo_evento(tag, eventi),
        label=(
            f"Ripreso «{tag.nome}», che avevi archiviato."
            if ripreso
            else f"Creato «{tag.nome}»: Custode lo userà dal prossimo giro, entro cinque minuti."
        ),
    )


@router.patch(
    "/tipi/{slug}", response_model=schemi.TipoEventoSalvato, response_model_exclude_none=True
)
def modifica_tipo(
    slug: str, corpo: schemi.ModificaTipoEvento, conn: ConnDip
) -> schemi.TipoEventoSalvato:
    """Nome, descrizione, archiviazione. Lo slug no: quello non cambia mai.

    **Rinominare non tocca nessun evento.** Gli impegni portano lo slug e
    l'etichetta la cercano nella tabella dei tipi: cambiare nome è una riga
    sola, e la pagina la mostra nuova su tutti gli eventi appena si ricarica.
    """
    try:
        tag = dom.modifica_tag(
            conn,
            slug,
            nome=corpo.nome,
            descrizione=corpo.descrizione,
            attivo=corpo.attivo,
        )
    except dom.TagInesistente as errore:
        raise HTTPException(status_code=404, detail=f"Il tipo «{slug}» non esiste.") from errore
    except dom.TagDiSistema as errore:
        raise HTTPException(status_code=409, detail=f"{errore}.") from errore
    except dom.NomeTagGiaUsato as errore:
        raise HTTPException(status_code=422, detail=f"{errore}.") from errore
    except ValueError as errore:
        raise HTTPException(status_code=422, detail=f"{errore}.") from errore

    eventi = dom.eventi_per_tag(conn).get(tag.slug, 0)
    return schemi.TipoEventoSalvato(
        tipo=_tipo_evento(tag, eventi), label=_label_modifica(tag, corpo)
    )


def _label_modifica(tag: dom.Tag, corpo: schemi.ModificaTipoEvento) -> str:
    """Cos'è cambiato, detto come lo diresti tu.

    L'archiviazione viene prima di tutto perché è la sola che cambia dove il
    tipo *si vede*: rinominare e riscrivere la descrizione si vedono da soli
    nella riga che hai appena modificato.
    """
    if corpo.attivo is False:
        return f"«{tag.nome}» archiviato: non comparirà più nel menu."
    if corpo.attivo is True:
        return f"«{tag.nome}» ripreso: torna nel menu e fra quelli che Custode propone."
    if corpo.nome is not None:
        return (
            f"Rinominato in «{tag.nome}». Nessun impegno è cambiato: portano tutti lo stesso tipo."
        )
    return f"Descrizione di «{tag.nome}» aggiornata: Custode la userà dal prossimo giro."


@router.delete("/tipi/{slug}", status_code=204)
def elimina_tipo(slug: str, conn: ConnDip) -> Response:
    """Cancella un tipo, e solo se nessun impegno lo usa.

    409 e non 422 quando è in uso: la richiesta è scritta bene, è lo stato delle
    cose a impedirla — lo stesso codice con cui l'API rifiuta di decidere due
    volte la stessa proposta di abitudine. Il messaggio dice quanti sono e cosa
    fare al posto suo, perché un no senza alternativa è un vicolo cieco.
    """
    try:
        dom.elimina_tag(conn, slug)
    except dom.TagInesistente as errore:
        raise HTTPException(status_code=404, detail=f"Il tipo «{slug}» non esiste.") from errore
    except dom.TagDiSistema as errore:
        raise HTTPException(status_code=409, detail=f"{errore}.") from errore
    except dom.TagInUso as errore:
        quanti = plurale(errore.eventi, "impegno lo usa", "impegni lo usano")
        raise HTTPException(
            status_code=409,
            detail=f"{quanti[0].upper()}{quanti[1:]}: archivialo invece di cancellarlo.",
        ) from errore
    return Response(status_code=204)
