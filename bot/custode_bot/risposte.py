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
from datetime import date, datetime, timedelta
from html import escape

from custode_bot import azioni
from custode_bot.azioni import Vista
from custode_core.dominio import abitudini as dom_abitudini
from custode_core.dominio import diario as dom_diario
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import profilo as dom_profilo
from custode_core.dominio import spese as dom_spese
from custode_core.dominio import task as dom_task
from custode_core.formato import (
    MESI_BREVI,
    etichetta_giorno,
    etichetta_giorno_voce,
    etichetta_quando,
    etichetta_scadenza,
    euro,
    giorno_con_preposizione,
    inizio_settimana,
    plurale,
)
from custode_router import Router
from custode_router import assistente as dom_assistente
from custode_router import diario as router_diario
from custode_router import profilo as router_profilo
from custode_router import spese as router_spese
from custode_router.errori import ErroreRouter

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
            "/diario — chiudi la giornata e leggi il riassunto da approvare\n"
            "/spese — quanto hai speso questo mese\n"
            "/abitudini — come stai andando questa settimana\n"
            "/profilo — cosa ho capito di te\n"
            "/aiuto — questo messaggio\n\n"
            "<i>Puoi anche scrivermi o dettarmi normalmente: «ricordami di "
            "chiamare l'officina», «sto finendo il latte», «fatto la bolletta». "
            "Eseguo subito e ti lascio un bottone per annullare.</i>\n\n"
            "<i>Le spese puoi dirmele («ho pagato 8€ la colazione da Bar Rossi») "
            "o fotografarmi lo scontrino: quello lo leggo e ti chiedo conferma "
            "prima di metterlo nei conti.</i>\n\n"
            "<i>Quello che mi racconti — com'è andata, cosa pensi, come stai — "
            "lo metto da parte per il diario di oggi. A fine giornata /diario "
            "te ne propone il riassunto: entra nel diario solo se lo approvi.</i>"
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
    conn: sqlite3.Connection,
    ora: datetime,
    testo: str,
    router: Router,
    *,
    da_vocale: bool = False,
) -> Risposta:
    """Testo (o vocale trascritto) in linguaggio libero → azione (§8.1, §6).

    L'azione viene eseguita subito e il bot dice cosa ha fatto, con un bottone
    per tornare indietro: l'interpretazione è automatica, quindi disfare deve
    costare un tap e non una caccia al task creato per sbaglio.
    """
    # Se una bozza di diario sta aspettando la tua riscrittura, questo messaggio
    # è la riscrittura: si prende alla lettera, senza passare dal modello (§8.4).
    # Il testo che entra nel diario resta così esattamente il tuo.
    attesa = dom_diario.in_modifica(conn)
    if attesa is not None:
        return _riscrivi_diario(conn, ora, attesa, testo)

    esito = dom_assistente.interpreta_ed_esegui(conn, ora, testo, router, da_vocale=da_vocale)

    bottoni: list[list[Bottone]] = []
    if esito.ha_cambiato_qualcosa and esito.identificatore is not None:
        bottoni = [
            [
                Bottone(
                    "Annulla",
                    azioni.annulla(esito.azione.value, esito.identificatore, esito.giorni),
                )
            ]
        ]

    # Una giornata raccontata in ritardo va anche chiusa, e `/diario` da solo
    # guarda oggi: senza questo bottone il racconto di ieri resterebbe grezzo
    # per sempre, e per accorgersene bisognerebbe sapere che esiste
    # `/diario ieri`. Il tap è nel momento in cui la cosa è in mente.
    raccontato = esito.giorno if esito.azione is dom_assistente.Azione.ANNOTA_DIARIO else None
    if raccontato is not None and raccontato != ora.date():
        bottoni = bottoni + [
            [
                Bottone(
                    f"Chiudi la giornata {giorno_con_preposizione(raccontato, ora.date())}",
                    azioni.diario_giorno(raccontato),
                )
            ]
        ]

    testo_risposta = escape(esito.testo)
    # Il segnale ambiguo di §8.4: la domanda si attacca alla risposta normale
    # invece di essere un secondo messaggio. Una notifica sola, e resta chiaro
    # che è una parentesi rispetto a quello che il bot ha appena fatto.
    if esito.domanda_chiarimento and esito.candidato_id is not None:
        testo_risposta += f"\n\n<i>{escape(esito.domanda_chiarimento)}</i>"
        bottoni = bottoni + [
            [
                Bottone("Sono fatto così", azioni.profilo("si", esito.candidato_id)),
                Bottone("Era il momento", azioni.profilo("no", esito.candidato_id)),
            ]
        ]
    return Risposta(testo=testo_risposta, bottoni=bottoni)


