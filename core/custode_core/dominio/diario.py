"""Diario (ARCHITECTURE.md §8.4).

Una voce per **giorno**, fatta di frammenti: ogni messaggio o vocale che
racconta qualcosa della giornata si accoda come frammento; quando la giornata
viene chiusa, Claude propone un riassunto dell'insieme; solo la versione che
approvi finisce in `riassunto_approvato`, ed è l'unica che il resto del sistema
considera diario — dashboard, statistiche e job settimanale leggono quella, mai
la bozza.

Qui dentro non c'è nessun modello: la generazione del riassunto sta in
`custode_router.diario`, e questo modulo si limita a riceverlo e a custodirlo.
È la stessa separazione del resto del dominio, e permette di esercitare tutto il
ciclo di approvazione senza chiamare nessuno.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum


class VoceInesistente(LookupError):
    """Sollevata quando l'id richiesto non corrisponde a nessuna voce."""


class FrammentoInesistente(LookupError):
    """Sollevata quando il frammento da togliere non c'è (già annullato)."""


class Stato(StrEnum):
    IN_RACCOLTA = "in_raccolta"
    """La giornata sta accumulando materiale: nessuna bozza ancora chiesta."""

    DA_APPROVARE = "da_approvare"
    """C'è una bozza che aspetta un sì, una riscrittura o uno scarto."""

    IN_MODIFICA = "in_modifica"
    """Hai chiesto di riscriverla: il prossimo messaggio è il testo corretto.

    Lo stato sta sul database e non nella memoria del processo apposta: se il
    bot riparte nel mezzo, la conversazione riprende da dov'era invece di
    scambiare la riscrittura per una frase qualsiasi.
    """

    APPROVATA = "approvata"


@dataclass(frozen=True)
class RiepilogoSettimana:
    """Il riepilogo di §8.4 punto 7, scritto da Claude sulle voci approvate."""

    settimana_inizio: date
    testo: str
    generato_il: datetime


@dataclass(frozen=True)
class Frammento:
    id: int
    testo: str
    da_vocale: bool
    creato_il: datetime


@dataclass(frozen=True)
class Voce:
    id: int
    giorno: date
    riassunto_proposto: str | None
    riassunto_approvato: str | None
    tag: list[str]
    stato: Stato
    creata_il: datetime
    approvata_il: datetime | None
    frammenti: list[Frammento] = field(default_factory=list)

    @property
    def grezzo(self) -> str:
        """Il materiale della giornata come lo legge il modello."""
        return "\n".join(f.testo for f in self.frammenti)

    @property
    def ha_materiale(self) -> bool:
        return bool(self.grezzo.strip())

    @property
    def n_vocali(self) -> int:
        return sum(1 for f in self.frammenti if f.da_vocale)

    @property
    def n_messaggi(self) -> int:
        return sum(1 for f in self.frammenti if not f.da_vocale)

    @property
    def parole(self) -> int:
        return len((self.riassunto_approvato or "").split())


def _leggi_tag(testo: str | None) -> list[str]:
    """I tag arrivano da un modello: un JSON storto non deve rompere la lettura."""
    if not testo:
        return []
    try:
        valore = json.loads(testo)
    except json.JSONDecodeError:
        return []
    if not isinstance(valore, list):
        return []
    return [str(t).strip() for t in valore if str(t).strip()]


def _scrivi_tag(tag: list[str]) -> str:
    # Deduplicati conservando l'ordine: un modello a volte ripete lo stesso tema
    # con due parole vicine, e nella dashboard si vedrebbero etichette gemelle.
    visti: dict[str, None] = {}
    for voce in tag:
        pulito = voce.strip().lower()
        if pulito:
            visti.setdefault(pulito, None)
    return json.dumps(list(visti), ensure_ascii=False)


def _frammento(riga: sqlite3.Row) -> Frammento:
    return Frammento(
        id=riga["id"],
        testo=riga["testo"],
        da_vocale=bool(riga["da_vocale"]),
        creato_il=datetime.fromisoformat(riga["creato_il"]),
    )


