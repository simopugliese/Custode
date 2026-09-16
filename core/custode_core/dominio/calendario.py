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

**I tipi li decidi tu** (pezzo 6). Erano quattro e fissi, incisi in un CHECK e
in una StrEnum; adesso stanno in `calendar_tags` e i quattro di prima ci sono
dentro come dati iniziali. Un evento porta lo **slug** del suo tag e non
l'etichetta: rinominare un tipo tocca una riga sola e nessun evento, e
archiviarne uno lo toglie dal menu senza toglierlo agli impegni che ce l'hanno.

**Si cancella solo dentro la finestra, e solo dopo una lettura completa.** Un
evento che Google non restituisce più mentre è dentro la finestra è disdetto
davvero, e lasciarlo renderebbe sbagliata la prima cosa che si vede in Home.
Ma la stessa cancellazione, applicata al risultato di una lettura andata a metà,
svuoterebbe la settimana: la riconciliazione è un parametro esplicito di
`sincronizza`, e chi la chiama può farlo solo quando ha in mano *tutte* le
pagine di una risposta riuscita.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

FONTE_GOOGLE = "google"


class EventoInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessun evento."""


SLUG_ALTRO = "altro"
"""Il tag con cui nasce ogni evento, e il ripiego di una risposta illeggibile.

È l'unico slug che il codice conosce per nome, ed è la ragione per cui la sua
riga in `calendar_tags` è marcata `di_sistema`: si può rinominare, non
archiviare né cancellare. `altro` è anche un esito **legittimo** del modello (un
ricevimento non è nessuno degli altri) — a distinguere "mai guardato" da
"guardato e detto altro" è `Evento.tag_proposto_il`, non il tipo.
"""


class TagInesistente(LookupError):
    """Lo slug richiesto non corrisponde a nessun tag."""


class TagDiSistema(ValueError):
    """Si è provato ad archiviare o cancellare `altro`."""


class TagInUso(ValueError):
    """Si è provato a cancellare un tag che degli eventi usano ancora.

    Porta con sé **quanti** sono: è l'unico numero che rende l'errore una
    risposta utile («47 impegni lo usano, archivialo invece») invece di un no.
    """

    def __init__(self, slug: str, eventi: int) -> None:
        super().__init__(f"«{slug}» è usato da {eventi} eventi")
        self.slug = slug
        self.eventi = eventi


class NomeTagGiaUsato(ValueError):
    """Esiste già un tag con questo nome, o con lo slug che ne uscirebbe."""


@dataclass(frozen=True)
class Tag:
    """Un tipo di evento, adesso che li decidi tu (§8.10, pezzo 6).

    **Due nomi e non uno.** `slug` è l'identificatore: deciso alla creazione,
    mai più toccato, ed è ciò che esce dal database — sta in
    `calendar_events.tipo`, nel campo `tipo` del contratto REST, nell'enum che
    riceve il modello e domani nel riferimento di una regola di contesto.
    `nome` è l'etichetta che leggi, e cambiarla tocca questa riga sola: zero
    eventi, perché nessun evento porta scritto il nome.

    `descrizione` è la riga che il modello legge per decidere, non un commento:
    è quella frase a fare il lavoro del tagging automatico, ed è la manopola con
    cui si aggiusta il tiro quando classifica male.
    """

    id: int
    slug: str
    nome: str
    descrizione: str
    di_sistema: bool
    """`altro`: rinominabile, mai archiviabile né cancellabile."""
    attivo: bool
    """Archiviato (`False`) vuol dire fuori dal menu e fuori dal prompt, non
    cancellato: gli eventi che ce l'hanno se lo tengono."""
    creato_il: datetime


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
    tipo: str
    """Lo slug del suo tag (`calendar_tags.slug`), non l'etichetta: chi deve
    mostrarla la cerca in `mappa_tag`. L'etichetta cambia quando rinomini un
    tag, e un evento che se la portasse dietro resterebbe indietro."""
    sincronizzato_il: datetime
    tag_proposto_il: datetime | None
    """Quando un tag è stato scritto l'ultima volta, dall'IA o da te. `None`
    finché nessuno l'ha ancora guardato — vedi `SLUG_ALTRO`."""
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
        tipo=riga["tipo"],
        sincronizzato_il=datetime.fromisoformat(riga["sincronizzato_il"]),
        tag_proposto_il=(
            datetime.fromisoformat(riga["tag_proposto_il"])
            if riga["tag_proposto_il"] is not None
            else None
        ),
        tag_confermato_da_te=bool(riga["tag_confermato_da_te"]),
    )