# — diario (§8.4) —————————————————————————————————————


def _testo_bozza(voce: dom_diario.Voce, riassunto: str) -> str:
    righe = [
        f"<b>{escape(etichetta_giorno_voce(voce.giorno))}</b>",
        "",
        escape(riassunto),
    ]
    if voce.tag:
        righe += ["", "<i>" + escape(" · ".join(voce.tag)) + "</i>"]
    righe += ["", "<i>Entra nel diario solo se lo approvi.</i>"]
    return "\n".join(righe)


def _bozza(voce: dom_diario.Voce) -> Risposta:
    """La proposta di Claude, con le tre uscite di §8.4: sì, riscrivi, butta."""
    return Risposta(
        testo=_testo_bozza(voce, voce.riassunto_proposto or ""),
        bottoni=[
            [
                Bottone("✓ Approva", azioni.diario("approva", voce.id)),
                Bottone("✎ Modifica", azioni.diario("modifica", voce.id)),
            ],
            [Bottone("Scarta", azioni.diario("scarta", voce.id))],
        ],
    )


# Le forme accettate da `/diario <giorno>`: poche e fisse, contate all'indietro
# da oggi. Qui un piccolo parser in codice è la scelta giusta, al contrario di
# quanto vale per il linguaggio libero (§8.5): l'argomento di un comando è un
# insieme chiuso che decido io, non una frase che puoi dire come ti pare — e
# far pagare una chiamata al modello per capire «ieri» sarebbe assurdo.
GIORNI_INDIETRO = {
    "oggi": 0,
    "ieri": 1,
    "altroieri": 2,
    "l'altro ieri": 2,
    "altro ieri": 2,
}


def leggi_giorno_comando(argomento: str, oggi: date) -> date | None:
    """Il giorno indicato a `/diario`. `None` se non si capisce.

    Accetta «ieri», «l'altro ieri», una data ISO (`2026-09-02`) e la forma
    breve che il bot stesso stampa nelle sue etichette («2 set»). Un giorno nel
    futuro non esiste come giornata da raccontare e vale `None`.
    """
    pulito = " ".join(argomento.strip().casefold().split())
    if not pulito:
        return oggi

    if pulito in GIORNI_INDIETRO:
        return oggi - timedelta(days=GIORNI_INDIETRO[pulito])

    letta: date | None
    try:
        letta = date.fromisoformat(pulito)
    except ValueError:
        letta = _giorno_breve(pulito, oggi)
    if letta is None or letta > oggi:
        return None
    return letta


def _giorno_breve(testo: str, oggi: date) -> date | None:
    """ "2 set" → la data più recente che si scrive così, mai nel futuro."""
    pezzi = testo.split()
    if len(pezzi) != 2 or not pezzi[0].isdigit():
        return None
    if pezzi[1][:3] not in MESI_BREVI:
        return None
    mese = MESI_BREVI.index(pezzi[1][:3]) + 1
    for anno in (oggi.year, oggi.year - 1):
        try:
            candidata = date(anno, mese, int(pezzi[0]))
        except ValueError:
            return None
        if candidata <= oggi:
            return candidata
    return None