def _da_riga(riga: sqlite3.Row, frammenti: list[Frammento]) -> Voce:
    return Voce(
        id=riga["id"],
        giorno=date.fromisoformat(riga["data"]),
        riassunto_proposto=riga["riassunto_proposto"],
        riassunto_approvato=riga["riassunto_approvato"],
        tag=_leggi_tag(riga["tag"]),
        stato=Stato(riga["stato_approvazione"]),
        creata_il=datetime.fromisoformat(riga["creata_il"]),
        approvata_il=(
            datetime.fromisoformat(riga["approvata_il"]) if riga["approvata_il"] else None
        ),
        frammenti=frammenti,
    )


def _frammenti_di(conn: sqlite3.Connection, id_voci: list[int]) -> dict[int, list[Frammento]]:
    """I frammenti di più voci in una query sola, invece di una per voce."""
    if not id_voci:
        return {}
    segnaposti = ",".join("?" * len(id_voci))
    righe = conn.execute(
        f"SELECT * FROM diary_fragments WHERE entry_id IN ({segnaposti}) ORDER BY id ASC",
        id_voci,
    )
    raccolti: dict[int, list[Frammento]] = {id_voce: [] for id_voce in id_voci}
    for riga in righe:
        raccolti[riga["entry_id"]].append(_frammento(riga))
    return raccolti


def _componi(conn: sqlite3.Connection, righe: list[sqlite3.Row]) -> list[Voce]:
    frammenti = _frammenti_di(conn, [r["id"] for r in righe])
    return [_da_riga(r, frammenti.get(r["id"], [])) for r in righe]


def leggi(conn: sqlite3.Connection, voce_id: int) -> Voce:
    riga = conn.execute("SELECT * FROM diary_entries WHERE id = ?", (voce_id,)).fetchone()
    if riga is None:
        raise VoceInesistente(voce_id)
    return _componi(conn, [riga])[0]


def leggi_giorno(conn: sqlite3.Connection, giorno: date) -> Voce | None:
    riga = conn.execute(
        "SELECT * FROM diary_entries WHERE data = ?", (giorno.isoformat(),)
    ).fetchone()
    return _componi(conn, [riga])[0] if riga else None


def elenco(
    conn: sqlite3.Connection, *, da: date | None = None, a: date | None = None
) -> list[Voce]:
    """Le voci nell'intervallo (estremi inclusi), dalla più recente."""
    condizioni: list[str] = []
    parametri: list[str] = []
    if da is not None:
        condizioni.append("data >= ?")
        parametri.append(da.isoformat())
    if a is not None:
        condizioni.append("data <= ?")
        parametri.append(a.isoformat())
    dove = f"WHERE {' AND '.join(condizioni)}" if condizioni else ""
    righe = list(conn.execute(f"SELECT * FROM diary_entries {dove} ORDER BY data DESC", parametri))
    return _componi(conn, righe)


def in_attesa(conn: sqlite3.Connection) -> list[Voce]:
    """Tutte le bozze che aspettano una risposta, di qualunque data.

    Senza limiti di periodo apposta: una bozza è una cosa da sbrigare, e una
    lasciata in sospeso a fine mese non deve sparire dalla vista solo perché
    nel frattempo il mese è cambiato.
    """
    righe = list(
        conn.execute(
            "SELECT * FROM diary_entries WHERE stato_approvazione IN"
            " ('da_approvare', 'in_modifica') ORDER BY data DESC"
        )
    )
    return _componi(conn, righe)


def approvate(conn: sqlite3.Connection, *, da: date, a: date) -> list[Voce]:
    """Le voci approvate dell'intervallo, dalla più vecchia.

    È ciò che leggerà il job settimanale di §8.4: solo l'approvato, in ordine
    cronologico, perché il riepilogo racconta una settimana dal lunedì in poi.
    """
    righe = list(
        conn.execute(
            "SELECT * FROM diary_entries"
            " WHERE stato_approvazione = 'approvata' AND data BETWEEN ? AND ?"
            " ORDER BY data ASC",
            (da.isoformat(), a.isoformat()),
        )
    )
    return _componi(conn, righe)


