"""Profilo cumulativo e candidati (ARCHITECTURE.md §8.4).

Due cose che vivono insieme:

- **I candidati**: segnali utili pescati dai messaggi di tutti i giorni («a me
  piace il backend», «di mattina non combino niente»). Si accumulano in
  silenzio, si chiariscono con una domanda quando sono ambigui, e una volta a
  settimana li rivedi prima che entrino nel profilo.
- **Il profilo**: un unico documento, riscritto per intero ad ogni rifusione e
  **versionato**. Non si accoda mai: §8.4 spiega perché — un log infinito
  diventa costoso da passare ai modelli e via via più rumore che segnale.

Come per il diario, qui non c'è nessun modello: la rifusione la scrive Claude
in `custode_router.profilo`, questo modulo la riceve e la custodisce.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CandidatoInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessun candidato."""


class Stato(StrEnum):
    IN_CODA = "in_coda"
    """Segnale chiaro, raccolto in silenzio: aspetta la revisione settimanale."""

    CHIARITO = "chiarito"
    """Era ambiguo e hai risposto alla domanda del bot: vale come segnale vero."""

    APPROVATO = "approvato"
    """L'hai lasciato passare alla revisione settimanale."""

    SCARTATO = "scartato"
    """Non ti rappresenta: non entrerà mai nel profilo."""


# Gli stati che una revisione settimanale deve mostrarti.
DA_RIVEDERE = (Stato.IN_CODA, Stato.CHIARITO)


@dataclass(frozen=True)
class Candidato:
    id: int
    messaggio_origine: str
    estratto: str
    stato: Stato
    chiarimento_domanda: str | None
    chiarimento_risposta: str | None
    versione_profilo: int | None
    creato_il: datetime

    @property
    def rifuso(self) -> bool:
        return self.versione_profilo is not None


@dataclass(frozen=True)
class Versione:
    versione: int
    testo: str
    aggiornato_il: datetime


def _da_riga(riga: sqlite3.Row) -> Candidato:
    return Candidato(
        id=riga["id"],
        messaggio_origine=riga["messaggio_origine"],
        estratto=riga["estratto"],
        stato=Stato(riga["stato"]),
        chiarimento_domanda=riga["chiarimento_domanda"],
        chiarimento_risposta=riga["chiarimento_risposta"],
        versione_profilo=riga["versione_profilo"],
        creato_il=datetime.fromisoformat(riga["creato_il"]),
    )


# — candidati —


def leggi_candidato(conn: sqlite3.Connection, candidato_id: int) -> Candidato:
    riga = conn.execute("SELECT * FROM profile_candidates WHERE id = ?", (candidato_id,)).fetchone()
    if riga is None:
        raise CandidatoInesistente(candidato_id)
    return _da_riga(riga)


def aggiungi_candidato(
    conn: sqlite3.Connection,
    *,
    messaggio_origine: str,
    estratto: str,
    ora: datetime,
    domanda: str | None = None,
) -> Candidato:
    """Registra un segnale pescato da un messaggio.

    Con `domanda` il candidato nasce già in attesa di un chiarimento: è il caso
    ambiguo di §8.4, dove il bot chiede lì per lì invece di tirare a indovinare.
    Senza, è un segnale chiaro e finisce in coda in silenzio — nessuna
    interruzione della conversazione.
    """
    testo = estratto.strip()
    if not testo:
        raise ValueError("l'estratto del candidato non può essere vuoto")

    cursore = conn.execute(
        "INSERT INTO profile_candidates"
        " (messaggio_origine, estratto, stato, chiarimento_domanda, creato_il)"
        " VALUES (?, ?, 'in_coda', ?, ?)",
        (
            messaggio_origine.strip(),
            testo,
            domanda.strip() if domanda and domanda.strip() else None,
            ora.isoformat(timespec="seconds"),
        ),
    )
    return leggi_candidato(conn, int(cursore.lastrowid or 0))