def diario_giorno(
    conn: sqlite3.Connection, ora: datetime, router: Router, *, giorno: date | None = None
) -> Risposta:
    """`/diario`: chiude una giornata e propone il riassunto da approvare.

    La chiusura è esplicita e non automatica: il riassunto costa una chiamata a
    Claude (§6), e rigenerarlo ad ogni frase sarebbe spesa buttata — oltre che
    inutile, visto che la giornata non è finita.

    `giorno` esiste perché una giornata si può raccontare in ritardo («ti
    racconto la giornata di ieri»): il materiale finisce sul giorno giusto, e
    senza un modo di chiudere *quel* giorno resterebbe grezzo per sempre.
    """
    quel_giorno = giorno or ora.date()
    voce = dom_diario.leggi_giorno(conn, quel_giorno)
    if voce is None or not voce.ha_materiale:
        if voce is not None and voce.riassunto_approvato:
            return Risposta(testo=_testo_approvato(voce))
        quando = "Oggi" if quel_giorno == ora.date() else etichetta_giorno_voce(quel_giorno)
        return Risposta(
            testo=(
                f"{escape(quando)} non mi hai raccontato niente.\n\n"
                "<i>Scrivimi o dettami com'è andata: metto tutto da parte e poi "
                "/diario te ne propone il riassunto.</i>"
            )
        )

    # Giornata già chiusa e nessun materiale nuovo dopo: si rilegge e basta.
    # Rigenerare qui sarebbe una chiamata a Claude per riscrivere una cosa già
    # decisa, e per giunta riaprirebbe una giornata che avevi chiuso. Quando
    # arriva materiale nuovo lo stato torna da solo a `in_raccolta`, e il
    # riassunto si rifà passando per il ramo qui sotto.
    if voce.stato is dom_diario.Stato.APPROVATA:
        return Risposta(testo=_testo_approvato(voce))

    if voce.stato is dom_diario.Stato.DA_APPROVARE and voce.riassunto_proposto:
        return _bozza(voce)
    if voce.stato is dom_diario.Stato.IN_MODIFICA:
        return _chiedi_riscrittura(voce)

    try:
        riassunto = router_diario.riassumi(
            router,
            giorno=voce.giorno,
            grezzo=voce.grezzo,
            precedente=voce.riassunto_approvato,
            # §8.4: il profilo serve a dare contesto senza rispiegarsi. Il
            # riassunto della giornata è l'unico posto, oggi, dove conoscerti
            # cambia davvero l'uscita — e costa una chiamata al giorno.
            profilo=dom_profilo.testo_corrente(conn),
        )
    except ErroreRouter as errore:
        # Il materiale resta salvato: si riprova con un altro /diario, e nel
        # frattempo non si è perso niente di ciò che era stato raccontato.
        return Risposta(testo=escape(router_diario.messaggio_errore(errore)))

    aggiornata = dom_diario.proponi(conn, voce.id, riassunto=riassunto.testo, tag=riassunto.tag)
    return _bozza(aggiornata)


def _testo_approvato(voce: dom_diario.Voce) -> str:
    righe = [
        f"<b>{escape(etichetta_giorno_voce(voce.giorno))}</b> — già nel diario",
        "",
        escape(voce.riassunto_approvato or ""),
    ]
    if voce.tag:
        righe += ["", "<i>" + escape(" · ".join(voce.tag)) + "</i>"]
    return "\n".join(righe)


def _chiedi_riscrittura(voce: dom_diario.Voce) -> Risposta:
    return Risposta(
        testo=(
            "Mandami la voce come la vuoi tu: il prossimo messaggio "
            "(scritto o dettato) diventa il diario di "
            f"<b>{escape(etichetta_giorno_voce(voce.giorno))}</b>, parola per parola."
        ),
        bottoni=[[Bottone("Lascia la bozza", azioni.diario("annmod", voce.id))]],
    )


def _riscrivi_diario(
    conn: sqlite3.Connection, ora: datetime, voce: dom_diario.Voce, testo: str
) -> Risposta:
    pulito = testo.strip()
    if not pulito:
        return _chiedi_riscrittura(voce)
    approvata = dom_diario.approva(conn, voce.id, ora, testo=pulito)
    return Risposta(testo=_testo_approvato(approvata))


