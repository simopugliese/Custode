"""Abitudini — `/api/abitudini` (§8.6).

Qui si **legge** come stai andando e si segna il giorno con una spunta; le
abitudini si aggiungono e si modificano da questa stessa pagina, perché il bot
segna e basta e da qualche parte bisogna pur poterle creare.

Nessun numero di questa pagina passa da un modello: aderenza, obiettivi
centrati, strisce e costanza sono aritmetica su insiemi di date, fatta in
`custode_core.dominio.abitudini` e provata lì. §8.6 lo chiede esplicitamente, e
un modello che ricalcola una percentuale la sbaglia ogni tanto senza dirlo. Il
solo pezzo scritto da Claude è il **report narrativo**, che arriva già scritto
dal worker e qui viene solo riletto.

**I sette pallini sono sempre la settimana corrente**, in tutte e due le viste:
l'intestazione della colonna nella dashboard dice «Lun – Dom» ed è fissa. Quello
che cambia con `vista` sono le etichette dell'obiettivo, gli obiettivi centrati
e il periodo su cui si conta l'aderenza.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from custode_api import schemi
from custode_api.dipendenze import ConnDip, OraDip
from custode_core.dominio import abitudini as dom
from custode_core.formato import etichetta_mese, inizio_settimana, plurale

router = APIRouter(prefix="/api/abitudini", tags=["abitudini"])

Vista = Literal["settimana", "mese"]

# Sotto questa soglia un'abitudine non è «in calo», è solo una settimana
# storta: l'avviso in cima alla pagina deve voler dire qualcosa.
GIORNI_SENZA_LOG_PER_AVVISO = 10


# — periodo —


def _intervallo(vista: Vista, oggi: date) -> tuple[date, date]:
    """Da quando a quando si contano i fatti, per la vista scelta.

    Entrambi finiscono **a oggi** e non alla fine del periodo: contare i giorni
    che devono ancora arrivare farebbe apparire ogni lunedì come un disastro.
    """
    if vista == "mese":
        return oggi.replace(day=1), oggi
    return inizio_settimana(oggi), oggi


def _settimana(oggi: date) -> list[date]:
    """I sette giorni della settimana corrente, lunedì → domenica."""
    lunedi = inizio_settimana(oggi)
    return dom.giorni_fra(lunedi, lunedi + timedelta(days=6))


# — presentazione —


def _frequenza_label(target: int) -> str:
    if target == dom.GIORNI_SETTIMANA:
        return "tutti i giorni"
    return f"{plurale(target, 'volta', 'volte')} a settimana"


def _riga(
    abitudine: dom.Abitudine,
    *,
    fatti: set[date],
    vista: Vista,
    da: date,
    oggi: date,
    segnata_oggi: bool,
) -> schemi.AbitudineDettaglio:
    nel_periodo = len([g for g in fatti if da <= g <= oggi])
    # Nella vista settimanale il denominatore è il target pieno, tondo e
    # riconoscibile («2/3»); nel mese è quello proporzionale ai giorni
    # trascorsi, arrotondato, perché «8/12» si legge e «8/12.86» no — e mai
    # sotto 1, altrimenti il primo del mese si leggerebbe «0/0».
    denominatore = (
        abitudine.target_settimanale
        if vista == "settimana"
        else max(1, round(dom.attesi(abitudine.target_settimanale, (oggi - da).days + 1)))
    )
    # «Centrato» è esattamente ciò che si legge nella riga. Valutarlo sul
    # pro-rata dei giorni trascorsi darebbe una riga verde accanto a un «1/3»,
    # e un numero che si contraddice da solo è peggio di un numero severo.
    centrato = nel_periodo >= denominatore

    return schemi.AbitudineDettaglio(
        id=str(abitudine.id),
        nome=abitudine.nome,
        giorni=dom.presenze(fatti, _settimana(oggi)),
        progressoLabel=f"{nel_periodo} / {denominatore}",
        goalRatioLabel=f"{nel_periodo}/{denominatore}",
        evidenziata=centrato or None,
        frequenzaLabel=_frequenza_label(abitudine.target_settimanale),
        segnataOggi=segnata_oggi,
    )


def _titolo(righe: list[schemi.AbitudineDettaglio], vista: Vista) -> str:
    if not righe:
        return "Non segui ancora nessuna abitudine."
    centrate = len([r for r in righe if r.evidenziata])
    quando = "questa settimana" if vista == "settimana" else "questo mese"
    if centrate == len(righe):
        return f"Tutti gli obiettivi centrati {quando}."
    quanti = plurale(centrate, "obiettivo centrato", "obiettivi centrati")
    return f"{quanti} su {len(righe)}, {quando}."


def _avviso(
    abitudini: list[dom.Abitudine], per_abitudine: dict[int, set[date]], oggi: date
) -> str | None:
    """Detto solo quando c'è qualcosa che vale la pena guardare.

    Un avviso che compare sempre smette di essere letto dopo tre giorni: qui
    esce solo per un'abitudine che è ferma da più di una settimana, e ne esce
    **una** — la più ferma di tutte.
    """
    ferme: list[tuple[int, str]] = []
    for abitudine in abitudini:
        fatti = per_abitudine.get(abitudine.id, set())
        passati = [g for g in fatti if g <= oggi]
        if not passati:
            continue  # mai segnata: è nuova, non è in calo
        giorni = (oggi - max(passati)).days
        if giorni >= GIORNI_SENZA_LOG_PER_AVVISO:
            ferme.append((giorni, abitudine.nome))
    if not ferme:
        return None
    giorni, nome = max(ferme)
    return f"«{nome}» non la segni da {plurale(giorni, 'giorno', 'giorni')}."


def _mese_singola(
    abitudini: list[dom.Abitudine],
    per_abitudine: dict[int, set[date]],
    oggi: date,
) -> schemi.MeseAbitudine:
    """Il calendario a pallini dell'abitudine che sta andando meglio nel mese.

    Se ne mostra **una**: una griglia per ognuna sarebbe un muro di pallini in
    cui non si guarda più niente. Si sceglie la più costante perché è quella su
    cui la griglia racconta qualcosa — le altre le riassume già l'aderenza.
    """
    primo = oggi.replace(day=1)
    giorni_mese = dom.giorni_fra(primo, oggi)
    if not abitudini:
        return schemi.MeseAbitudine(
            nome="Nessuna abitudine",
            giorni=[],
            nota="Aggiungine una per vedere qui il mese giorno per giorno.",
        )

    def quante(abitudine: dom.Abitudine) -> int:
        return len([g for g in per_abitudine.get(abitudine.id, set()) if primo <= g <= oggi])

    migliore = max(abitudini, key=lambda a: (quante(a), -a.id))
    fatti = quante(migliore)
    nota = (
        f"{plurale(fatti, 'giorno', 'giorni')} su {len(giorni_mese)}"
        f" — {etichetta_mese(primo, oggi)}"
    )
    return schemi.MeseAbitudine(
        nome=migliore.nome,
        giorni=dom.presenze(per_abitudine.get(migliore.id, set()), giorni_mese),
        nota=nota,
    )


def _strisce(
    abitudini: list[dom.Abitudine], per_abitudine: dict[int, set[date]], oggi: date
) -> tuple[list[schemi.StreakAbitudine], int]:
    valori = [(a, dom.striscia(per_abitudine.get(a.id, set()), oggi)) for a in abitudini]
    migliore = max((v for _, v in valori), default=0)
    righe = [
        schemi.StreakAbitudine(
            nome=abitudine.nome,
            valoreLabel=plurale(giorni, "giorno", "giorni") if giorni else "—",
            evidenziata=(giorni == migliore and giorni > 0) or None,
            # Una riga a zero resta visibile ma spenta: toglierla nasconderebbe
            # proprio quella su cui c'è da lavorare.
            mutedRow=giorni == 0 or None,
        )
        for abitudine, giorni in valori
    ]
    return righe, migliore


def _costanza_mese(
    abitudini: list[dom.Abitudine], per_abitudine: dict[int, set[date]], oggi: date
) -> int:
    """L'aderenza media del mese, in percento. Zero se non segui niente."""
    if not abitudini:
        return 0
    primo = oggi.replace(day=1)
    giorni = (oggi - primo).days + 1
    quote = [
        dom.aderenza(
            len([g for g in per_abitudine.get(a.id, set()) if primo <= g <= oggi]),
            dom.attesi(a.target_settimanale, giorni),
        )
        for a in abitudini
    ]
    return dom.percentuale(sum(quote) / len(quote))


