"""Gli eventi del calendario, come Custode li conserva (ARCHITECTURE.md §8.10).

Questo modulo **non sa che dietro c'è Google**: riceve eventi già letti e
convertiti e li custodisce. È la stessa divisione di `spese` e `abitudini` —
chi parla col mondo esterno sta nel suo pacchetto (`custode_calendario`), e
`core` resta senza dipendenze di rete. Per questo l'ingresso di `sincronizza`
è un `EventoEsterno`, un Protocol descritto qui: `custode_calendario.Evento` lo
soddisfa per forma, senza che `core` debba importarlo.

**La tabella è un archivio, non una cache.** §8.10 vuole che le regole
auto-proposte cerchino pattern «nei dati storici (calendario, abitudini, orari
in cui scrivi)»: il calendario di tre mesi fa è uno degli ingressi, quindi ciò
che esce dalla finestra sincronizzata resta dov'è invece di essere potato.

**Si cancella solo dentro la finestra, e solo dopo una lettura completa.** Un
evento che Google non restituisce più mentre è dentro la finestra è disdetto
davvero, e lasciarlo renderebbe sbagliata la prima cosa che si vede in Home.
Ma la stessa cancellazione, applicata al risultato di una lettura andata a metà,
svuoterebbe la settimana: la riconciliazione è un parametro esplicito di
`sincronizza`, e chi la chiama può farlo solo quando ha in mano *tutte* le
pagine di una risposta riuscita.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

FONTE_GOOGLE = "google"


class Tipo(StrEnum):
    """Il tag di §8.10. Oggi ogni evento nasce `ALTRO`.

    A deciderlo sarà il pezzo successivo — l'IA propone, tu correggi, e per una
    serie ricorrente la scelta vale una volta sola. Qui il tipo si **conserva**:
    è la ragione per cui risincronizzare aggiorna la riga invece di rifarla.
    """

    LEZIONE = "lezione"
    PALESTRA = "palestra"
    VIAGGIO = "viaggio"
    ALTRO = "altro"


class EventoEsterno(Protocol):
    """Un evento come lo consegna una sorgente, prima di entrare nel database.

    Combacia con `custode_calendario.Evento` senza che `core` lo importi: la
    dipendenza va in una direzione sola, e un feed iCal futuro non dovrà
    passare per Google per essere salvato.
    """

    @property
    def id(self) -> str: ...
    @property
    def titolo(self) -> str: ...
    @property
    def inizio(self) -> datetime: ...
    @property
    def fine(self) -> datetime: ...
    @property
    def tutto_il_giorno(self) -> bool: ...
    @property
    def luogo(self) -> str: ...
    @property
    def serie_id(self) -> str: ...


@dataclass(frozen=True)
class Evento:
    """Un evento già in archivio: ha un id nostro e un tipo."""

    id: int
    fonte: str
    id_esterno: str
    titolo: str
    inizio: datetime
    fine: datetime
    tutto_il_giorno: bool
    luogo: str
    serie_id: str
    tipo: Tipo
    sincronizzato_il: datetime

    @property
    def giorno(self) -> date:
        return self.inizio.date()


@dataclass(frozen=True)
class Esito:
    """Cos'è cambiato in una sincronizzazione.

    Serve ai log del worker: un sync che cancella venti eventi è la cosa da
    poter leggere il giorno dopo, quando ti accorgi che manca una lezione.
    """

    nuovi: int = 0
    aggiornati: int = 0
    invariati: int = 0
    rimossi: int = 0

    @property
    def totale_visti(self) -> int:
        return self.nuovi + self.aggiornati + self.invariati


def _iso(momento: datetime) -> str:
    """La forma con cui un istante sta in tabella: ISO al secondo.

    È l'unica porta di scrittura, e il confronto «è cambiato?» passa di qui su
    **entrambi** i lati — la forma salvata contro la forma che si salverebbe.
    Non è un dettaglio di stile: la fine di un evento di giornata arriva con i
    microsecondi (`time.max`), e confrontare i datetime invece delle stringhe
    farebbe risultare *aggiornato* ad ogni giro ogni evento di giornata che
    esiste, per sempre.
    """
    return momento.isoformat(timespec="seconds")


def _da_riga(riga: sqlite3.Row) -> Evento:
    return Evento(
        id=riga["id"],
        fonte=riga["fonte"],
        id_esterno=riga["id_esterno"],
        titolo=riga["titolo"],
        inizio=datetime.fromisoformat(riga["inizio"]),
        fine=datetime.fromisoformat(riga["fine"]),
        tutto_il_giorno=bool(riga["tutto_il_giorno"]),
        luogo=riga["luogo"],
        serie_id=riga["serie_id"],
        tipo=Tipo(riga["tipo"]),
        sincronizzato_il=datetime.fromisoformat(riga["sincronizzato_il"]),
    )


# — lettura —


def fra(conn: sqlite3.Connection, da: date, a: date, *, fonte: str | None = None) -> list[Evento]:
    """Gli eventi che **toccano** l'intervallo fra due giorni, estremi inclusi.

    «Toccano» e non «cominciano»: un viaggio che parte venerdì e finisce
    domenica è un impegno anche di sabato, e un filtro sul solo `inizio` lo
    farebbe sparire dal sabato. Il confronto è lessicografico sull'ISO, che per
    date della stessa forma è l'ordine cronologico.
    """
    if da > a:
        raise ValueError(f"intervallo rovesciato: da {da} a {a}")

    condizioni = ["inizio < ?", "fine >= ?"]
    valori: list[object] = [(a + timedelta(days=1)).isoformat(), da.isoformat()]
    if fonte is not None:
        condizioni.append("fonte = ?")
        valori.append(fonte)

    righe = conn.execute(
        f"SELECT * FROM calendar_events WHERE {' AND '.join(condizioni)}"
        " ORDER BY inizio ASC, titolo ASC",
        valori,
    )
    return [_da_riga(r) for r in righe]


def del_giorno(conn: sqlite3.Connection, giorno: date, *, fonte: str | None = None) -> list[Evento]:
    """Gli impegni di una giornata: è ciò che chiede la Home."""
    return fra(conn, giorno, giorno, fonte=fonte)


# — scrittura —


def sincronizza(
    conn: sqlite3.Connection,
    eventi: list[EventoEsterno],
    *,
    da: date,
    a: date,
    ora: datetime,
    fonte: str = FONTE_GOOGLE,
) -> Esito:
    """Porta in pari l'archivio con quello che la sorgente ha appena detto.

    `da`/`a` sono la finestra **davvero chiesta** alla sorgente, e delimitano
    l'unica zona in cui si cancella: fuori di lì il silenzio della sorgente non
    vuol dire niente, perché non le è stato chiesto niente. Passare una
    finestra più larga di quella interrogata cancellerebbe eventi vivi.

    Va chiamata **solo dopo una lettura riuscita e completa** (tutte le pagine):
    su una risposta parziale, l'assenza di un evento non significa che è stato
    disdetto.
    """
    if da > a:
        raise ValueError(f"intervallo rovesciato: da {da} a {a}")

    # Tutto l'archivio di questa fonte in un colpo solo. Sono qualche centinaio
    # di righe all'anno: leggerle ogni quarto d'ora costa meno della ginnastica
    # di clausole IN che servirebbe a leggerne un sottoinsieme, e serve
    # comunque l'intero archivio — la sorgente può restituire un evento che
    # comincia *prima* della finestra e la attraversa.
    esistenti = {
        riga["id_esterno"]: riga
        for riga in conn.execute("SELECT * FROM calendar_events WHERE fonte = ?", (fonte,))
    }

    timbro = _iso(ora)
    nuovi = aggiornati = invariati = 0
    visti: set[str] = set()

    for evento in eventi:
        if evento.id in visti:
            # La stessa occorrenza due volte nella stessa risposta non dovrebbe
            # capitare, ma se capitasse il secondo passaggio la conterebbe come
            # «aggiornata» dopo averla appena scritta.
            continue
        visti.add(evento.id)

        campi = (
            evento.titolo,
            _iso(evento.inizio),
            _iso(evento.fine),
            int(evento.tutto_il_giorno),
            evento.luogo,
            evento.serie_id,
        )
        riga = esistenti.get(evento.id)

        if riga is None:
            conn.execute(
                "INSERT INTO calendar_events"
                " (fonte, id_esterno, titolo, inizio, fine, tutto_il_giorno, luogo,"
                "  serie_id, sincronizzato_il)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fonte, evento.id, *campi, timbro),
            )
            nuovi += 1
            continue

        # `tipo` non compare fra i campi aggiornati, ed è il punto: è l'unica
        # colonna che non viene dalla sorgente. Riscriverla ad ogni sync
        # cancellerebbe il tag che hai corretto a mano.
        precedenti = (
            riga["titolo"],
            riga["inizio"],
            riga["fine"],
            riga["tutto_il_giorno"],
            riga["luogo"],
            riga["serie_id"],
        )
        if precedenti == campi:
            # Si aggiorna comunque `sincronizzato_il`: dice «visto adesso», non
            # «cambiato adesso», ed è ciò che distingue un evento immobile da
            # uno che la sorgente ha smesso di nominare.
            conn.execute(
                "UPDATE calendar_events SET sincronizzato_il = ? WHERE id = ?",
                (timbro, riga["id"]),
            )
            invariati += 1
            continue

        conn.execute(
            "UPDATE calendar_events SET titolo = ?, inizio = ?, fine = ?,"
            " tutto_il_giorno = ?, luogo = ?, serie_id = ?, sincronizzato_il = ?"
            " WHERE id = ?",
            (*campi, timbro, riga["id"]),
        )
        aggiornati += 1

    rimossi = _riconcilia(conn, visti, da=da, a=a, fonte=fonte)
    return Esito(nuovi=nuovi, aggiornati=aggiornati, invariati=invariati, rimossi=rimossi)


def _riconcilia(conn: sqlite3.Connection, visti: set[str], *, da: date, a: date, fonte: str) -> int:
    """Toglie dall'archivio gli eventi disdetti, e solo quelli.

    I candidati sono le righe che **cominciano** dentro la finestra, non quelle
    che la toccano: una sorgente interrogata su [da, a] restituisce tutto ciò
    che comincia lì dentro, quindi il suo silenzio su una di quelle righe è
    un'informazione. Su un evento cominciato *prima* della finestra non lo è —
    dipende da come la sorgente tratta le sovrapposizioni — e cancellarlo
    sarebbe una deduzione da un dato che non abbiamo chiesto.
    """
    candidate = conn.execute(
        "SELECT id, id_esterno FROM calendar_events"
        " WHERE fonte = ? AND inizio >= ? AND inizio < ?",
        (fonte, da.isoformat(), (a + timedelta(days=1)).isoformat()),
    ).fetchall()

    da_togliere = [riga["id"] for riga in candidate if riga["id_esterno"] not in visti]
    for evento_id in da_togliere:
        conn.execute("DELETE FROM calendar_events WHERE id = ?", (evento_id,))
    return len(da_togliere)