def _chiudi_giornata(
    conn: sqlite3.Connection, ora: datetime, argomento: str, router: Router | None
) -> Risposta:
    """Il tap su «Chiudi la giornata di ieri»: fa quello che farebbe `/diario ieri`."""
    giorno = leggi_giorno_comando(argomento, ora.date())
    if giorno is None:
        return Risposta(testo="Questo bottone non è più valido.")
    if router is None:
        # Non può capitare dal bot vero, che il router ce l'ha sempre: è la
        # stessa rete del bottone «Aggiorna il profilo».
        return Risposta(testo="Il riassunto ha bisogno del modello, che non è configurato.")
    return diario_giorno(conn, ora, router, giorno=giorno)


def _azione_diario(conn: sqlite3.Connection, ora: datetime, nome: str, voce_id: int) -> Risposta:
    if nome == "approva":
        voce = dom_diario.approva(conn, voce_id, ora)
        return Risposta(testo=_testo_approvato(voce))
    if nome == "modifica":
        return _chiedi_riscrittura(dom_diario.chiedi_modifica(conn, voce_id))
    if nome == "annmod":
        return _bozza(dom_diario.annulla_modifica(conn, voce_id))
    if nome == "scarta":
        dom_diario.scarta(conn, voce_id)
        return Risposta(
            testo=(
                "Buttata via, materiale compreso: di questa giornata non resta "
                "niente nel diario."
            )
        )
    return Risposta(testo="Questo bottone non è più valido.")


# — spese (§8.5) ——————————————————————————————————————


def _riga_spesa(spesa: dom_spese.Spesa, oggi: date) -> str:
    riga = f"• {escape(spesa.descrizione)} — <b>{euro(spesa.centesimi)}</b>"
    # Di uno scontrino la descrizione *è* il luogo: ripeterlo direbbe due volte
    # la stessa cosa in una riga che deve stare su uno schermo di telefono.
    luogo = spesa.luogo if spesa.luogo != spesa.descrizione else None
    dettagli = [d for d in (spesa.categoria, luogo) if d]
    if dettagli:
        riga += f" <i>{escape(' · '.join(dettagli))}</i>"
    return riga + f" <i>{escape(etichetta_giorno(spesa.giorno, oggi))}</i>"


def elenco_spese(conn: sqlite3.Connection, ora: datetime) -> Risposta:
    """`/spese`: il mese corrente, col totale e le categorie che pesano di più."""
    oggi = ora.date()
    primo = oggi.replace(day=1)
    del_mese = dom_spese.elenco(conn, da=primo, a=oggi)
    attesa = dom_spese.in_attesa(conn)
    # Registrate ora ma datate prima del mese: fuori dal totale, ma non dallo
    # schermo — altrimenti uno scontrino appena confermato sembrerebbe perso.
    fuori = dom_spese.registrate_fuori_periodo(conn, da=primo, a=oggi)

    if not del_mese and not attesa and not fuori:
        return Risposta(
            testo=(
                "Non hai ancora registrato spese questo mese.\n\n"
                "<i>Dimmi «ho pagato 8€ la colazione» o mandami la foto di uno "
                "scontrino.</i>"
            )
        )

    pezzi: list[str] = []
    if del_mese:
        totale = dom_spese.totale(del_mese)
        pezzi.append(
            f"<b>Questo mese</b> — {euro(totale)} in " f"{plurale(len(del_mese), 'spesa', 'spese')}"
        )
        categorie = dom_spese.per_categoria(del_mese)[:5]
        if categorie:
            pezzi.append("\n".join(f"• {escape(nome)} — {euro(cent)}" for nome, cent in categorie))
        pezzi.append("<b>Ultime</b>\n" + "\n".join(_riga_spesa(s, oggi) for s in del_mese[:5]))

    if fuori:
        pezzi.append(
            f"<i>Hai registrato {plurale(len(fuori), 'spesa datata', 'spese datate')} "
            f"fuori da questo mese ({euro(dom_spese.totale(fuori))}): "
            "non sono in questo totale.</i>\n" + "\n".join(_riga_spesa(s, oggi) for s in fuori[:3])
        )

    bottoni: list[list[Bottone]] = []
    if attesa:
        pezzi.append(
            f"<i>{plurale(len(attesa), 'scontrino letto', 'scontrini letti')} "
            "in attesa di conferma.</i>"
        )
        bottoni = _bottoni_scontrino(attesa[0])

    return Risposta(testo="\n\n".join(pezzi), bottoni=bottoni)