# — i tag, adesso che li decidi tu (§8.10, pezzo 6) —


def _normalizza(nome: str) -> str:
    """Forma di confronto di un nome di tag, come per le abitudini.

    Serve a non far nascere «Palestra» accanto a «palestra  » per una maiuscola
    o uno spazio: due righe quasi identiche renderebbero ambiguo sia il menu di
    correzione sia l'elenco che legge il modello.
    """
    pulito = unicodedata.normalize("NFKC", nome).strip()
    return " ".join(pulito.split()).casefold()


def _pulisci(testo: str) -> str:
    return " ".join(testo.strip().split())


MAX_CARATTERI_SLUG = 40


def slug_da(nome: str) -> str:
    """Lo slug che nascerebbe da questo nome.

    Accenti via, minuscole, tutto ciò che non è lettera o cifra diventa un
    trattino basso: è la forma che regge come valore di un enum JSON, come
    segmento di URL e come chiave in tabella senza doversi far virgolettare da
    nessuna parte — ed è lo stesso vincolo che il CHECK della migrazione 009
    scrive nello schema.

    Pubblica e non privata perché **è una decisione che si vede**: lo slug
    nasce qui e non cambia più, quindi chi crea un tag ha diritto di sapere
    prima quale identificatore sta creando.
    """
    senza_accenti = "".join(
        carattere
        for carattere in unicodedata.normalize("NFKD", nome)
        if not unicodedata.combining(carattere)
    )
    pulito = re.sub(r"[^a-z0-9]+", "_", senza_accenti.casefold()).strip("_")
    if not pulito:
        # Un nome fatto solo di emoji o di punteggiatura non lascia niente da
        # cui ricavare un identificatore. Inventarne uno («tag_7») darebbe un
        # tag che nel database non si riconosce più: meglio dirlo subito, che è
        # anche l'unico momento in cui si può ancora cambiare nome senza costo.
        raise ValueError(f"«{nome}» non contiene nessuna lettera o cifra da cui ricavare un nome")
    return pulito[:MAX_CARATTERI_SLUG].strip("_")


def _da_riga_tag(riga: sqlite3.Row) -> Tag:
    return Tag(
        id=riga["id"],
        slug=riga["slug"],
        nome=riga["nome"],
        descrizione=riga["descrizione"],
        di_sistema=bool(riga["di_sistema"]),
        attivo=bool(riga["attivo"]),
        creato_il=datetime.fromisoformat(riga["creato_il"]),
    )


# L'ordine è quello in cui li hai aggiunti, con `altro` sempre in fondo. Non
# alfabetico, per la stessa ragione delle abitudini — una lista che si riordina
# da sola ogni volta che ne aggiungi una costringe a ricercare col dito dove
# stava quella di prima — e `altro` ultimo perché in un menu di scelte è il
# ripiego, e un ripiego in mezzo si legge come un'opzione qualunque.
_ORDINE_TAG = f"ORDER BY (slug = '{SLUG_ALTRO}') ASC, id ASC"


def elenco_tag(conn: sqlite3.Connection, *, solo_attivi: bool = False) -> list[Tag]:
    """I tag. Con `solo_attivi` quelli che il menu offre e il modello vede.

    Il default è **tutti**, archiviati compresi: chi mostra la pagina deve
    poterli disegnare tutti — un evento di marzo può portare un tag che hai
    archiviato ieri, e la sua etichetta va comunque mostrata.
    """
    dove = "WHERE attivo = 1 " if solo_attivi else ""
    return [
        _da_riga_tag(r) for r in conn.execute(f"SELECT * FROM calendar_tags {dove}{_ORDINE_TAG}")
    ]


def mappa_tag(conn: sqlite3.Connection) -> dict[str, Tag]:
    """I tag per slug, per chi deve tradurre in etichette un elenco di eventi.

    Una lettura sola invece di una JOIN per riga: la pagina Calendario traduce
    qualche centinaio di eventi contro una tabella che ne ha cinque.
    """
    return {tag.slug: tag for tag in elenco_tag(conn)}


def tag_per_slug(conn: sqlite3.Connection, slug: str) -> Tag:
    riga = conn.execute("SELECT * FROM calendar_tags WHERE slug = ?", (slug,)).fetchone()
    if riga is None:
        raise TagInesistente(slug)
    return _da_riga_tag(riga)


