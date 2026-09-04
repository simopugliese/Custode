"""Abitudini e loro log (ARCHITECTURE.md §8.6).

Un'abitudine è un nome e una frequenza target settimanale («palestra, almeno 3
volte a settimana»); un log dice se in un certo giorno l'hai fatta. Tutto il
resto — aderenza in percentuale, obiettivi centrati, strisce — sono **conti
fatti in codice**, come chiede §8.6: nessuno di questi numeri passa da un
modello, e passarci sarebbe pagare una chiamata per fare una divisione che può
sbagliare.

Il modello serve altrove, e non entra mai qui: capire che «ho fatto x e y ma
non z» parla di tre abitudini esistenti sta in `custode_router.abitudini`
(DeepSeek), e il report narrativo che incrocia abitudini, diario e spese sta lì
accanto (Claude). Questo modulo riceve i risultati e li custodisce.

**Le funzioni di calcolo sono pure**: prendono insiemi di date, non una
connessione. Un'aderenza sbagliata è un bug che si nota mesi dopo, e volerlo
provare su ottanta combinazioni di giorni non deve costare ottanta database.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

GIORNI_SETTIMANA = 7


class AbitudineInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessuna abitudine."""


class PropostaInesistente(LookupError):
    """Sollevata quando la proposta da accettare o rifiutare non c'è più."""


class StatoProposta(StrEnum):
    IN_ATTESA = "in_attesa"
    ACCETTATA = "accettata"
    RIFIUTATA = "rifiutata"


class Periodo(StrEnum):
    SETTIMANA = "settimana"
    MESE = "mese"


@dataclass(frozen=True)
class Abitudine:
    id: int
    nome: str
    target_settimanale: int
    attiva: bool
    creata_il: datetime


@dataclass(frozen=True)
class Proposta:
    """Un adeguamento di target proposto dal report di Claude (§8.6)."""

    id: int
    abitudine_id: int
    abitudine: str
    target_proposto: int
    target_attuale: int
    motivazione: str
    stato: StatoProposta
    creata_il: datetime


@dataclass(frozen=True)
class Report:
    periodo: Periodo
    chiave: date
    testo: str
    generato_il: datetime


def _normalizza(nome: str) -> str:
    """Forma di confronto di un nome di abitudine.

    Serve a non far nascere «Palestra» accanto a «palestra  » per una maiuscola
    o uno spazio: il nome è anche ciò su cui il modello aggancia il testo
    libero, e due righe quasi identiche renderebbero quel matching ambiguo.
    """
    pulito = unicodedata.normalize("NFKC", nome).strip()
    return " ".join(pulito.split()).casefold()


# — abitudini —


def _da_riga(riga: sqlite3.Row) -> Abitudine:
    return Abitudine(
        id=riga["id"],
        nome=riga["nome"],
        target_settimanale=riga["frequenza_target_settimanale"],
        attiva=bool(riga["attivo"]),
        creata_il=datetime.fromisoformat(riga["creato_il"]),
    )


def elenco(conn: sqlite3.Connection, *, solo_attive: bool = True) -> list[Abitudine]:
    """Le abitudini, in ordine di creazione.

    L'ordine è quello in cui le hai aggiunte e non alfabetico: una lista che si
    riordina da sola ogni volta che ne aggiungi una costringe a ricercare col
    dito dove stava quella di prima.
    """
    dove = "WHERE attivo = 1" if solo_attive else ""
    righe = conn.execute(f"SELECT * FROM habits {dove} ORDER BY id ASC")
    return [_da_riga(r) for r in righe]


def leggi(conn: sqlite3.Connection, abitudine_id: int) -> Abitudine:
    riga = conn.execute("SELECT * FROM habits WHERE id = ?", (abitudine_id,)).fetchone()
    if riga is None:
        raise AbitudineInesistente(abitudine_id)
    return _da_riga(riga)