def _bottoni_scontrino(spesa: dom_spese.Spesa) -> list[list[Bottone]]:
    return [
        [
            Bottone("✓ Conferma", azioni.spesa("conferma", spesa.id)),
            Bottone("Scarta", azioni.spesa("scarta", spesa.id)),
        ]
    ]


def _testo_scontrino(spesa: dom_spese.Spesa, oggi: date) -> str:
    righe = [
        "<b>Scontrino letto</b>",
        "",
        f"Totale: <b>{euro(spesa.centesimi)}</b>",
    ]
    if spesa.luogo:
        righe.append(f"Luogo: {escape(spesa.luogo)}")
    righe.append(f"Data: {escape(etichetta_giorno(spesa.giorno, oggi))}")
    if spesa.categoria:
        righe.append(f"Categoria: {escape(spesa.categoria)}")
    if spesa.scontrino_raw:
        voci = spesa.scontrino_raw.splitlines()
        mostrate = "\n".join(f"  {escape(v)}" for v in voci[:8])
        righe += ["", "<i>Voci lette:</i>", f"<i>{mostrate}</i>"]
        if len(voci) > 8:
            righe.append(f"<i>  … e altre {len(voci) - 8}</i>")
    righe += ["", "<i>Entra nei conti solo se confermi.</i>"]
    return "\n".join(righe)


def scontrino(
    conn: sqlite3.Connection,
    ora: datetime,
    immagine: bytes,
    router: Router,
    *,
    media_type: str = "image/jpeg",
) -> Risposta:
    """Una foto di scontrino → una spesa da confermare (§8.5).

    È l'unica cosa che chiede una conferma esplicita prima di entrare nei
    conti: il modello legge dieci numeri da un'immagine, e sbagliarne uno è
    facile in un modo in cui non lo è leggere una frase.
    """
    try:
        letto = router_spese.leggi_scontrino(
            router, immagine=immagine, oggi=ora.date(), media_type=media_type
        )
    except ErroreRouter as errore:
        return Risposta(testo=escape(router_spese.messaggio_errore(errore)))

    spesa = dom_spese.registra(
        conn,
        centesimi=letto.centesimi,
        descrizione=letto.luogo or "scontrino",
        ora=ora,
        giorno=letto.giorno,
        luogo=letto.luogo or None,
        fonte=dom_spese.Fonte.SCONTRINO,
        stato=dom_spese.Stato.DA_CONFERMARE,
        scontrino_raw=letto.dettaglio or None,
    )
    # La categoria si chiede *dopo* aver salvato: se Claude non risponde, lo
    # scontrino letto resta lì da confermare invece di andare perso.
    dom_assistente.categorizza_se_serve(conn, ora, spesa.id, router)
    return Risposta(
        testo=_testo_scontrino(dom_spese.leggi(conn, spesa.id), ora.date()),
        bottoni=_bottoni_scontrino(spesa),
    )


def _azione_spesa(conn: sqlite3.Connection, ora: datetime, nome: str, spesa_id: int) -> Risposta:
    if nome == "conferma":
        spesa = dom_spese.conferma(conn, spesa_id, ora)
        coda = f" — {spesa.categoria}" if spesa.categoria else ""
        # I totali vanno per data della spesa, non per quando l'hai registrata:
        # se lo scontrino è di un altro giorno bisogna dirlo, altrimenti lo si
        # cerca invano in «questo mese».
        quando = etichetta_quando(spesa.giorno, ora.date())
        return Risposta(
            testo=(
                f"Nei conti: <b>{escape(spesa.descrizione)}</b>, "
                f"{euro(spesa.centesimi)}{escape(coda)}{escape(quando)}"
            )
        )
    if nome == "scarta":
        dom_spese.elimina(conn, spesa_id)
        return Risposta(testo="Scontrino buttato: non è entrato nei conti.")
    return Risposta(testo="Questo bottone non è più valido.")