def _assicura_tag(conn: sqlite3.Connection, slug: str) -> None:
    if conn.execute("SELECT 1 FROM calendar_tags WHERE slug = ?", (slug,)).fetchone() is None:
        raise TagInesistente(slug)


def _nome_libero(conn: sqlite3.Connection, nome: str, *, tranne: str | None = None) -> None:
    for tag in elenco_tag(conn):
        if tag.slug != tranne and _normalizza(tag.nome) == _normalizza(nome):
            raise NomeTagGiaUsato(f"esiste già un tipo chiamato «{tag.nome}»")


def eventi_per_tag(conn: sqlite3.Connection) -> dict[str, int]:
    """Quanti eventi usa ogni tag, in tutto l'archivio.

    Tutto l'archivio e non da oggi in poi, al contrario dei contatori della
    pagina: qui il numero non è una cosa da fare, è ciò che si perderebbe
    cancellando — e un impegno di marzo si perde come uno di domani.
    """
    return {
        riga["tipo"]: riga["quanti"]
        for riga in conn.execute(
            "SELECT tipo, COUNT(*) AS quanti FROM calendar_events GROUP BY tipo"
        )
    }


def crea_tag(conn: sqlite3.Connection, *, nome: str, descrizione: str, ora: datetime) -> Tag:
    """Un tipo nuovo. Se lo slug esiste già archiviato, lo **riprende**.

    Stessa scelta di `abitudini.crea`, e qui la ragione è più forte: un secondo
    tag che significa la stessa cosa (`palestra` e `palestra_2`) spaccherebbe
    in due gli eventi già taggati, che è esattamente ciò che rende utile
    riprendere quello di prima. Riprenderlo restituisce il tag a tutti i suoi
    eventi nello stesso istante — non l'avevano mai perso.

    La descrizione è obbligatoria: è la riga che il modello legge per decidere,
    e un tag senza non è un tag più veloce da creare, è un tag che il modello
    sbaglia.
    """
    nome_pulito = _pulisci(nome)
    if not nome_pulito:
        raise ValueError("il nome di un tipo non può essere vuoto")
    descrizione_pulita = _pulisci(descrizione)
    if not descrizione_pulita:
        raise ValueError("la descrizione di un tipo non può essere vuota: la legge il modello")

    slug = slug_da(nome_pulito)
    esistente = conn.execute("SELECT * FROM calendar_tags WHERE slug = ?", (slug,)).fetchone()
    if esistente is not None:
        if esistente["attivo"]:
            raise NomeTagGiaUsato(f"esiste già un tipo chiamato «{esistente['nome']}»")
        _nome_libero(conn, nome_pulito, tranne=slug)
        conn.execute(
            "UPDATE calendar_tags SET nome = ?, descrizione = ?, attivo = 1 WHERE slug = ?",
            (nome_pulito, descrizione_pulita, slug),
        )
        return tag_per_slug(conn, slug)

    _nome_libero(conn, nome_pulito)
    conn.execute(
        "INSERT INTO calendar_tags (slug, nome, descrizione, creato_il) VALUES (?, ?, ?, ?)",
        (slug, nome_pulito, descrizione_pulita, _iso(ora)),
    )
    return tag_per_slug(conn, slug)


def modifica_tag(
    conn: sqlite3.Connection,
    slug: str,
    *,
    nome: str | None = None,
    descrizione: str | None = None,
    attivo: bool | None = None,
) -> Tag:
    """Cambia nome, descrizione o stato. Lo slug no, mai.

    **Rinominare non tocca nessun evento**: gli eventi portano lo slug, e
    l'etichetta la cercano qui. È tutta la differenza fra cambiare un nome e
    riscrivere mille righe.
    """
    tag = tag_per_slug(conn, slug)

    if nome is not None:
        nome_pulito = _pulisci(nome)
        if not nome_pulito:
            raise ValueError("il nome di un tipo non può essere vuoto")
        _nome_libero(conn, nome_pulito, tranne=slug)
        conn.execute("UPDATE calendar_tags SET nome = ? WHERE slug = ?", (nome_pulito, slug))

    if descrizione is not None:
        descrizione_pulita = _pulisci(descrizione)
        if not descrizione_pulita:
            raise ValueError("la descrizione di un tipo non può essere vuota: la legge il modello")
        conn.execute(
            "UPDATE calendar_tags SET descrizione = ? WHERE slug = ?", (descrizione_pulita, slug)
        )

    if attivo is not None:
        if not attivo and tag.di_sistema:
            raise TagDiSistema(
                f"«{tag.nome}» non si può archiviare: è il tipo con cui nasce ogni evento nuovo"
            )
        conn.execute("UPDATE calendar_tags SET attivo = ? WHERE slug = ?", (int(attivo), slug))

    return tag_per_slug(conn, slug)