def trova(conn: sqlite3.Connection, nome: str) -> Abitudine | None:
    """L'abitudine con quel nome, comunque sia scritta. `None` se non c'è."""
    obiettivo = _normalizza(nome)
    for abitudine in elenco(conn, solo_attive=False):
        if _normalizza(abitudine.nome) == obiettivo:
            return abitudine
    return None


def _valida_target(target: int) -> int:
    if not 1 <= target <= GIORNI_SETTIMANA:
        raise ValueError("la frequenza target va da 1 a 7 volte a settimana")
    return target


def crea(
    conn: sqlite3.Connection, *, nome: str, target_settimanale: int, ora: datetime
) -> Abitudine:
    """Una nuova abitudine. Se il nome esiste già, la riattiva invece di duplicarla.

    Riaggiungere qualcosa che avevi disattivato è il modo naturale di
    riprenderla, e crearne una seconda con lo stesso nome spezzerebbe in due la
    storia già raccolta — che è esattamente ciò che rende utile riprenderla.
    """
    pulito = " ".join(nome.strip().split())
    if not pulito:
        raise ValueError("il nome di un'abitudine non può essere vuoto")
    _valida_target(target_settimanale)

    esistente = trova(conn, pulito)
    if esistente is not None:
        return modifica(conn, esistente.id, target_settimanale=target_settimanale, attiva=True)

    cursore = conn.execute(
        "INSERT INTO habits (nome, frequenza_target_settimanale, creato_il) VALUES (?, ?, ?)",
        (pulito, target_settimanale, ora.isoformat(timespec="seconds")),
    )
    return leggi(conn, int(cursore.lastrowid or 0))


def modifica(
    conn: sqlite3.Connection,
    abitudine_id: int,
    *,
    nome: str | None = None,
    target_settimanale: int | None = None,
    attiva: bool | None = None,
) -> Abitudine:
    """Cambia nome, target o stato. §8.6: tutto modificabile in qualsiasi momento."""
    abitudine = leggi(conn, abitudine_id)
    if nome is not None:
        pulito = " ".join(nome.strip().split())
        if not pulito:
            raise ValueError("il nome di un'abitudine non può essere vuoto")
        altra = trova(conn, pulito)
        if altra is not None and altra.id != abitudine_id:
            raise ValueError(f"esiste già un'abitudine chiamata «{altra.nome}»")
        conn.execute("UPDATE habits SET nome = ? WHERE id = ?", (pulito, abitudine_id))
    if target_settimanale is not None:
        conn.execute(
            "UPDATE habits SET frequenza_target_settimanale = ? WHERE id = ?",
            (_valida_target(target_settimanale), abitudine_id),
        )
    if attiva is not None:
        conn.execute("UPDATE habits SET attivo = ? WHERE id = ?", (int(attiva), abitudine_id))
    return leggi(conn, abitudine.id)


# — log —


def segna(
    conn: sqlite3.Connection,
    abitudine_id: int,
    *,
    giorno: date,
    fatto: bool,
    ora: datetime,
) -> None:
    """Registra (o corregge) il log di un giorno. Ridirlo aggiorna, non accoda."""
    leggi(conn, abitudine_id)  # esiste? altrimenti il log resterebbe orfano
    conn.execute(
        "INSERT INTO habit_logs (habit_id, data, fatto, creato_il) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (habit_id, data) DO UPDATE SET fatto = excluded.fatto",
        (abitudine_id, giorno.isoformat(), int(fatto), ora.isoformat(timespec="seconds")),
    )


def togli_log(conn: sqlite3.Connection, abitudine_id: int, giorno: date) -> None:
    """Cancella il log di un giorno: serve ad «Annulla» (§8.1).

    Torna al silenzio, che non è la stessa cosa di un «non fatto»: annullare
    deve rimettere le cose com'erano, non scrivere il contrario.
    """
    conn.execute(
        "DELETE FROM habit_logs WHERE habit_id = ? AND data = ?",
        (abitudine_id, giorno.isoformat()),
    )