# — abitudini (§8.6) ————————————————————————————————


def elenco_abitudini(conn: sqlite3.Connection, ora: datetime) -> Risposta:
    """`/abitudini`: come stai andando questa settimana, con un tap per segnare.

    L'aderenza è la stessa che vede la dashboard, calcolata dalle stesse
    funzioni: §8.6 la vuole «sia in dashboard che a richiesta via bot», e due
    conti diversi che dicono due numeri diversi sono peggio di uno solo.
    """
    attive = dom_abitudini.elenco(conn)
    if not attive:
        return Risposta(
            testo=(
                "Non segui ancora nessuna abitudine.\n\n"
                "<i>Si aggiungono dalla dashboard, nella pagina Abitudini. "
                "Poi qui basta dirmi «oggi palestra e lettura».</i>"
            )
        )

    oggi = ora.date()
    lunedi = inizio_settimana(oggi)
    log = dom_abitudini.log_del_periodo(conn, da=lunedi - timedelta(days=60), a=oggi)

    righe: list[str] = []
    bottoni: list[list[Bottone]] = []
    for abitudine in attive:
        fatti = log.get(abitudine.id, set())
        nella_settimana = len([g for g in fatti if lunedi <= g <= oggi])
        striscia = dom_abitudini.striscia(fatti, oggi)
        spunta = "✅" if dom_abitudini.segnata(conn, abitudine.id, oggi) else "▫️"
        coda = f" · {plurale(striscia, 'giorno', 'giorni')} di fila" if striscia else ""
        righe.append(
            f"{spunta} <b>{escape(abitudine.nome)}</b> — "
            f"{nella_settimana}/{abitudine.target_settimanale}{escape(coda)}"
        )
        bottoni.append(
            [
                Bottone(
                    f"{'Togli' if spunta == '✅' else 'Segna'} {abitudine.nome}",
                    azioni.abitudine("oggi", abitudine.id),
                )
            ]
        )

    pezzi = ["<b>Questa settimana</b>\n" + "\n".join(righe)]
    ultimo = dom_abitudini.ultimo_report(conn, periodo=dom_abitudini.Periodo.SETTIMANA)
    if ultimo is not None and ultimo.chiave >= lunedi - timedelta(days=7):
        # Solo il resoconto recente: uno di tre settimane fa non racconta più
        # questa settimana, e riproporlo ad ogni `/abitudini` lo svuoterebbe.
        pezzi.append(f"<i>{escape(ultimo.testo)}</i>")
    return Risposta(testo="\n\n".join(pezzi), bottoni=bottoni)


def _azione_abitudine(
    conn: sqlite3.Connection, ora: datetime, nome: str, abitudine_id: int
) -> Risposta:
    """Il tap su un'abitudine: segna oggi, o toglie se era già segnata."""
    if nome != "oggi":
        return Risposta(testo="Questo bottone non è più valido.")
    try:
        dom_abitudini.leggi(conn, abitudine_id)  # esiste ancora?
    except dom_abitudini.AbitudineInesistente:
        return Risposta(testo="Quell'abitudine non c'è più.")

    if dom_abitudini.segnata(conn, abitudine_id, ora.date()):
        # Toglie invece di scrivere «non fatta»: un tap per sbaglio deve
        # riportare al silenzio, non affermare il contrario (§8.6).
        dom_abitudini.togli_log(conn, abitudine_id, ora.date())
    else:
        dom_abitudini.segna(conn, abitudine_id, giorno=ora.date(), fatto=True, ora=ora)
    return elenco_abitudini(conn, ora)


# — profilo (§8.4) ————————————————————————————————————


def _riga_candidato(candidato: dom_profilo.Candidato, indice: int) -> str:
    riga = f"{indice}. {escape(candidato.estratto)}"
    if candidato.chiarimento_risposta:
        riga += f"\n   <i>chiarito: {escape(candidato.chiarimento_risposta)}</i>"
    elif candidato.chiarimento_domanda:
        # Domanda fatta e mai risposta: qui è il momento di guardarla.
        riga += f"\n   <i>non hai risposto a: {escape(candidato.chiarimento_domanda)}</i>"
    return riga