def aggiungi_materiale(
    conn: sqlite3.Connection,
    *,
    giorno: date,
    testo: str,
    ora: datetime,
    da_vocale: bool = False,
) -> tuple[Voce, int]:
    """Accoda una frase (scritta o dettata) al diario del giorno.

    Ritorna la voce aggiornata e l'id del frammento appena scritto: è quello che
    serve al bottone «Annulla» per togliere esattamente questa frase e non
    un'altra (§8.1).

    Se la giornata era già approvata torna `in_raccolta`, ma l'approvazione
    precedente resta leggibile finché non ne approvi una nuova: aggiungere
    qualcosa a tarda sera non deve cancellare ciò che avevi già confermato.
    """
    pulito = testo.strip()
    if not pulito:
        raise ValueError("il materiale del diario non può essere vuoto")

    voce = leggi_giorno(conn, giorno)
    if voce is None:
        cursore = conn.execute(
            "INSERT INTO diary_entries (data, creata_il) VALUES (?, ?)",
            (giorno.isoformat(), ora.isoformat(timespec="seconds")),
        )
        voce_id = int(cursore.lastrowid or 0)
    else:
        voce_id = voce.id
        conn.execute(
            # Una bozza calcolata prima di questa frase non la comprende più.
            "UPDATE diary_entries SET riassunto_proposto = NULL,"
            " stato_approvazione = 'in_raccolta' WHERE id = ?",
            (voce_id,),
        )

    cursore = conn.execute(
        "INSERT INTO diary_fragments (entry_id, testo, da_vocale, creato_il)"
        " VALUES (?, ?, ?, ?)",
        (voce_id, pulito, 1 if da_vocale else 0, ora.isoformat(timespec="seconds")),
    )
    return leggi(conn, voce_id), int(cursore.lastrowid or 0)


def togli_frammento(conn: sqlite3.Connection, frammento_id: int) -> str:
    """Disfà un'aggiunta al diario. Ritorna il testo tolto.

    Se era l'ultimo frammento e la giornata non era ancora approvata, la voce
    sparisce: una giornata senza materiale e senza diario non è una giornata
    vuota da mostrare, è una giornata di cui non hai scritto niente.
    """
    riga = conn.execute("SELECT * FROM diary_fragments WHERE id = ?", (frammento_id,)).fetchone()
    if riga is None:
        raise FrammentoInesistente(frammento_id)

    voce_id = riga["entry_id"]
    conn.execute("DELETE FROM diary_fragments WHERE id = ?", (frammento_id,))

    voce = leggi(conn, voce_id)
    if not voce.frammenti and voce.riassunto_approvato is None:
        conn.execute("DELETE FROM diary_entries WHERE id = ?", (voce_id,))
    else:
        conn.execute(
            "UPDATE diary_entries SET riassunto_proposto = NULL, stato_approvazione = ?"
            " WHERE id = ?",
            (_stato_dopo_rimozione(voce), voce_id),
        )
    return str(riga["testo"])


def _stato_dopo_rimozione(voce: Voce) -> Stato:
    """Dove torna una giornata dopo che le si è tolto un frammento.

    Se ciò che resta è tutto materiale che l'approvazione aveva già visto, la
    giornata è di nuovo semplicemente approvata: annullare l'aggiunta delle
    22:30 deve riportare le cose com'erano alle 22:29, non lasciare in sospeso
    una giornata che avevi già chiuso. Se invece resta materiale successivo
    all'approvazione, c'è ancora qualcosa da incorporare.
    """
    if voce.riassunto_approvato is None or voce.approvata_il is None:
        return Stato.IN_RACCOLTA
    posteriori = [f for f in voce.frammenti if f.creato_il > voce.approvata_il]
    return Stato.IN_RACCOLTA if posteriori else Stato.APPROVATA