def togli_log_creati_il(conn: sqlite3.Connection, ora: datetime) -> list[str]:
    """Cancella i log scritti in quell'istante. Ritorna i nomi delle abitudini.

    È così che funziona «Annulla» su un messaggio come «palestra e lettura ma
    non meditazione», che segna tre abitudini in un colpo solo: il
    `callback_data` di Telegram sta in 64 byte e non può portarsi dietro una
    lista di id, mentre l'istante di scrittura — uno solo per messaggio, perché
    `ora` attraversa tutta l'esecuzione — li identifica tutti insieme. Ed è la
    cosa giusta anche a prescindere dai byte: quel messaggio è stato **un**
    gesto, e disfarlo a metà non è quello che si intende con «Annulla».
    """
    istante = ora.isoformat(timespec="seconds")
    righe = conn.execute(
        "SELECT h.nome FROM habit_logs l JOIN habits h ON h.id = l.habit_id"
        " WHERE l.creato_il = ? ORDER BY h.id",
        (istante,),
    ).fetchall()
    conn.execute("DELETE FROM habit_logs WHERE creato_il = ?", (istante,))
    return [r["nome"] for r in righe]


def log_del_periodo(
    conn: sqlite3.Connection, *, da: date, a: date, solo_fatti: bool = True
) -> dict[int, set[date]]:
    """I giorni segnati per ciascuna abitudine nell'intervallo, in una query sola.

    Una query per abitudine costerebbe una decina di viaggi per disegnare una
    pagina che ne mostra sette, e i conti che seguono sono tutti su insiemi di
    date: è quella la forma in cui servono.
    """
    dove = "AND fatto = 1" if solo_fatti else ""
    righe = conn.execute(
        f"SELECT habit_id, data FROM habit_logs WHERE data BETWEEN ? AND ? {dove}",
        (da.isoformat(), a.isoformat()),
    )
    per_abitudine: dict[int, set[date]] = {}
    for riga in righe:
        per_abitudine.setdefault(riga["habit_id"], set()).add(date.fromisoformat(riga["data"]))
    return per_abitudine


def segnata(conn: sqlite3.Connection, abitudine_id: int, giorno: date) -> bool | None:
    """`True`/`False` se quel giorno c'è un log, `None` se non ne hai mai parlato."""
    riga = conn.execute(
        "SELECT fatto FROM habit_logs WHERE habit_id = ? AND data = ?",
        (abitudine_id, giorno.isoformat()),
    ).fetchone()
    return None if riga is None else bool(riga["fatto"])


# — i conti, tutti in codice: nessuno di questi passa da un modello (§8.6) —


def giorni_fra(da: date, a: date) -> list[date]:
    """Le date dell'intervallo, estremi compresi."""
    return [da + timedelta(days=i) for i in range((a - da).days + 1)]


def attesi(target_settimanale: int, giorni_trascorsi: int) -> float:
    """Quante volte avresti dovuto farla in `giorni_trascorsi` giorni.

    Il target è settimanale (§7), quindi il mese si ricava in proporzione ai
    giorni **trascorsi**, non a quelli del mese: il 3 del mese un'aderenza
    calcolata su 30 giorni direbbe solo che il mese è appena cominciato.
    """
    return target_settimanale * giorni_trascorsi / GIORNI_SETTIMANA


def aderenza(fatti: int, attesi_nel_periodo: float) -> float:
    """Quota del target centrata, da 0 a 1, con il tetto a 1.

    Sopra il 100% non si va: aver fatto palestra cinque volte con un target di
    tre è una bella settimana, ma in una media con le altre abitudini quel 167%
    coprirebbe una che non hai fatto mai.
    """
    if attesi_nel_periodo <= 0:
        return 0.0
    return min(fatti / attesi_nel_periodo, 1.0)


