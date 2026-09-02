"""Spese e categorie (ARCHITECTURE.md §8.5).

Due canali che finiscono nello stesso posto: una frase («ho pagato 8€ la
colazione da Bar Rossi») diventa subito una spesa con un bottone «Annulla»,
mentre una foto di scontrino diventa una spesa `da_confermare` — §8.5 vuole
che la sintesi letta da un'immagine passi da un tuo sì prima di entrare nei
conti, perché lì il modello estrae dieci numeri e sbagliarne uno è facile.

**Gli importi sono in centesimi.** Dentro questo modulo si parla di `int`, e
gli euro esistono solo al confine con l'API e col bot. Sommare float per
centinaia di spese produce totali che non tornano per qualche centesimo, e su
dei soldi un totale che non torna è un bug che si nota subito.

Nessun modello qui dentro: la categorizzazione e la lettura degli scontrini
stanno in `custode_router.spese`, e questo modulo riceve i risultati.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum


class SpesaInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessuna spesa."""


class Stato(StrEnum):
    CONFERMATA = "confermata"
    DA_CONFERMARE = "da_confermare"
    """Solo per gli scontrini: la sintesi aspetta il tuo sì (§8.5)."""


class Fonte(StrEnum):
    TESTO = "testo"
    SCONTRINO = "scontrino"


@dataclass(frozen=True)
class Categoria:
    id: int
    nome: str
    creata_da: str
    attiva: bool


@dataclass(frozen=True)
class Spesa:
    id: int
    centesimi: int
    descrizione: str
    categoria: str | None
    luogo: str | None
    giorno: date
    fonte: Fonte
    stato: Stato
    scontrino_raw: str | None
    creata_il: datetime

    @property
    def euro(self) -> float:
        """L'importo come lo mostra il contratto. Solo per uscire da qui."""
        return self.centesimi / 100


def in_centesimi(euro: float) -> int:
    """Euro → centesimi, arrotondando all'unità più vicina.

    `round` e non `int`: `int(8.15 * 100)` fa 814 su un binario che non sa
    rappresentare 8.15 esattamente, e una spesa su venti finirebbe con un
    centesimo in meno senza che nessuno capisca perché.
    """
    return round(euro * 100)


def _normalizza(nome: str) -> str:
    """Forma di confronto di un nome di categoria.

    Serve a non creare «Alimentari» accanto a «alimentari  » per una maiuscola
    o uno spazio. I doppioni *semantici* («Cibo» vs «Alimentari») non li può
    prendere una funzione: li evita il modello, che riceve le categorie già in
    uso prima di proporne una nuova (§8.5).
    """
    pulito = unicodedata.normalize("NFKC", nome).strip()
    return " ".join(pulito.split()).casefold()


# — categorie —


def _categoria_da_riga(riga: sqlite3.Row) -> Categoria:
    return Categoria(
        id=riga["id"],
        nome=riga["nome"],
        creata_da=riga["creata_da"],
        attiva=bool(riga["attiva"]),
    )


def categorie(conn: sqlite3.Connection, *, solo_attive: bool = False) -> list[Categoria]:
    dove = "WHERE attiva = 1" if solo_attive else ""
    righe = conn.execute(f"SELECT * FROM expense_categories {dove} ORDER BY nome ASC")
    return [_categoria_da_riga(r) for r in righe]


def trova_categoria(conn: sqlite3.Connection, nome: str) -> Categoria | None:
    obiettivo = _normalizza(nome)
    for categoria in categorie(conn):
        if _normalizza(categoria.nome) == obiettivo:
            return categoria
    return None


def assicura_categoria(
    conn: sqlite3.Connection, nome: str, ora: datetime, *, da_utente: bool = False
) -> Categoria:
    """La categoria con quel nome, creandola se non c'è ancora.

    Non esiste un elenco predefinito: la prima spesa fa nascere la prima
    categoria, e le tue finiscono per somigliare a come spendi tu invece che a
    un elenco deciso a tavolino (§8.5).
    """
    pulito = " ".join(nome.strip().split())
    if not pulito:
        raise ValueError("il nome della categoria non può essere vuoto")

    esistente = trova_categoria(conn, pulito)
    if esistente is not None:
        return esistente

    conn.execute(
        "INSERT INTO expense_categories (nome, creata_da, creata_il) VALUES (?, ?, ?)",
        (pulito, "utente" if da_utente else "ia", ora.isoformat(timespec="seconds")),
    )
    creata = trova_categoria(conn, pulito)
    assert creata is not None  # appena scritta
    return creata