def proponi(conn: sqlite3.Connection, voce_id: int, *, riassunto: str, tag: list[str]) -> Voce:
    """Registra la bozza di Claude e la mette in attesa di approvazione."""
    testo = riassunto.strip()
    if not testo:
        raise ValueError("il riassunto proposto non può essere vuoto")
    leggi(conn, voce_id)  # solleva VoceInesistente prima di scrivere
    conn.execute(
        "UPDATE diary_entries SET riassunto_proposto = ?, tag = ?,"
        " stato_approvazione = 'da_approvare' WHERE id = ?",
        (testo, _scrivi_tag(tag), voce_id),
    )
    return leggi(conn, voce_id)


def chiedi_modifica(conn: sqlite3.Connection, voce_id: int) -> Voce:
    """Mette la voce in attesa del testo riscritto da te.

    Una riscrittura per volta: il prossimo messaggio può diventare una sola
    voce, quindi chiedere di riscriverne un'altra riporta la precedente alla
    sua bozza. Senza questo, premendo «Modifica» su due giornate diverse (i
    bottoni restano attivi nella cronologia della chat) la meno recente
    resterebbe in attesa per sempre, senza più un modo per sbloccarla.
    """
    voce = leggi(conn, voce_id)
    if voce.stato is not Stato.DA_APPROVARE:
        raise ValueError("si può riscrivere solo una bozza in attesa di approvazione")
    conn.execute(
        "UPDATE diary_entries SET stato_approvazione = 'da_approvare'"
        " WHERE stato_approvazione = 'in_modifica' AND id != ?",
        (voce_id,),
    )
    conn.execute(
        "UPDATE diary_entries SET stato_approvazione = 'in_modifica' WHERE id = ?", (voce_id,)
    )
    return leggi(conn, voce_id)


def annulla_modifica(conn: sqlite3.Connection, voce_id: int) -> Voce:
    """Torna alla bozza proposta, senza riscriverla."""
    voce = leggi(conn, voce_id)
    if voce.stato is not Stato.IN_MODIFICA:
        return voce
    conn.execute(
        "UPDATE diary_entries SET stato_approvazione = 'da_approvare' WHERE id = ?", (voce_id,)
    )
    return leggi(conn, voce_id)


def in_modifica(conn: sqlite3.Connection) -> Voce | None:
    """La voce che sta aspettando un testo riscritto, se ce n'è una."""
    riga = conn.execute(
        "SELECT * FROM diary_entries WHERE stato_approvazione = 'in_modifica'"
        " ORDER BY data DESC LIMIT 1"
    ).fetchone()
    return _componi(conn, [riga])[0] if riga else None


def approva(
    conn: sqlite3.Connection, voce_id: int, ora: datetime, *, testo: str | None = None
) -> Voce:
    """Salva nel diario la versione approvata.

    `testo` è la tua riscrittura: se c'è vince sulla bozza, parola per parola.
    Senza, si approva la proposta così com'è.
    """
    voce = leggi(conn, voce_id)
    definitivo = (testo if testo is not None else voce.riassunto_proposto or "").strip()
    if not definitivo:
        raise ValueError("non c'è niente da approvare")

    conn.execute(
        "UPDATE diary_entries SET riassunto_approvato = ?, riassunto_proposto = NULL,"
        " stato_approvazione = 'approvata', approvata_il = ? WHERE id = ?",
        (definitivo, ora.isoformat(timespec="seconds"), voce_id),
    )
    return leggi(conn, voce_id)


def scarta(conn: sqlite3.Connection, voce_id: int) -> None:
    """Butta via la giornata, materiale grezzo compreso.

    §8.4 è netto: nel diario entra solo ciò che approvi. Scartare significa
    "questo non deve restare", quindi non si conserva una bozza rifiutata da
    nessuna parte — il giorno torna semplicemente vuoto. I frammenti se ne
    vanno con la voce (`ON DELETE CASCADE`).
    """
    leggi(conn, voce_id)
    conn.execute("DELETE FROM diary_entries WHERE id = ?", (voce_id,))


# — riepilogo settimanale (§8.4 punto 7) —