def in_chiarimento(conn: sqlite3.Connection) -> Candidato | None:
    """Il candidato per cui il bot ha fatto una domanda e aspetta risposta."""
    riga = conn.execute(
        "SELECT * FROM profile_candidates"
        " WHERE stato = 'in_coda' AND chiarimento_domanda IS NOT NULL"
        " AND chiarimento_risposta IS NULL"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _da_riga(riga) if riga else None


def chiarisci(
    conn: sqlite3.Connection, candidato_id: int, *, risposta: str, vale: bool
) -> Candidato:
    """Registra la risposta alla domanda di chiarimento.

    `vale=False` non lascia il candidato a metà: lo scarta. Un «era solo la
    giornata storta» è un no, e tenerlo in coda vorrebbe dire richiedertelo alla
    revisione settimanale — cioè fare due volte la stessa domanda.
    """
    leggi_candidato(conn, candidato_id)
    conn.execute(
        "UPDATE profile_candidates SET chiarimento_risposta = ?, stato = ? WHERE id = ?",
        (risposta.strip(), Stato.CHIARITO if vale else Stato.SCARTATO, candidato_id),
    )
    return leggi_candidato(conn, candidato_id)


def da_rivedere(conn: sqlite3.Connection) -> list[Candidato]:
    """I candidati che aspettano la revisione settimanale, dal più vecchio.

    Non c'è un limite di periodo: un candidato raccolto e mai rivisto (perché
    quella settimana il job non è girato, o non hai risposto) resta lì. Sono
    cose da guardare, non un registro che scade.
    """
    righe = conn.execute(
        "SELECT * FROM profile_candidates"
        " WHERE stato IN ('in_coda', 'chiarito') AND versione_profilo IS NULL"
        " ORDER BY id ASC"
    )
    return [_da_riga(r) for r in righe]


def approvati(conn: sqlite3.Connection) -> list[Candidato]:
    """I candidati passati dalla revisione e non ancora rifusi nel profilo."""
    righe = conn.execute(
        "SELECT * FROM profile_candidates"
        " WHERE stato = 'approvato' AND versione_profilo IS NULL"
        " ORDER BY id ASC"
    )
    return [_da_riga(r) for r in righe]


def scarta_candidato(conn: sqlite3.Connection, candidato_id: int) -> Candidato:
    leggi_candidato(conn, candidato_id)
    conn.execute("UPDATE profile_candidates SET stato = 'scartato' WHERE id = ?", (candidato_id,))
    return leggi_candidato(conn, candidato_id)


def approva_rimanenti(conn: sqlite3.Connection) -> list[Candidato]:
    """Chiude la revisione: quel che non hai scartato è approvato.

    La revisione di §8.4 funziona per sottrazione — si scartano quelli
    sbagliati, non si conferma uno per uno — perché §8.4 stessa dice che la
    disambiguazione grossa è già stata fatta al momento della domanda.
    """
    conn.execute(
        "UPDATE profile_candidates SET stato = 'approvato'"
        " WHERE stato IN ('in_coda', 'chiarito') AND versione_profilo IS NULL"
    )
    return approvati(conn)


# — profilo —


def _versione(riga: sqlite3.Row) -> Versione:
    return Versione(
        versione=riga["versione"],
        testo=riga["testo"],
        aggiornato_il=datetime.fromisoformat(riga["aggiornato_il"]),
    )


def corrente(conn: sqlite3.Connection) -> Versione | None:
    """L'ultima versione del profilo, o None se non ne esiste ancora nessuna."""
    riga = conn.execute("SELECT * FROM profile_document ORDER BY versione DESC LIMIT 1").fetchone()
    return _versione(riga) if riga else None


def versioni(conn: sqlite3.Connection) -> list[Versione]:
    """Tutte le versioni, dalla più recente."""
    righe = conn.execute("SELECT * FROM profile_document ORDER BY versione DESC")
    return [_versione(r) for r in righe]


def salva_versione(
    conn: sqlite3.Connection, *, testo: str, ora: datetime, candidati: list[Candidato]
) -> Versione:
    """Scrive una nuova versione del profilo e ci lega i candidati rifusi.

    I candidati restano registrati con il numero di versione che li ha
    assorbiti: è ciò che impedisce di riproporli al modello ogni settimana, e
    ciò che permette, guardando una riga del profilo, di risalire a cosa
    l'aveva originata.
    """
    pulito = testo.strip()
    if not pulito:
        raise ValueError("il profilo non può essere vuoto")

    attuale = corrente(conn)
    numero = (attuale.versione + 1) if attuale else 1
    conn.execute(
        "INSERT INTO profile_document (versione, testo, aggiornato_il) VALUES (?, ?, ?)",
        (numero, pulito, ora.isoformat(timespec="seconds")),
    )
    for candidato in candidati:
        conn.execute(
            "UPDATE profile_candidates SET versione_profilo = ? WHERE id = ?",
            (numero, candidato.id),
        )

    nuova = corrente(conn)
    assert nuova is not None  # appena scritta
    return nuova


def torna_indietro(conn: sqlite3.Connection) -> Versione | None:
    """Disfa l'ultima rifusione. Ritorna la versione tornata attiva.

    È un annullamento, non una revisione: la versione sbagliata sparisce e i
    candidati che ci erano finiti dentro tornano approvati e non rifusi, così
    rientrano nella prossima rifusione invece di perdersi. Senza quel secondo
    passaggio, tornare indietro butterebbe via anche il materiale.
    """
    attuale = corrente(conn)
    if attuale is None:
        return None

    conn.execute(
        "UPDATE profile_candidates SET versione_profilo = NULL, stato = 'approvato'"
        " WHERE versione_profilo = ?",
        (attuale.versione,),
    )
    conn.execute("DELETE FROM profile_document WHERE versione = ?", (attuale.versione,))
    return corrente(conn)


def testo_corrente(conn: sqlite3.Connection) -> str | None:
    """Il profilo da infilare nei prompt, o None se non esiste ancora.

    None e non stringa vuota: chi lo usa deve poter omettere del tutto la parte
    di prompt che lo riguarda, invece di dire al modello «ecco il profilo:» e
    non dargli niente.
    """
    attuale = corrente(conn)
    return attuale.testo if attuale else None
