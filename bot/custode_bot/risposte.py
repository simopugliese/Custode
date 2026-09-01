"""Cosa risponde il bot, come funzioni pure.

Ogni funzione prende una connessione (e l'ora) e ritorna una `Risposta`:
niente qui sa cosa sia `python-telegram-bot`. È il livello che i test possono
esercitare davvero, mentre `applicazione.py` resta un adattatore sottile.

Il testo usa HTML (l'unico `parse_mode` di Telegram in cui si può mettere al
sicuro il testo dell'utente con un semplice escape): tutto ciò che arriva dal
database passa da `escape()` prima di finire in un messaggio.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

from custode_bot import azioni
from custode_bot.azioni import Vista
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import task as dom_task
from custode_core.formato import etichetta_scadenza, plurale
from custode_router import Router
from custode_router import assistente as dom_assistente

# I bottoni di Telegram vanno a capo male: meglio un titolo tagliato che una
# riga di bottoni illeggibile.
MAX_TESTO_BOTTONE = 28


@dataclass(frozen=True)
class Bottone:
    testo: str
    dato: str


@dataclass(frozen=True)
class Risposta:
    testo: str
    bottoni: list[list[Bottone]] = field(default_factory=list)


def _taglia(testo: str, massimo: int = MAX_TESTO_BOTTONE) -> str:
    return testo if len(testo) <= massimo else testo[: massimo - 1] + "…"


def _riga_task(task: dom_task.Task, ora: datetime) -> str:
    etichetta = etichetta_scadenza(task.scadenza, ora)
    riga = f"• {escape(task.titolo)}"
    if etichetta:
        riga += f" — <i>{escape(etichetta)}</i>"
    if task.rinvii:
        riga += f" (rinviato {task.rinvii}×)"
    return riga


def _riga_voce(voce: dom_lista.Voce) -> str:
    riga = f"• {escape(voce.nome)}"
    if voce.quantita:
        riga += f" — <i>{escape(voce.quantita)}</i>"
    return riga


def aiuto() -> Risposta:
    return Risposta(
        testo=(
            "<b>Custode</b>\n\n"
            "/oggi — cosa c'è oggi\n"
            "/task — i task aperti, con i bottoni per spuntarli\n"
            "/nuovo &lt;titolo&gt; — aggiungi un task\n"
            "/lista — la lista della spesa\n"
            "/aggiungi &lt;voce&gt; — aggiungi alla lista\n"
            "/svuota — togli dalla lista le voci già prese\n"
            "/aiuto — questo messaggio\n\n"
            "<i>Puoi anche scrivermi o dettarmi normalmente: «ricordami di "
            "chiamare l'officina», «sto finendo il latte», «fatto la bolletta». "
            "Eseguo subito e ti lascio un bottone per annullare.</i>"
        )
    )


def riepilogo_oggi(conn: sqlite3.Connection, ora: datetime) -> Risposta:
    """Il "che c'è oggi": scaduti, in scadenza oggi, e quanto manca sulla lista."""
    oggi = ora.date()
    aperti = dom_task.elenco(conn, fatto=False)
    in_ritardo = [t for t in aperti if dom_task.in_ritardo(t, oggi)]
    per_oggi = [t for t in aperti if dom_task.per_oggi(t, oggi)]
    da_prendere = dom_lista.elenco(conn, preso=False)

    if not in_ritardo and not per_oggi and not da_prendere:
        return Risposta(testo="Niente in sospeso.")

    pezzi: list[str] = []
    if in_ritardo:
        pezzi.append("<b>In ritardo</b>\n" + "\n".join(_riga_task(t, ora) for t in in_ritardo))
    if per_oggi:
        pezzi.append("<b>Oggi</b>\n" + "\n".join(_riga_task(t, ora) for t in per_oggi))
    if da_prendere:
        pezzi.append(
            f"<b>Lista spesa</b>\n{plurale(len(da_prendere), 'voce', 'voci')} da prendere."
        )

    bottoni = [
        [Bottone(f"✓ {_taglia(t.titolo)}", azioni.task_fatto(t.id, "oggi"))]
        for t in in_ritardo + per_oggi
    ]
    return Risposta(testo="\n\n".join(pezzi), bottoni=bottoni)


def elenco_task(conn: sqlite3.Connection, ora: datetime) -> Risposta:
    """Tutti i task aperti, con spunta e rinvio a portata di tap."""
    aperti = dom_task.elenco(conn, fatto=False)
    if not aperti:
        return Risposta(testo="Nessun task aperto.")

    testo = "<b>Task aperti</b>\n" + "\n".join(_riga_task(t, ora) for t in aperti)
    bottoni = [
        [
            Bottone(f"✓ {_taglia(t.titolo)}", azioni.task_fatto(t.id, "task")),
            Bottone("⏭", azioni.task_rinvia(t.id, "task")),
        ]
        for t in aperti
    ]
    return Risposta(testo=testo, bottoni=bottoni)


def nuovo_task(conn: sqlite3.Connection, ora: datetime, titolo: str) -> Risposta:
    """Crea un task e chiede la scadenza con dei bottoni.

    Chiedere invece di interpretare: senza il router (§6) una data scritta a
    parole non si può leggere in modo affidabile, e tre bottoni sono più veloci
    da premere di quanto sia scrivere una data.
    """
    titolo = titolo.strip()
    if not titolo:
        return Risposta(testo="Serve un titolo: <code>/nuovo Chiamare l'officina</code>")

    task = dom_task.crea(conn, titolo=titolo, ora=ora, origine="telegram")
    return Risposta(
        testo=f"Segnato: <b>{escape(task.titolo)}</b>\nQuando scade?",
        bottoni=[
            [
                Bottone("Oggi", azioni.task_scadenza(task.id, "oggi")),
                Bottone("Domani", azioni.task_scadenza(task.id, "domani")),
            ],
            [
                Bottone("Fra una settimana", azioni.task_scadenza(task.id, "settimana")),
                Bottone("Senza scadenza", azioni.task_scadenza(task.id, "mai")),
            ],
        ],
    )


def elenco_lista(conn: sqlite3.Connection) -> Risposta:
    """La lista della spesa raggruppata per reparto, spuntabile."""
    da_prendere = dom_lista.elenco(conn, preso=False)
    presi = dom_lista.elenco(conn, preso=True)

    if not da_prendere:
        testo = "Lista della spesa vuota."
        if presi:
            testo += f"\n{plurale(len(presi), 'voce presa', 'voci prese')} da archiviare (/svuota)."
        return Risposta(testo=testo)

    blocchi = [
        f"<b>{escape(reparto)}</b>\n" + "\n".join(_riga_voce(v) for v in voci)
        for reparto, voci in dom_lista.per_reparto(da_prendere)
    ]
    testo = "\n\n".join(blocchi)
    if presi:
        testo += (
            f"\n\n<i>{plurale(len(presi), 'voce presa', 'voci prese')}</i> — /svuota per toglierle."
        )

    bottoni = [
        [Bottone(f"✓ {_taglia(v.nome)}", azioni.voce_presa(v.id, "lista"))] for v in da_prendere
    ]
    return Risposta(testo=testo, bottoni=bottoni)


def aggiungi_voce(conn: sqlite3.Connection, ora: datetime, testo: str) -> Risposta:
    nome = testo.strip()
    if not nome:
        return Risposta(testo="Serve una voce: <code>/aggiungi latte</code>")

    prima = len(dom_lista.elenco(conn, preso=False))
    voce = dom_lista.aggiungi(conn, nome=nome, ora=ora)
    if len(dom_lista.elenco(conn, preso=False)) == prima:
        return Risposta(testo=f"<b>{escape(voce.nome)}</b> era già in lista.")
    return Risposta(testo=f"Aggiunto: <b>{escape(voce.nome)}</b>")


def chiedi_svuota(conn: sqlite3.Connection) -> Risposta:
    """Svuotare cancella righe: si chiede conferma prima, non dopo."""
    presi = dom_lista.elenco(conn, preso=True)
    if not presi:
        return Risposta(testo="Non c'è niente di già preso da togliere.")
    return Risposta(
        testo=f"Tolgo {plurale(len(presi), 'voce già presa', 'voci già prese')} dalla lista?",
        bottoni=[
            [Bottone("Sì, togli", azioni.svuota(True)), Bottone("Annulla", azioni.svuota(False))]
        ],
    )


def messaggio_libero(
    conn: sqlite3.Connection, ora: datetime, testo: str, router: Router
) -> Risposta:
    """Testo (o vocale trascritto) in linguaggio libero → azione (§8.1, §6).

    L'azione viene eseguita subito e il bot dice cosa ha fatto, con un bottone
    per tornare indietro: l'interpretazione è automatica, quindi disfare deve
    costare un tap e non una caccia al task creato per sbaglio.
    """
    esito = dom_assistente.interpreta_ed_esegui(conn, ora, testo, router)

    bottoni: list[list[Bottone]] = []
    identificatore = esito.task_id if esito.task_id is not None else esito.voce_id
    if esito.ha_cambiato_qualcosa and identificatore is not None:
        bottoni = [
            [
                Bottone(
                    "Annulla",
                    azioni.annulla(esito.azione.value, identificatore, esito.giorni),
                )
            ]
        ]
    return Risposta(testo=escape(esito.testo), bottoni=bottoni)


def _dopo_azione(conn: sqlite3.Connection, ora: datetime, vista: Vista) -> Risposta:
    """Ridisegna l'elenco da cui è partito il tap, aggiornato."""
    if vista == "oggi":
        return riepilogo_oggi(conn, ora)
    if vista == "lista":
        return elenco_lista(conn)
    return elenco_task(conn, ora)


