"""Il report narrativo delle abitudini, settimanale e mensile (§8.6).

§8.6 ne vuole due, con due scopi diversi: il **settimanale** per un check
ravvicinato, il **mensile** per i trend più lenti — «un'abitudine che regge le
prime settimane e poi cala». Sono lo stesso giro con un intervallo diverso, e
quello che cambia davvero è cosa si riesce a vedere: una settimana storta non
è una tendenza, un mese sì. Per questo la **proposta** di adeguare un target
nasce solo dal mensile.

I numeri li prepara questo modulo leggendo il dominio; Claude li racconta e
basta (§8.6: «calcolati in codice, senza LLM»). E come ogni azione decisa da un
modello, l'eventuale proposta resta una proposta finché non la accetti: qui si
scrive una riga in `habit_proposals`, non si cambia nessun target.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from custode_bot.risposte import Risposta
from custode_core.dominio import abitudini as dom
from custode_core.dominio import diario as dom_diario
from custode_core.dominio import spese as dom_spese
from custode_core.formato import etichetta_giorno_voce, etichetta_mese, euro, plurale
from custode_router import Router
from custode_router import abitudini as router_abitudini
from custode_router.errori import ErroreRouter

log = logging.getLogger("custode.worker")

# Dopo un «no» su un'abitudine non si ripropone per un mese: i numeri che
# l'avevano fatta nascere cambiano lentamente, quindi la proposta successiva
# sarebbe quasi identica — e ripetere la stessa domanda dopo un no è il modo
# più rapido perché smetta di essere letta.
GIORNI_DI_SILENZIO_DOPO_UN_NO = 30

# Quante voci di diario passare al modello: servono a dare colore agli
# incroci, non a essere riassunte da capo (quello è §8.4).
MAX_VOCI_DIARIO = 14


@dataclass(frozen=True)
class Esito:
    """Cosa ha fatto il giro, per i log e per i test."""

    periodo: dom.Periodo
    chiave: date
    abitudini_lette: int
    report_scritto: bool
    proposta_creata: bool
    messaggio: Risposta | None
    """Cosa mandare su Telegram. `None` = non c'è niente da dire, e non si manda."""

    errore: str | None = None


def _intervallo(periodo: dom.Periodo, chiave: date) -> tuple[date, date]:
    if periodo is dom.Periodo.SETTIMANA:
        return chiave, chiave + timedelta(days=6)
    # Il mese finisce l'ultimo giorno: si arriva al primo del mese dopo e si
    # torna indietro di uno, così non serve sapere quanti giorni ha.
    primo_dopo = (chiave.replace(day=28) + timedelta(days=4)).replace(day=1)
    return chiave, primo_dopo - timedelta(days=1)


def etichetta_periodo(periodo: dom.Periodo, chiave: date, oggi: date) -> str:
    if periodo is dom.Periodo.SETTIMANA:
        da, a = _intervallo(periodo, chiave)
        return f"{etichetta_giorno_voce(da)} – {etichetta_giorno_voce(a)}"
    return etichetta_mese(chiave, oggi)


def numeri(conn: sqlite3.Connection, *, da: date, a: date) -> list[dict[str, Any]]:
    """I dati di ogni abitudine attiva nel periodo, già calcolati (§8.6).

    Sta a parte da `esegui` perché è la parte che si può sbagliare in silenzio:
    provarla non deve richiedere di far finta di essere Claude.
    """
    attive = dom.elenco(conn)
    log_periodo = dom.log_del_periodo(conn, da=da - timedelta(days=60), a=a)
    giorni = (a - da).days + 1

    righe: list[dict[str, Any]] = []
    for abitudine in attive:
        fatti = log_periodo.get(abitudine.id, set())
        nel_periodo = len([g for g in fatti if da <= g <= a])
        attesi = dom.attesi(abitudine.target_settimanale, giorni)
        righe.append(
            {
                "id": abitudine.id,
                "nome": abitudine.nome,
                "target": abitudine.target_settimanale,
                "fatte": nel_periodo,
                "attese": attesi,
                "aderenza": dom.percentuale(dom.aderenza(nel_periodo, attesi)),
                "striscia": dom.striscia(fatti, a),
            }
        )
    return righe


def _diario(conn: sqlite3.Connection, da: date, a: date) -> list[str]:
    voci = dom_diario.approvate(conn, da=da, a=a)
    return [v.riassunto_approvato or "" for v in voci if v.riassunto_approvato][:MAX_VOCI_DIARIO]