def revisione_settimanale(conn: sqlite3.Connection) -> Risposta:
    """L'elenco dei candidati, con un tap per buttare quelli sbagliati (§8.4).

    Funziona per sottrazione: si scarta ciò che non ti rappresenta e il resto
    passa. Confermare uno per uno sarebbe più lavoro senza più controllo, e
    §8.4 dice che il grosso della disambiguazione è già stato fatto al momento
    della domanda.
    """
    candidati = dom_profilo.da_rivedere(conn)
    if not candidati:
        return Risposta(testo="Non ho raccolto niente di nuovo su di te questa settimana.")

    quanti = plurale(len(candidati), "segnale raccolto", "segnali raccolti")
    righe = [f"<b>Da mettere nel profilo</b>\n{quanti}:", ""]
    righe += [_riga_candidato(c, i) for i, c in enumerate(candidati, start=1)]
    righe += ["", "<i>Butta quelli che non ti rappresentano, poi aggiorno il profilo.</i>"]

    bottoni = [
        [Bottone(f"✕ {i}. {_taglia(c.estratto, 22)}", azioni.profilo("scarta", c.id))]
        for i, c in enumerate(candidati, start=1)
    ]
    bottoni.append([Bottone("Aggiorna il profilo", azioni.profilo("rifondi"))])
    return Risposta(testo="\n".join(righe), bottoni=bottoni)


def _testo_profilo(versione: dom_profilo.Versione, cambiamenti: list[str] | None = None) -> str:
    righe = [
        f"<b>Il tuo profilo</b> — versione {versione.versione}",
        "",
        escape(versione.testo),
    ]
    if cambiamenti:
        righe += ["", "<i>Cos'è cambiato:</i>"]
        righe += [f"<i>• {escape(c)}</i>" for c in cambiamenti]
    return "\n".join(righe)


def profilo(conn: sqlite3.Connection) -> Risposta:
    """`/profilo`: cosa Custode ha capito di te, e da quanti segnali."""
    versione = dom_profilo.corrente(conn)
    in_coda = len(dom_profilo.da_rivedere(conn))
    if versione is None:
        testo = (
            "Non ho ancora un profilo di te.\n\n"
            "<i>Si costruisce da solo con quello che mi racconti, e lo riscrivo "
            "una volta a settimana facendotelo vedere.</i>"
        )
        if in_coda:
            testo += f"\n\n{plurale(in_coda, 'segnale', 'segnali')} già in attesa."
        return Risposta(testo=testo)

    testo = _testo_profilo(versione)
    if in_coda:
        testo += (
            f"\n\n<i>{plurale(in_coda, 'segnale nuovo', 'segnali nuovi')} in attesa "
            "della prossima revisione.</i>"
        )
    return Risposta(testo=testo)


def rifondi_profilo(conn: sqlite3.Connection, ora: datetime, router: Router) -> Risposta:
    """Chiude la revisione e riscrive il profilo con Claude (§8.4).

    Il ritorno indietro è un bottone e non un'approvazione preventiva: §8.4
    tratta il versionamento proprio come la rete di sicurezza della rifusione.
    """
    approvati = dom_profilo.approva_rimanenti(conn)
    if not approvati:
        return Risposta(testo="Non è rimasto niente da mettere nel profilo.")

    attuale = dom_profilo.corrente(conn)
    ultimo = dom_diario.ultimo_riepilogo(conn)
    try:
        testo, cambiamenti = router_profilo.rifondi(
            router,
            profilo=attuale.testo if attuale else None,
            riepilogo=ultimo.testo if ultimo else None,
            candidati=[c.estratto for c in approvati],
        )
    except ErroreRouter as errore:
        # I candidati restano approvati e non rifusi: rientrano nella prossima
        # rifusione invece di perdersi.
        return Risposta(testo=escape(router_profilo.messaggio_errore(errore)))

    nuova = dom_profilo.salva_versione(conn, testo=testo, ora=ora, candidati=approvati)
    bottoni = (
        [[Bottone("Torna alla precedente", azioni.profilo("indietro"))]]
        if nuova.versione > 1
        else []
    )
    return Risposta(testo=_testo_profilo(nuova, cambiamenti), bottoni=bottoni)