SCADENZE_RAPIDE = {"oggi": 0, "domani": 1, "settimana": 7}


def esegui_azione(conn: sqlite3.Connection, ora: datetime, dato: str) -> Risposta:
    """Applica il tap su un bottone e ritorna il messaggio aggiornato."""
    try:
        azione = azioni.leggi(dato)
    except azioni.AzioneNonValida:
        return Risposta(testo="Questo bottone non è più valido.")

    try:
        if azione.dominio == "t" and azione.nome == "fatto":
            dom_task.imposta_fatto(conn, int(azione.argomento), True, ora)
        elif azione.dominio == "t" and azione.nome == "rinvia":
            dom_task.rinvia(conn, int(azione.argomento), 1, ora)
        elif azione.dominio == "t" and azione.nome.startswith("sc-"):
            return _imposta_scadenza(conn, ora, int(azione.argomento), azione.nome[3:])
        elif azione.dominio == "s" and azione.nome == "preso":
            dom_lista.imposta_preso(conn, int(azione.argomento), True, ora)
        elif azione.dominio == "x" and azione.nome == "annulla":
            return _annulla(conn, ora, azione.argomento)
        elif azione.dominio == "x" and azione.nome == "svuota":
            if azione.argomento == "si":
                dom_lista.svuota_presi(conn)
        else:
            return Risposta(testo="Questo bottone non è più valido.")
    except (dom_task.TaskInesistente, dom_lista.VoceInesistente):
        # Capita col messaggio vecchio in cronologia, dopo aver cancellato la riga.
        return Risposta(testo="Quella voce non esiste più.")
    except ValueError:
        return Risposta(testo="Questo bottone non è più valido.")

    return _dopo_azione(conn, ora, azione.vista)