def rinomina_categoria(conn: sqlite3.Connection, categoria_id: int, nome: str) -> Categoria:
    pulito = " ".join(nome.strip().split())
    if not pulito:
        raise ValueError("il nome della categoria non può essere vuoto")
    conn.execute("UPDATE expense_categories SET nome = ? WHERE id = ?", (pulito, categoria_id))
    riga = conn.execute("SELECT * FROM expense_categories WHERE id = ?", (categoria_id,)).fetchone()
    if riga is None:
        raise LookupError(categoria_id)
    return _categoria_da_riga(riga)


def unisci_categorie(conn: sqlite3.Connection, da_id: int, a_id: int) -> None:
    """Sposta le spese di una categoria su un'altra e disattiva la prima.

    Serve a rimediare ai doppioni semantici che il modello non ha evitato:
    §8.5 vuole che le categorie restino unibili a mano. Si disattiva invece di
    cancellare, così resta traccia di com'era chiamata prima.
    """
    if da_id == a_id:
        return
    conn.execute("UPDATE expenses SET categoria_id = ? WHERE categoria_id = ?", (a_id, da_id))
    conn.execute("UPDATE expense_categories SET attiva = 0 WHERE id = ?", (da_id,))


# — spese —


def _da_riga(riga: sqlite3.Row) -> Spesa:
    return Spesa(
        id=riga["id"],
        centesimi=riga["importo"],
        descrizione=riga["descrizione"],
        categoria=riga["categoria"],
        luogo=riga["luogo"],
        giorno=date.fromisoformat(riga["data"]),
        fonte=Fonte(riga["fonte"]),
        stato=Stato(riga["stato"]),
        scontrino_raw=riga["scontrino_raw_estratto"],
        creata_il=datetime.fromisoformat(riga["creata_il"]),
    )


# Il nome della categoria arriva già unito: chi legge una spesa vuole sapere
# «Alimentari», non un id da risolvere con una seconda query.
_SELECT = (
    "SELECT e.*, c.nome AS categoria FROM expenses e"
    " LEFT JOIN expense_categories c ON c.id = e.categoria_id"
)


def leggi(conn: sqlite3.Connection, spesa_id: int) -> Spesa:
    riga = conn.execute(f"{_SELECT} WHERE e.id = ?", (spesa_id,)).fetchone()
    if riga is None:
        raise SpesaInesistente(spesa_id)
    return _da_riga(riga)


def elenco(
    conn: sqlite3.Connection,
    *,
    da: date | None = None,
    a: date | None = None,
    stato: Stato | None = Stato.CONFERMATA,
) -> list[Spesa]:
    """Le spese nell'intervallo, dalla più recente.

    Di default solo quelle confermate: una spesa che aspetta il tuo sì non è
    ancora un movimento, e non deve comparire nei totali.
    """
    condizioni: list[str] = []
    parametri: list[str] = []
    if stato is not None:
        condizioni.append("e.stato = ?")
        parametri.append(stato.value)
    if da is not None:
        condizioni.append("e.data >= ?")
        parametri.append(da.isoformat())
    if a is not None:
        condizioni.append("e.data <= ?")
        parametri.append(a.isoformat())
    dove = f"WHERE {' AND '.join(condizioni)}" if condizioni else ""
    righe = conn.execute(f"{_SELECT} {dove} ORDER BY e.data DESC, e.id DESC", parametri)
    return [_da_riga(r) for r in righe]


def in_attesa(conn: sqlite3.Connection) -> list[Spesa]:
    """Gli scontrini letti che aspettano una conferma (§8.5)."""
    righe = conn.execute(f"{_SELECT} WHERE e.stato = 'da_confermare' ORDER BY e.creata_il DESC")
    return [_da_riga(r) for r in righe]