def _azione_profilo(
    conn: sqlite3.Connection, ora: datetime, nome: str, argomento: str, router: Router | None
) -> Risposta:
    if nome in ("si", "no"):
        candidato = dom_profilo.chiarisci(
            conn,
            int(argomento),
            risposta="vale in generale" if nome == "si" else "era il momento",
            vale=nome == "si",
        )
        if nome == "si":
            return Risposta(
                testo=f"Segnato: <i>{escape(candidato.estratto)}</i>\nLo rivedremo insieme."
            )
        return Risposta(testo="Va bene, lascio perdere.")

    if nome == "scarta":
        dom_profilo.scarta_candidato(conn, int(argomento))
        return revisione_settimanale(conn)

    if nome == "rifondi":
        if router is None:
            return Risposta(testo="Non posso aggiornare il profilo da qui.")
        return rifondi_profilo(conn, ora, router)

    if nome == "indietro":
        # Va guardato *prima*: `torna_indietro` risponde None sia quando non
        # c'era niente da annullare, sia quando ha annullato l'unica versione
        # che c'era. Dire «non c'è nessuna versione precedente» nel secondo caso
        # farebbe credere che il profilo sia ancora lì.
        if dom_profilo.corrente(conn) is None:
            return Risposta(testo="Non c'è nessun profilo da annullare.")

        precedente = dom_profilo.torna_indietro(conn)
        coda = "\n\n<i>Riscrittura annullata: i segnali tornano in attesa.</i>"
        if precedente is None:
            return Risposta(
                testo="Annullata la prima versione: il profilo è di nuovo vuoto." + coda
            )
        return Risposta(testo=_testo_profilo(precedente) + coda)

    return Risposta(testo="Questo bottone non è più valido.")


def _dopo_azione(conn: sqlite3.Connection, ora: datetime, vista: Vista) -> Risposta:
    """Ridisegna l'elenco da cui è partito il tap, aggiornato."""
    if vista == "oggi":
        return riepilogo_oggi(conn, ora)
    if vista == "lista":
        return elenco_lista(conn)
    return elenco_task(conn, ora)


SCADENZE_RAPIDE = {"oggi": 0, "domani": 1, "settimana": 7}


def esegui_azione(
    conn: sqlite3.Connection, ora: datetime, dato: str, router: Router | None = None
) -> Risposta:
    """Applica il tap su un bottone e ritorna il messaggio aggiornato.

    `router` serve al solo bottone «Aggiorna il profilo», che fa una chiamata a
    Claude (§8.4): tutti gli altri bottoni sono logica pura sul database.
    """
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
        elif azione.dominio == "d" and azione.nome == "chiudi":
            # L'unico bottone del diario il cui argomento è una data e non un
            # id: chiude una giornata raccontata in ritardo (§8.4).
            return _chiudi_giornata(conn, ora, azione.argomento, router)
        elif azione.dominio == "d":
            return _azione_diario(conn, ora, azione.nome, int(azione.argomento))
        elif azione.dominio == "p":
            return _azione_profilo(conn, ora, azione.nome, azione.argomento, router)
        elif azione.dominio == "e":
            return _azione_spesa(conn, ora, azione.nome, int(azione.argomento))
        elif azione.dominio == "a":
            return _azione_abitudine(conn, ora, azione.nome, int(azione.argomento))
        elif azione.dominio == "x" and azione.nome == "annulla":
            return _annulla(conn, ora, azione.argomento)
        elif azione.dominio == "x" and azione.nome == "svuota":
            if azione.argomento == "si":
                dom_lista.svuota_presi(conn)
        else:
            return Risposta(testo="Questo bottone non è più valido.")
    except (
        dom_task.TaskInesistente,
        dom_lista.VoceInesistente,
        dom_diario.VoceInesistente,
        dom_profilo.CandidatoInesistente,
        dom_spese.SpesaInesistente,
    ):
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