def percentuale(quota: float) -> int:
    """Da 0-1 a un intero: il contratto mostra numeri interi, non 63,49%."""
    return round(quota * 100)


def striscia(fatti: set[date], oggi: date) -> int:
    """Giorni consecutivi in cui l'hai fatta, contando all'indietro da oggi.

    **Se oggi non è segnato, la striscia si conta fino a ieri.** Altrimenti alle
    nove del mattino ogni striscia sarebbe zero, e il numero direbbe che ora è
    invece di come stai andando. È lo stesso motivo per cui la si conta in
    giorni anche per un'abitudine da tre volte a settimana: la striscia è
    «quanti giorni di fila», e chi ha un target basso la vede semplicemente
    corta — la sua costanza la racconta l'aderenza, che è il numero giusto lì.
    """
    inizio = oggi if oggi in fatti else oggi - timedelta(days=1)
    quanti = 0
    giorno = inizio
    while giorno in fatti:
        quanti += 1
        giorno -= timedelta(days=1)
    return quanti


def presenze(fatti: set[date], giorni: list[date]) -> list[bool]:
    """I pallini di una riga: uno per giorno, nell'ordine dato."""
    return [giorno in fatti for giorno in giorni]


# — proposte di adeguamento del target (§8.6) —


def _proposta_da_riga(riga: sqlite3.Row) -> Proposta:
    return Proposta(
        id=riga["id"],
        abitudine_id=riga["habit_id"],
        abitudine=riga["abitudine"],
        target_proposto=riga["target_proposto"],
        target_attuale=riga["target_attuale"],
        motivazione=riga["motivazione"],
        stato=StatoProposta(riga["stato"]),
        creata_il=datetime.fromisoformat(riga["creata_il"]),
    )


_SELECT_PROPOSTA = (
    "SELECT p.*, h.nome AS abitudine,"
    " h.frequenza_target_settimanale AS target_attuale"
    " FROM habit_proposals p JOIN habits h ON h.id = p.habit_id"
)


def proponi(
    conn: sqlite3.Connection,
    abitudine_id: int,
    *,
    target_proposto: int,
    motivazione: str,
    ora: datetime,
) -> Proposta:
    """Mette in attesa un adeguamento del target. Non cambia niente da sola."""
    abitudine = leggi(conn, abitudine_id)
    _valida_target(target_proposto)
    if target_proposto == abitudine.target_settimanale:
        raise ValueError("il target proposto è già quello attuale")
    if not motivazione.strip():
        raise ValueError("una proposta senza motivazione non è valutabile")

    # Una proposta alla volta per abitudine: quella vecchia decade, perché è
    # stata scritta su numeri che nel frattempo sono cambiati.
    conn.execute(
        "DELETE FROM habit_proposals WHERE habit_id = ? AND stato = 'in_attesa'",
        (abitudine_id,),
    )
    cursore = conn.execute(
        "INSERT INTO habit_proposals"
        " (habit_id, tipo, target_proposto, motivazione, creata_il) VALUES (?, 'target', ?, ?, ?)",
        (
            abitudine_id,
            target_proposto,
            motivazione.strip(),
            ora.isoformat(timespec="seconds"),
        ),
    )
    riga = conn.execute(
        f"{_SELECT_PROPOSTA} WHERE p.id = ?", (int(cursore.lastrowid or 0),)
    ).fetchone()
    assert riga is not None  # appena scritta
    return _proposta_da_riga(riga)


def proposta_aperta(conn: sqlite3.Connection) -> Proposta | None:
    """La proposta da mostrare, se ce n'è una: la più recente ancora in attesa.

    Il contratto ne mostra **una**, e va bene così: due riquadri «Custode
    propone» uno sopra l'altro sono un modulo che chiede, non che aiuta.
    """
    riga = conn.execute(
        f"{_SELECT_PROPOSTA} WHERE p.stato = 'in_attesa' AND h.attivo = 1"
        " ORDER BY p.creata_il DESC, p.id DESC LIMIT 1"
    ).fetchone()
    return _proposta_da_riga(riga) if riga is not None else None