def elimina_tag(conn: sqlite3.Connection, slug: str) -> None:
    """Cancella un tag, e solo se nessun evento lo usa.

    Il caso che serve è uno: l'hai appena creato e ti sei accorto che non ti
    serve. Per tutti gli altri c'è l'archiviazione — cancellare un tag usato
    vorrebbe dire riscrivere il tipo degli eventi che ce l'hanno, cioè
    riscrivere la storia di cos'era un impegno perché oggi hai cambiato idea.
    A impedirlo c'è comunque la FK della migrazione 009: questo controllo esiste
    per poter dire **quanti** sono gli eventi, che è ciò che rende il no una
    risposta utile.
    """
    tag = tag_per_slug(conn, slug)
    if tag.di_sistema:
        raise TagDiSistema(
            f"«{tag.nome}» non si può cancellare: è il tipo con cui nasce ogni evento nuovo"
        )
    quanti = eventi_per_tag(conn).get(slug, 0)
    if quanti:
        raise TagInUso(slug, quanti)
    conn.execute("DELETE FROM calendar_tags WHERE slug = ?", (slug,))


def etichette(tag: Mapping[str, Tag], slug: str) -> str:
    """L'etichetta di uno slug, con lo slug stesso come ripiego.

    Il ripiego non dovrebbe servire — la FK garantisce che ogni `tipo` abbia la
    sua riga — ma trasformare un tag mancante in un `KeyError` vorrebbe dire
    una pagina intera che non si apre per una parola che manca.
    """
    voce = tag.get(slug)
    return voce.nome if voce is not None else slug


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


def per_id(conn: sqlite3.Connection, evento_id: int) -> Evento:
    """Un evento solo. Solleva `EventoInesistente` se l'id non esiste.

    Serve a chi ha appena corretto un tag e deve restituire la riga com'è
    diventata: rileggerla è l'unico modo di dire cosa c'è scritto davvero,
    invece di ricostruirlo da quello che si è chiesto di scrivere.
    """
    riga = conn.execute("SELECT * FROM calendar_events WHERE id = ?", (evento_id,)).fetchone()
    if riga is None:
        raise EventoInesistente(evento_id)
    return _da_riga(riga)


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
                    eredita["tipo"] if eredita is not None else SLUG_ALTRO,
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
    conn: sqlite3.Connection, *, fonte: str = FONTE_GOOGLE, dal: date | None = None
) -> list[GruppoDaTaggare]:
    """Le serie e gli eventi singoli che il tagging non ha ancora guardato.

    Un gruppo per serie, non una riga per occorrenza: grazie all'eredità del
    tag in `sincronizza`, dentro una stessa serie o tutte le righe hanno
    `tag_proposto_il` valorizzato o nessuna — non serve interrogare più di una
    riga a serie per sapere se è da proporre.

    `dal` restringe a ciò che finisce da quel giorno in poi, col filtro di
    `fra` (`fine >= dal`), e serve a **contare** non a lavorare: chi propone i
    tag lo chiama senza, perché un archivio taggato per intero è ciò che il
    motore di contesto vorrà avere quando cercherà pattern nello storico; chi
    mostra un numero all'utente lo chiama con `oggi`, perché un impegno di
    marzo rimasto senza tipo non è una cosa da sbrigare — e un contatore che
    non scende mai è un contatore che si smette di guardare.
    """
    condizioni = ["fonte = ?", "tag_proposto_il IS NULL"]
    valori: list[object] = [fonte]
    if dal is not None:
        condizioni.append("fine >= ?")
        valori.append(dal.isoformat())

    righe = conn.execute(
        f"SELECT id, serie_id, titolo FROM calendar_events WHERE {' AND '.join(condizioni)}"
        " ORDER BY inizio ASC",
        valori,
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
    tipo: str,
    ora: datetime,
    *,
    confermato_da_te: bool = False,
) -> int:
    """Scrive il tag su tutte le righe del gruppo. Ritorna quante ne ha toccate.

    Una serie si scrive tutta insieme: scriverla riga per riga lascerebbe le
    occorrenze non toccate — passate o non ancora sincronizzate — senza tag, e
    la prossima sincronizzazione le riproporrebbe da capo.

    `tipo` è uno slug, e si controlla che esista prima di scriverlo: la FK lo
    impedirebbe comunque, ma con una `IntegrityError` che il worker non
    saprebbe raccontare. Il caso non è teorico — fra il momento in cui il
    prompt elenca i tag e quello in cui la risposta arriva passano dei
    secondi, e in mezzo puoi averne cancellato uno dalla pagina.
    """
    _assicura_tag(conn, tipo)
    timbro = _iso(ora)
    if gruppo.serie_id:
        cursore = conn.execute(
            "UPDATE calendar_events"
            " SET tipo = ?, tag_proposto_il = ?, tag_confermato_da_te = ?"
            " WHERE fonte = ? AND serie_id = ?",
            (tipo, timbro, int(confermato_da_te), gruppo.fonte, gruppo.serie_id),
        )
    else:
        assert gruppo.evento_id is not None  # un gruppo o ha una serie, o un id
        cursore = conn.execute(
            "UPDATE calendar_events SET tipo = ?, tag_proposto_il = ?, tag_confermato_da_te = ?"
            " WHERE id = ?",
            (tipo, timbro, int(confermato_da_te), gruppo.evento_id),
        )
    return cursore.rowcount