def riepilogo(conn: sqlite3.Connection, settimana_inizio: date) -> RiepilogoSettimana | None:
    riga = conn.execute(
        "SELECT * FROM diary_weekly_summary WHERE settimana_inizio = ?",
        (settimana_inizio.isoformat(),),
    ).fetchone()
    if riga is None:
        return None
    return RiepilogoSettimana(
        settimana_inizio=date.fromisoformat(riga["settimana_inizio"]),
        testo=riga["testo"],
        generato_il=datetime.fromisoformat(riga["generato_il"]),
    )


def ultimo_riepilogo(conn: sqlite3.Connection) -> RiepilogoSettimana | None:
    riga = conn.execute(
        "SELECT * FROM diary_weekly_summary ORDER BY settimana_inizio DESC LIMIT 1"
    ).fetchone()
    if riga is None:
        return None
    return riepilogo(conn, date.fromisoformat(riga["settimana_inizio"]))


def salva_riepilogo(
    conn: sqlite3.Connection, *, settimana_inizio: date, testo: str, ora: datetime
) -> RiepilogoSettimana:
    """Scrive (o riscrive) il riepilogo di una settimana.

    `settimana_inizio` è chiave unica: se il job gira due volte per la stessa
    settimana il riepilogo viene sostituito, non duplicato.
    """
    pulito = testo.strip()
    if not pulito:
        raise ValueError("il riepilogo settimanale non può essere vuoto")
    conn.execute(
        # `excluded` è la riga che si stava inserendo: si riusa quella invece di
        # ripetere i parametri, così i segnaposto restano anonimi. Numerarli
        # (`?1`) mescolandoli a una sequenza è deprecato e in Python 3.14
        # diventa un errore.
        "INSERT INTO diary_weekly_summary (settimana_inizio, testo, generato_il)"
        " VALUES (?, ?, ?)"
        " ON CONFLICT (settimana_inizio) DO UPDATE SET"
        " testo = excluded.testo, generato_il = excluded.generato_il",
        (settimana_inizio.isoformat(), pulito, ora.isoformat(timespec="seconds")),
    )
    risultato = riepilogo(conn, settimana_inizio)
    assert risultato is not None  # appena scritto
    return risultato


# — statistiche, tutte in codice: nessuna di queste passa da un modello —


def giorni_consecutivi(voci: list[Voce], oggi: date) -> int:
    """Giorni di fila con una voce approvata, contando all'indietro.

    Si parte da oggi se oggi è già approvato, altrimenti da ieri: a metà
    giornata la serie non è ancora interrotta, e azzerarla sarebbe scoraggiante
    oltre che falso.
    """
    approvati = {v.giorno for v in voci if v.stato is Stato.APPROVATA}
    if not approvati:
        return 0
    corrente = oggi if oggi in approvati else oggi - timedelta(days=1)
    serie = 0
    while corrente in approvati:
        serie += 1
        corrente -= timedelta(days=1)
    return serie


def parole_media(voci: list[Voce]) -> int:
    lunghezze = [v.parole for v in voci if v.stato is Stato.APPROVATA and v.parole]
    return round(sum(lunghezze) / len(lunghezze)) if lunghezze else 0


def conteggio_tag(voci: list[Voce]) -> list[tuple[str, int]]:
    """Tag delle voci approvate, dal più frequente. A parità, in ordine alfabetico."""
    contatore = Counter(t for v in voci if v.stato is Stato.APPROVATA for t in v.tag)
    return sorted(contatore.items(), key=lambda c: (-c[1], c[0]))


def copertura(voci: list[Voce], *, da: date, giorni: int) -> list[bool]:
    """Un valore per giorno: True dove c'è una voce approvata."""
    approvati = {v.giorno for v in voci if v.stato is Stato.APPROVATA}
    return [(da + timedelta(days=i)) in approvati for i in range(giorni)]


def primo_del_mese(giorno: date) -> date:
    return date(giorno.year, giorno.month, 1)


def giorni_nel_mese(giorno: date) -> int:
    prossimo = (
        date(giorno.year + 1, 1, 1)
        if giorno.month == 12
        else date(giorno.year, giorno.month + 1, 1)
    )
    return (prossimo - primo_del_mese(giorno)).days