def _proposta(conn: ConnDip) -> schemi.PropostaAbitudine | None:
    aperta = dom.proposta_aperta(conn)
    if aperta is None:
        return None
    return schemi.PropostaAbitudine(
        id=str(aperta.id),
        titolo=(
            f"{aperta.abitudine}: da {aperta.target_attuale}"
            f" a {aperta.target_proposto} volte a settimana"
        ),
        motivazione=aperta.motivazione,
    )


def _report(conn: ConnDip, vista: Vista, oggi: date) -> schemi.ReportAbitudini | None:
    """Il racconto più recente per la vista scelta, se il worker ne ha scritto uno."""
    periodo = dom.Periodo.SETTIMANA if vista == "settimana" else dom.Periodo.MESE
    ultimo = dom.ultimo_report(conn, periodo=periodo)
    if ultimo is None:
        return None
    etichetta = (
        f"settimana del {ultimo.chiave.day} {etichetta_mese(ultimo.chiave, oggi)}"
        if periodo is dom.Periodo.SETTIMANA
        else etichetta_mese(ultimo.chiave, oggi)
    )
    return schemi.ReportAbitudini(periodoLabel=etichetta, testo=ultimo.testo)


def pagina(conn: ConnDip, oggi: date, vista: Vista) -> schemi.AbitudiniData:
    """Costruisce la risposta. A parte dalla rotta per poterla usare dal PATCH."""
    attive = dom.elenco(conn)
    da, _ = _intervallo(vista, oggi)
    primo_mese = oggi.replace(day=1)
    # Un intervallo solo, abbastanza largo da coprire mese, settimana e strisce:
    # le strisce guardano indietro, quindi si parte da un po' prima del mese.
    per_abitudine = dom.log_del_periodo(conn, da=min(da, primo_mese) - timedelta(days=60), a=oggi)

    righe = [
        _riga(
            a,
            fatti=per_abitudine.get(a.id, set()),
            vista=vista,
            da=da,
            oggi=oggi,
            segnata_oggi=dom.segnata(conn, a.id, oggi) is True,
        )
        for a in attive
    ]
    strisce, migliore = _strisce(attive, per_abitudine, oggi)

    return schemi.AbitudiniData(
        periodoLabel="questa settimana"
        if vista == "settimana"
        else etichetta_mese(primo_mese, oggi),
        titolo=_titolo(righe, vista),
        avviso=_avviso(attive, per_abitudine, oggi),
        stats=schemi.StatsAbitudini(
            attive=len(attive),
            obiettiviCentrati=schemi.ObiettiviCentrati(
                fatti=len([r for r in righe if r.evidenziata]), totali=len(righe)
            ),
            streakMigliore=migliore,
            costanzaMese=_costanza_mese(attive, per_abitudine, oggi),
        ),
        abitudini=righe,
        meseSingolaAbitudine=_mese_singola(attive, per_abitudine, oggi),
        streak=strisce,
        proposta=_proposta(conn),
        report=_report(conn, vista, oggi),
    )