def correggi_tag(conn: sqlite3.Connection, evento_id: int, tipo: str, ora: datetime) -> int:
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


@dataclass(frozen=True)
class SerieDaRivedere:
    """Una serie taggata dall'IA che tu non hai mai confermato né corretto.

    È la risposta a «cosa ha capito» di §8.10: ciò che il modello ha deciso da
    solo e che nessuno ha ancora guardato. Un gruppo per serie, come per la
    proposta — correggere un'occorrenza corregge tutta la serie, quindi
    mostrarne dodici sarebbe mostrare dodici volte la stessa correzione.
    """

    evento_id: int
    """La prossima occorrenza: è la riga su cui chiamare `correggi_tag`."""
    serie_id: str
    """Vuoto per un evento singolo."""
    titolo: str
    tipo: str
    prossima: datetime
    """Quando torna la prima volta da oggi in poi."""
    occorrenze: int
    """Quante ne restano da oggi in poi, questa compresa."""
    proposto_il: datetime


def da_rivedere(
    conn: sqlite3.Connection, oggi: date, *, fonte: str = FONTE_GOOGLE
) -> list[SerieDaRivedere]:
    """Le serie proposte dall'IA e mai confermate, dalla prossima in poi.

    **Solo ciò che deve ancora succedere.** Un tag sbagliato su una lezione di
    marzo non produce più niente di sbagliato: le regole di contesto scattano
    su quello che viene, e una coda che cresce per sempre smette di essere una
    cosa da sbrigare. Il filtro è `fine >= oggi`, lo stesso di `fra`: un evento
    cominciato ieri e ancora in corso è di oggi.
    """
    righe = conn.execute(
        "SELECT id, serie_id, titolo, tipo, inizio, tag_proposto_il"
        " FROM calendar_events"
        " WHERE fonte = ? AND tag_proposto_il IS NOT NULL AND tag_confermato_da_te = 0"
        "   AND fine >= ?"
        " ORDER BY inizio ASC",
        (fonte, oggi.isoformat()),
    )

    per_serie: dict[str, list[sqlite3.Row]] = {}
    for riga in righe:
        chiave = riga["serie_id"] or f"#{riga['id']}"
        per_serie.setdefault(chiave, []).append(riga)

    # Le righe arrivano già in ordine di inizio, quindi la prima di ogni gruppo
    # è la prossima occorrenza — e l'ordine dei gruppi è quello delle prime.
    return [
        SerieDaRivedere(
            evento_id=gruppo[0]["id"],
            serie_id=gruppo[0]["serie_id"],
            titolo=gruppo[0]["titolo"],
            tipo=gruppo[0]["tipo"],
            prossima=datetime.fromisoformat(gruppo[0]["inizio"]),
            occorrenze=len(gruppo),
            proposto_il=datetime.fromisoformat(gruppo[0]["tag_proposto_il"]),
        )
        for gruppo in per_serie.values()
    ]