def _annulla(conn: sqlite3.Connection, ora: datetime, argomento: str) -> Risposta:
    try:
        nome, identificatore, giorni = azioni.leggi_annulla(argomento)
        azione_assistente = dom_assistente.Azione(nome)
    except (azioni.AzioneNonValida, ValueError):
        return Risposta(testo="Questo bottone non è più valido.")

    testo = dom_assistente.annulla(
        conn, ora, azione_assistente, identificatore=identificatore, giorni=giorni
    )
    return Risposta(testo=escape(testo))


def _imposta_scadenza(
    conn: sqlite3.Connection, ora: datetime, task_id: int, quando: str
) -> Risposta:
    task = dom_task.leggi(conn, task_id)
    if quando == "mai":
        return Risposta(testo=f"<b>{escape(task.titolo)}</b> — senza scadenza.")
    if quando not in SCADENZE_RAPIDE:
        return Risposta(testo="Questo bottone non è più valido.")

    scadenza = ora.date() + timedelta(days=SCADENZE_RAPIDE[quando])
    conn.execute(
        "UPDATE tasks SET scadenza = ? WHERE id = ?",
        (dom_task.scrivi_scadenza(scadenza), task_id),
    )
    aggiornato = dom_task.leggi(conn, task_id)
    etichetta = etichetta_scadenza(aggiornato.scadenza, ora) or ""
    return Risposta(testo=f"<b>{escape(task.titolo)}</b> — scade {escape(etichetta)}.")