def decidi(conn: sqlite3.Connection, proposta_id: int, *, accetta: bool, ora: datetime) -> Proposta:
    """«Accetta» applica il nuovo target, «No, lascia com'è» archivia e basta."""
    riga = conn.execute(f"{_SELECT_PROPOSTA} WHERE p.id = ?", (proposta_id,)).fetchone()
    if riga is None:
        raise PropostaInesistente(proposta_id)
    proposta = _proposta_da_riga(riga)
    if proposta.stato is not StatoProposta.IN_ATTESA:
        raise ValueError("questa proposta è già stata decisa")

    conn.execute(
        "UPDATE habit_proposals SET stato = ?, decisa_il = ? WHERE id = ?",
        (
            StatoProposta.ACCETTATA.value if accetta else StatoProposta.RIFIUTATA.value,
            ora.isoformat(timespec="seconds"),
            proposta_id,
        ),
    )
    if accetta:
        modifica(conn, proposta.abitudine_id, target_settimanale=proposta.target_proposto)
    riga = conn.execute(f"{_SELECT_PROPOSTA} WHERE p.id = ?", (proposta_id,)).fetchone()
    assert riga is not None  # appena aggiornata
    return _proposta_da_riga(riga)


def rifiutata_di_recente(conn: sqlite3.Connection, abitudine_id: int, *, dal: date) -> bool:
    """Hai già detto di no a un adeguamento di questa abitudine da poco?

    Serve a non riproporre la stessa cosa ogni settimana: i numeri che l'hanno
    fatta nascere cambiano lentamente, quindi la proposta successiva sarebbe
    quasi identica, e un modulo che ripete la stessa domanda dopo un no è un
    modulo che non ascolta.
    """
    riga = conn.execute(
        "SELECT 1 FROM habit_proposals WHERE habit_id = ? AND stato = 'rifiutata'"
        " AND date(decisa_il) >= ? LIMIT 1",
        (abitudine_id, dal.isoformat()),
    ).fetchone()
    return riga is not None


# — report narrativi (§8.6) —


def salva_report(
    conn: sqlite3.Connection, *, periodo: Periodo, chiave: date, testo: str, ora: datetime
) -> Report:
    conn.execute(
        "INSERT INTO habit_reports (periodo, chiave, testo, generato_il) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (periodo, chiave) DO UPDATE SET"
        " testo = excluded.testo, generato_il = excluded.generato_il",
        (periodo.value, chiave.isoformat(), testo.strip(), ora.isoformat(timespec="seconds")),
    )
    salvato = report(conn, periodo=periodo, chiave=chiave)
    assert salvato is not None  # appena scritto
    return salvato


def report(conn: sqlite3.Connection, *, periodo: Periodo, chiave: date) -> Report | None:
    riga = conn.execute(
        "SELECT * FROM habit_reports WHERE periodo = ? AND chiave = ?",
        (periodo.value, chiave.isoformat()),
    ).fetchone()
    return _report_da_riga(riga) if riga is not None else None


def ultimo_report(conn: sqlite3.Connection, *, periodo: Periodo) -> Report | None:
    """L'ultimo scritto per quel periodo: è quello che la pagina mostra."""
    riga = conn.execute(
        "SELECT * FROM habit_reports WHERE periodo = ? ORDER BY chiave DESC LIMIT 1",
        (periodo.value,),
    ).fetchone()
    return _report_da_riga(riga) if riga is not None else None


def _report_da_riga(riga: sqlite3.Row) -> Report:
    return Report(
        periodo=Periodo(riga["periodo"]),
        chiave=date.fromisoformat(riga["chiave"]),
        testo=riga["testo"],
        generato_il=datetime.fromisoformat(riga["generato_il"]),
    )