def _spese(conn: sqlite3.Connection, da: date, a: date) -> str | None:
    """Una riga sola: le spese danno contesto, non sono da analizzare (§8.5)."""
    spese = dom_spese.elenco(conn, da=da, a=a)
    if not spese:
        return None
    categorie = dom_spese.per_categoria(spese)[:3]
    coda = ", soprattutto " + ", ".join(nome for nome, _ in categorie) if categorie else ""
    return f"{euro(dom_spese.totale(spese))} in {plurale(len(spese), 'spesa', 'spese')}{coda}"


def esegui(
    conn: sqlite3.Connection,
    ora: datetime,
    *,
    periodo: dom.Periodo,
    chiave: date,
    router: Router,
) -> Esito:
    """Il giro per un periodo. Non manda niente: prepara il messaggio e lo ritorna.

    Come il riepilogo del diario, così tutto il ragionamento si prova senza rete.
    """
    da, a = _intervallo(periodo, chiave)
    righe = numeri(conn, da=da, a=a)
    if not righe:
        # Nessuna abitudine attiva: non c'è niente da raccontare, e un report
        # che dice «non segui niente» è una notifica sprecata.
        return Esito(
            periodo=periodo,
            chiave=chiave,
            abitudini_lette=0,
            report_scritto=False,
            proposta_creata=False,
            messaggio=None,
        )

    esistente = dom.report(conn, periodo=periodo, chiave=chiave)
    if esistente is not None:
        # Il job è stato rifatto a mano: un periodo chiuso non cambia, e
        # richiamare Claude costerebbe una chiamata per riscrivere lo stesso.
        return Esito(
            periodo=periodo,
            chiave=chiave,
            abitudini_lette=len(righe),
            report_scritto=True,
            proposta_creata=False,
            messaggio=_messaggio(periodo, chiave, esistente.testo, ora.date()),
        )

    try:
        rapporto = router_abitudini.report(
            router,
            periodo="settimanale" if periodo is dom.Periodo.SETTIMANA else "mensile",
            intervallo=etichetta_periodo(periodo, chiave, ora.date()),
            abitudini=righe,
            diario=_diario(conn, da, a),
            spese=_spese(conn, da, a),
        )
    except ErroreRouter as guasto:
        log.warning("report abitudini (%s) non riuscito: %s", periodo.value, guasto)
        return Esito(
            periodo=periodo,
            chiave=chiave,
            abitudini_lette=len(righe),
            report_scritto=False,
            proposta_creata=False,
            messaggio=None,
            errore=router_abitudini.messaggio_errore(guasto),
        )

    dom.salva_report(conn, periodo=periodo, chiave=chiave, testo=rapporto.testo, ora=ora)
    proposta = _registra_proposta(conn, ora, periodo, rapporto, righe)

    return Esito(
        periodo=periodo,
        chiave=chiave,
        abitudini_lette=len(righe),
        report_scritto=True,
        proposta_creata=proposta,
        messaggio=_messaggio(periodo, chiave, rapporto.testo, ora.date()),
    )


def _registra_proposta(
    conn: sqlite3.Connection,
    ora: datetime,
    periodo: dom.Periodo,
    rapporto: router_abitudini.Rapporto,
    righe: list[dict[str, Any]],
) -> bool:
    """Mette in attesa l'adeguamento proposto, se ce n'è uno e ha senso tenerlo.

    Solo dal **mensile**: una settimana storta non è una tendenza, e §8.6 parla
    proprio di «un'abitudine che regge le prime settimane e poi cala». Un
    adeguamento proposto ogni sette giorni sarebbe rumore.
    """
    if rapporto.proposta is None or periodo is dom.Periodo.SETTIMANA:
        return False

    per_nome = {r["nome"]: r["id"] for r in righe}
    abitudine_id = per_nome.get(rapporto.proposta.abitudine)
    if abitudine_id is None:
        return False
    if dom.rifiutata_di_recente(
        conn, abitudine_id, dal=ora.date() - timedelta(days=GIORNI_DI_SILENZIO_DOPO_UN_NO)
    ):
        return False

    try:
        dom.proponi(
            conn,
            abitudine_id,
            target_proposto=rapporto.proposta.target_proposto,
            motivazione=rapporto.proposta.motivazione,
            ora=ora,
        )
    except ValueError as errore:
        # Un target identico a quello attuale, o una motivazione vuota: la
        # proposta si perde, il report no.
        log.info("proposta di adeguamento scartata: %s", errore)
        return False
    return True


def _messaggio(periodo: dom.Periodo, chiave: date, testo: str, oggi: date) -> Risposta:
    titolo = (
        "Le tue abitudini · settimana"
        if periodo is dom.Periodo.SETTIMANA
        else "Le tue abitudini · mese"
    )
    return Risposta(
        testo=(
            f"<b>{escape(titolo)}</b>\n"
            f"<i>{escape(etichetta_periodo(periodo, chiave, oggi))}</i>\n\n"
            f"{escape(testo)}"
        )
    )