def registra(
    conn: sqlite3.Connection,
    *,
    centesimi: int,
    descrizione: str,
    ora: datetime,
    giorno: date | None = None,
    categoria: str | None = None,
    luogo: str | None = None,
    fonte: Fonte = Fonte.TESTO,
    stato: Stato = Stato.CONFERMATA,
    scontrino_raw: str | None = None,
    categoria_da_utente: bool = False,
) -> Spesa:
    """Scrive una spesa. Gli importi entrano qui già in centesimi.

    `categoria_da_utente` dice **chi** ha scelto il nome della categoria, non
    se è nuova: una categoria che hai scritto tu e una che ha proposto il
    modello si correggono con criteri diversi, e il default è il modello
    perché è da lì che arriva quasi sempre.
    """
    if centesimi <= 0:
        raise ValueError("l'importo di una spesa dev'essere positivo")
    testo = descrizione.strip()
    if not testo:
        raise ValueError("la descrizione di una spesa non può essere vuota")

    categoria_id = (
        assicura_categoria(conn, categoria, ora, da_utente=categoria_da_utente).id
        if categoria and categoria.strip()
        else None
    )
    cursore = conn.execute(
        "INSERT INTO expenses"
        " (importo, descrizione, categoria_id, luogo, data, fonte, stato,"
        "  scontrino_raw_estratto, creata_il)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            centesimi,
            testo,
            categoria_id,
            (luogo or "").strip() or None,
            (giorno or ora.date()).isoformat(),
            fonte.value,
            stato.value,
            scontrino_raw,
            ora.isoformat(timespec="seconds"),
        ),
    )
    return leggi(conn, int(cursore.lastrowid or 0))


def conferma(
    conn: sqlite3.Connection, spesa_id: int, ora: datetime, *, categoria: str | None = None
) -> Spesa:
    """Fa entrare nei conti uno scontrino letto, eventualmente correggendone la categoria."""
    spesa = leggi(conn, spesa_id)
    if spesa.stato is not Stato.DA_CONFERMARE:
        raise ValueError("questa spesa è già confermata")

    if categoria and categoria.strip():
        nuova = assicura_categoria(conn, categoria, ora, da_utente=True)
        conn.execute("UPDATE expenses SET categoria_id = ? WHERE id = ?", (nuova.id, spesa_id))
    conn.execute("UPDATE expenses SET stato = 'confermata' WHERE id = ?", (spesa_id,))
    return leggi(conn, spesa_id)


def elimina(conn: sqlite3.Connection, spesa_id: int) -> None:
    """Cancella una spesa: serve ad «Annulla» e a scartare uno scontrino."""
    leggi(conn, spesa_id)
    conn.execute("DELETE FROM expenses WHERE id = ?", (spesa_id,))


# — totali, tutti in codice: nessuno di questi passa da un modello —


def totale(spese: list[Spesa]) -> int:
    return sum(s.centesimi for s in spese)


def per_categoria(spese: list[Spesa]) -> list[tuple[str, int]]:
    """Centesimi per categoria, dalla più alta. Senza categoria → «Senza categoria»."""
    somme: dict[str, int] = defaultdict(int)
    for spesa in spese:
        somme[spesa.categoria or "Senza categoria"] += spesa.centesimi
    return sorted(somme.items(), key=lambda c: (-c[1], c[0]))


def per_giorno(spese: list[Spesa], *, da: date, giorni: int) -> list[int]:
    """Centesimi spesi in ciascun giorno a partire da `da`."""
    somme: dict[date, int] = defaultdict(int)
    for spesa in spese:
        somme[spesa.giorno] += spesa.centesimi
    return [somme.get(da + timedelta(days=i), 0) for i in range(giorni)]


def luoghi_frequenti(spese: list[Spesa], quanti: int = 5) -> list[tuple[str, int]]:
    """I posti dove spendi più spesso, col numero di volte."""
    conteggi: dict[str, int] = defaultdict(int)
    for spesa in spese:
        if spesa.luogo:
            conteggi[spesa.luogo] += 1
    return sorted(conteggi.items(), key=lambda c: (-c[1], c[0]))[:quanti]


def giorni_dall_ultima(spese: list[Spesa], oggi: date) -> int | None:
    """Da quanti giorni non registri una spesa. None se non ce n'è nessuna."""
    passate = [s.giorno for s in spese if s.giorno <= oggi]
    return (oggi - max(passate)).days if passate else None