# — rotte —


@router.get("", response_model=schemi.AbitudiniData, response_model_exclude_none=True)
def pagina_abitudini(
    conn: ConnDip, ora: OraDip, vista: Vista = "settimana"
) -> schemi.AbitudiniData:
    return pagina(conn, ora.date(), vista)


def _dettaglio(conn: ConnDip, abitudine_id: int, oggi: date) -> schemi.AbitudineDettaglio:
    """La riga di una sola abitudine, come la rimanda una mutazione."""
    for riga in pagina(conn, oggi, "settimana").abitudini:
        if riga.id == str(abitudine_id):
            return riga
    # Disattivata: non compare più fra le attive, ma la mutazione è riuscita e
    # deve poter rispondere qualcosa di sensato.
    abitudine = dom.leggi(conn, abitudine_id)
    return schemi.AbitudineDettaglio(
        id=str(abitudine.id),
        nome=abitudine.nome,
        giorni=[False] * dom.GIORNI_SETTIMANA,
        progressoLabel="—",
        goalRatioLabel="—",
        frequenzaLabel=_frequenza_label(abitudine.target_settimanale),
        segnataOggi=False,
    )


@router.post("", response_model=schemi.AbitudineDettaglio, response_model_exclude_none=True)
def crea_abitudine(
    corpo: schemi.NuovaAbitudine, conn: ConnDip, ora: OraDip
) -> schemi.AbitudineDettaglio:
    """Una nuova abitudine (§8.6). Un nome già usato riprende quella che c'è."""
    try:
        abitudine = dom.crea(
            conn, nome=corpo.nome, target_settimanale=corpo.targetSettimanale, ora=ora
        )
    except ValueError as errore:
        raise HTTPException(status_code=422, detail=str(errore)) from errore
    return _dettaglio(conn, abitudine.id, ora.date())


