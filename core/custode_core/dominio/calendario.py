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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

FONTE_GOOGLE = "google"


class EventoInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessun evento."""


class Tipo(StrEnum):
    """Il tag di §8.10.

    Un evento nuovo nasce `ALTRO` finché il job di tagging non l'ha guardato —
    ma `ALTRO` è anche un esito legittimo (un ricevimento non è nessuno degli
    altri tre): a distinguere "mai guardato" da "guardato e detto altro" è
    `Evento.tag_proposto_il`, non il tipo. La scelta vale una volta per l'intera
    serie ricorrente (`serie_id`), mai per la singola occorrenza. Qui il tipo si
    **conserva**: è la ragione per cui risincronizzare aggiorna la riga invece
    di rifarla.
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
    tag_proposto_il: datetime | None
    """Quando un tag è stato scritto l'ultima volta, dall'IA o da te. `None`
    finché nessuno l'ha ancora guardato — vedi `Tipo`."""
    tag_confermato_da_te: bool
    """Vero se l'ultima scrittura del tag è stata una tua correzione, non una
    proposta dell'IA. Serve solo alla pagina Calendario per mostrarlo."""

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
        tag_proposto_il=(
            datetime.fromisoformat(riga["tag_proposto_il"])
            if riga["tag_proposto_il"] is not None
            else None
        ),
        tag_confermato_da_te=bool(riga["tag_confermato_da_te"]),
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
    eventi: Sequence[EventoEsterno],
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

    `Sequence` e non `list` perché `list` è invariante: una `list[Evento]` di
    una sorgente concreta non è una `list[EventoEsterno]`, e chiamare questa
    funzione costringerebbe ogni sorgente a ricopiare la sua lista.
    """
    if da > a:
        raise ValueError(f"intervallo rovesciato: da {da} a {a}")

    # Tutto l'archivio di questa fonte in un colpo solo. Sono qualche centinaio
    # di righe all'anno: leggerle ogni sincronizzazione costa meno della
    # ginnastica di clausole IN che servirebbe a leggerne un sottoinsieme, e
    # serve comunque l'intero archivio — la sorgente può restituire un evento
    # che comincia *prima* della finestra e la attraversa.
    tutte = list(conn.execute("SELECT * FROM calendar_events WHERE fonte = ?", (fonte,)))
    esistenti = {riga["id_esterno"]: riga for riga in tutte}

    # Una serie già taggata non deve tornare 'altro' alla prima occorrenza
    # nuova: senza questo, ogni settimana la lezione di martedì rinascerebbe
    # senza tag, e il job di tagging la riproporrebbe da capo — il duplicato
    # che il tagging deve evitare. Basta una riga qualunque della serie: per
    # costruzione tutte condividono lo stesso tag (`applica_tag` scrive sempre
    # l'intera serie insieme).
    per_serie = {riga["serie_id"]: riga for riga in tutte if riga["serie_id"]}

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
            eredita = per_serie.get(evento.serie_id) if evento.serie_id else None
            conn.execute(
                "INSERT INTO calendar_events"
                " (fonte, id_esterno, titolo, inizio, fine, tutto_il_giorno, luogo,"
                "  serie_id, sincronizzato_il, tipo, tag_proposto_il, tag_confermato_da_te)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fonte,
                    evento.id,
                    *campi,
                    timbro,
                    eredita["tipo"] if eredita is not None else Tipo.ALTRO.value,
                    eredita["tag_proposto_il"] if eredita is not None else None,
                    eredita["tag_confermato_da_te"] if eredita is not None else 0,
                ),
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


# — il tag (§8.10, pezzo 5) —


@dataclass(frozen=True)
class GruppoDaTaggare:
    """Una serie ricorrente, o un evento singolo, che nessuno ha ancora guardato.

    È l'unità su cui si decide un tag: tutte le occorrenze con lo stesso
    `serie_id` lo condividono (§8.10, "resta fisso per gli eventi ricorrenti"),
    quindi un evento senza serie è un gruppo fatto di una riga sola.
    """

    fonte: str
    serie_id: str
    """Vuoto per un evento singolo."""
    evento_id: int | None
    """Valorizzato solo per un evento singolo: è la riga su cui scrivere."""
    titolo: str
    """Un titolo rappresentativo del gruppo, per chi deve proporre il tag."""


def gruppi_senza_tag(
    conn: sqlite3.Connection, *, fonte: str = FONTE_GOOGLE
) -> list[GruppoDaTaggare]:
    """Le serie e gli eventi singoli che il tagging non ha ancora guardato.

    Un gruppo per serie, non una riga per occorrenza: grazie all'eredità del
    tag in `sincronizza`, dentro una stessa serie o tutte le righe hanno
    `tag_proposto_il` valorizzato o nessuna — non serve interrogare più di una
    riga a serie per sapere se è da proporre.
    """
    righe = conn.execute(
        "SELECT id, serie_id, titolo FROM calendar_events"
        " WHERE fonte = ? AND tag_proposto_il IS NULL"
        " ORDER BY inizio ASC",
        (fonte,),
    )

    visti: set[str] = set()
    gruppi: list[GruppoDaTaggare] = []
    for riga in righe:
        serie = riga["serie_id"]
        chiave = serie or f"#{riga['id']}"
        if chiave in visti:
            continue
        visti.add(chiave)
        gruppi.append(
            GruppoDaTaggare(
                fonte=fonte,
                serie_id=serie,
                evento_id=None if serie else riga["id"],
                titolo=riga["titolo"],
            )
        )
    return gruppi


def applica_tag(
    conn: sqlite3.Connection,
    gruppo: GruppoDaTaggare,
    tipo: Tipo,
    ora: datetime,
    *,
    confermato_da_te: bool = False,
) -> int:
    """Scrive il tag su tutte le righe del gruppo. Ritorna quante ne ha toccate.

    Una serie si scrive tutta insieme: scriverla riga per riga lascerebbe le
    occorrenze non toccate — passate o non ancora sincronizzate — senza tag, e
    la prossima sincronizzazione le riproporrebbe da capo.
    """
    timbro = _iso(ora)
    if gruppo.serie_id:
        cursore = conn.execute(
            "UPDATE calendar_events"
            " SET tipo = ?, tag_proposto_il = ?, tag_confermato_da_te = ?"
            " WHERE fonte = ? AND serie_id = ?",
            (tipo.value, timbro, int(confermato_da_te), gruppo.fonte, gruppo.serie_id),
        )
    else:
        assert gruppo.evento_id is not None  # un gruppo o ha una serie, o un id
        cursore = conn.execute(
            "UPDATE calendar_events SET tipo = ?, tag_proposto_il = ?, tag_confermato_da_te = ?"
            " WHERE id = ?",
            (tipo.value, timbro, int(confermato_da_te), gruppo.evento_id),
        )
    return cursore.rowcount


def correggi_tag(conn: sqlite3.Connection, evento_id: int, tipo: Tipo, ora: datetime) -> int:
    """La correzione a mano di §8.10 ("tu correggi se serve").

    Parte da un evento che vedi — nella pagina Calendario, per esempio — e
    tocca tutta la sua serie se ne ha una: è la stessa regola di `applica_tag`,
    letta dal verso di chi corregge invece che di chi propone.
    """
    riga = conn.execute(
        "SELECT fonte, serie_id FROM calendar_events WHERE id = ?", (evento_id,)
    ).fetchone()
    if riga is None:
        raise EventoInesistente(evento_id)

    gruppo = GruppoDaTaggare(
        fonte=riga["fonte"],
        serie_id=riga["serie_id"],
        evento_id=None if riga["serie_id"] else evento_id,
        titolo="",
    )
    return applica_tag(conn, gruppo, tipo, ora, confermato_da_te=True)