@router.patch(
    "/{abitudine_id}", response_model=schemi.AbitudineDettaglio, response_model_exclude_none=True
)
def modifica_abitudine(
    abitudine_id: int, corpo: schemi.ModificaAbitudine, conn: ConnDip, ora: OraDip
) -> schemi.AbitudineDettaglio:
    """Nome, target o attivazione. §8.6: tutto modificabile in qualsiasi momento."""
    try:
        dom.modifica(
            conn,
            abitudine_id,
            nome=corpo.nome,
            target_settimanale=corpo.targetSettimanale,
            attiva=corpo.attiva,
        )
    except dom.AbitudineInesistente as errore:
        raise HTTPException(status_code=404, detail="Abitudine non trovata.") from errore
    except ValueError as errore:
        raise HTTPException(status_code=422, detail=str(errore)) from errore
    return _dettaglio(conn, abitudine_id, ora.date())


@router.patch(
    "/{abitudine_id}/log",
    response_model=schemi.AbitudineDettaglio,
    response_model_exclude_none=True,
)
def log_abitudine(
    abitudine_id: int, corpo: schemi.LogAbitudine, conn: ConnDip, ora: OraDip
) -> schemi.AbitudineDettaglio:
    """Segna (o toglie) un giorno. È la spunta della pagina, e il tap del bot."""
    try:
        giorno = date.fromisoformat(corpo.data)
    except ValueError as errore:
        raise HTTPException(
            status_code=422, detail="Data non valida: serve AAAA-MM-GG."
        ) from errore
    if giorno > ora.date():
        # Come per le spese (§8.5): un giorno che non è ancora arrivato non si
        # può segnare, e scriverlo lo renderebbe invisibile in ogni vista.
        raise HTTPException(status_code=422, detail="Non si può segnare un giorno futuro.")

    try:
        dom.segna(conn, abitudine_id, giorno=giorno, fatto=corpo.fatto, ora=ora)
    except dom.AbitudineInesistente as errore:
        raise HTTPException(status_code=404, detail="Abitudine non trovata.") from errore
    return _dettaglio(conn, abitudine_id, ora.date())


@router.post("/{proposta_id}/proposta/accetta", status_code=204)
def accetta_proposta(proposta_id: int, conn: ConnDip, ora: OraDip) -> Response:
    """`:id` qui è la **proposta**, non l'abitudine: è quello che manda la pagina."""
    _decidi(conn, proposta_id, ora, accetta=True)
    return Response(status_code=204)


@router.post("/{proposta_id}/proposta/rifiuta", status_code=204)
def rifiuta_proposta(proposta_id: int, conn: ConnDip, ora: OraDip) -> Response:
    _decidi(conn, proposta_id, ora, accetta=False)
    return Response(status_code=204)


def _decidi(conn: ConnDip, proposta_id: int, ora: OraDip, *, accetta: bool) -> None:
    try:
        dom.decidi(conn, proposta_id, accetta=accetta, ora=ora)
    except dom.PropostaInesistente as errore:
        raise HTTPException(status_code=404, detail="Proposta non trovata.") from errore
    except ValueError as errore:
        raise HTTPException(status_code=409, detail=str(errore)) from errore
