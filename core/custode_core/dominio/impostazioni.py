"""Le impostazioni che si cambiano senza riavviare niente (§8).

**Dove sta il confine col `.env`.** Nel `.env` restano tre categorie, e per tre
ragioni diverse: i **segreti** (§9 vuole una convenzione sola, e il database
finisce nel backup ogni notte), ciò che serve **per partire** (dove sta il
database non si può leggere dal database; le origini CORS servono a montare il
middleware, cioè prima che esista una richiesta), e la **whitelist** di §9 —
una lista di chi può scrivere al bot, modificabile con una `PATCH`, è una lista
che un bug dell'API può allargare. Qui sta il resto: le preferenze.

**Come si applica un cambio senza riavviare.** Non c'è nessun meccanismo, ed è
il punto: un'impostazione calda si **rilegge nel momento in cui serve**, da un
file SQLite che API, bot e worker hanno già aperto. L'API apre una connessione
per richiesta, quindi è a caldo per costruzione; il worker le rilegge in cima a
ogni giro invece che all'avvio, e un cambio è attivo entro un ciclo. La regola
da non rompere è una sola: **un'impostazione calda non finisce mai in una
variabile di modulo**, perché lì smetterebbe di essere calda senza che niente lo
segnali.

**Il `.env` è il punto di partenza, non una seconda fonte di verità.** Finché
non hai mai salvato, una chiave non ha riga e vale il `default` che chi legge
passa — tipicamente il valore del `.env`, che è la configurazione con cui
l'installazione è nata. Dal primo salvataggio vince il database, e la variabile
d'ambiente smette di contare. È la strada che `ImpostazioniWorker.giorno_riepilogo`
annunciava già prima che questo modulo esistesse.

**Il registro è qui e non nel database.** La tabella è chiave/valore, quindi
non sa quali chiavi esistono né che forma abbiano: lo sa questo modulo, ed è
anche l'unica porta di scrittura. Una chiave fuori dal registro non si salva —
altrimenti un errore di battitura in una `PATCH` diventerebbe una riga che
nessuno leggerà mai, e che nessuno saprà spiegare.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class ImpostazioneInesistente(KeyError):
    """La chiave non è nel registro: non si legge e non si scrive."""


class ValoreNonValido(ValueError):
    """Il valore non ha la forma che questa impostazione pretende."""


@dataclass(frozen=True)
class Impostazione(Generic[T]):
    """Una manopola: come si chiama, quanto vale se non l'hai mai toccata, e
    cosa si rifiuta di accettare.

    `default` è il valore di un'installazione che non ha né una riga in tabella
    né una variabile d'ambiente — l'ultima spiaggia. Chi legge può passarne uno
    diverso, ed è così che il `.env` fa da punto di partenza senza diventare una
    seconda fonte di verità.
    """

    chiave: str
    default: T
    valida: Callable[[object], T]
    """Prende quello che arriva — da JSON o da una richiesta HTTP — e restituisce
    il valore nella forma giusta, o solleva `ValoreNonValido`. È la stessa
    funzione nei due versi, ed è voluto: un valore salvato ieri da una versione
    più permissiva deve incontrare lo stesso controllo di uno che arriva adesso.
    """

    def leggi(self, conn: sqlite3.Connection, *, default: T | None = None) -> T:
        """Il valore salvato, o il default. Non solleva mai su una riga storta.

        Un valore illeggibile in tabella — scritto a mano con `sqlite3`, o
        rimasto da una versione in cui quella chiave voleva dire un'altra cosa —
        vale come **assente**. Sollevare qui vorrebbe dire una pagina intera che
        non si apre, o peggio un worker che muore ad ogni giro, per una riga che
        si sistema sovrascrivendola.
        """
        riga = conn.execute(
            "SELECT valore FROM impostazioni WHERE chiave = ?", (self.chiave,)
        ).fetchone()
        ripiego = self.default if default is None else default
        if riga is None:
            return ripiego
        try:
            return self.valida(json.loads(riga["valore"]))
        except (json.JSONDecodeError, ValoreNonValido):
            return ripiego

    def scrivi(self, conn: sqlite3.Connection, valore: object, ora: datetime) -> T:
        """Salva, dopo aver validato. Ritorna il valore come è stato salvato."""
        pulito = self.valida(valore)
        conn.execute(
            "INSERT INTO impostazioni (chiave, valore, aggiornato_il) VALUES (?, ?, ?)"
            " ON CONFLICT (chiave) DO UPDATE SET valore = excluded.valore,"
            " aggiornato_il = excluded.aggiornato_il",
            (self.chiave, json.dumps(pulito), ora.isoformat(timespec="seconds")),
        )
        return pulito


# — i controlli —


def _euro_o_niente(valore: object) -> float | None:
    """Un importo in euro, o «nessun tetto».

    `None` è un valore legittimo e non un campo vuoto: §8.5 dice che senza
    budget la Home **omette** il blocco delle spese invece di disegnare una
    barra su un tetto immaginario. Zero non è la stessa cosa — sarebbe un tetto
    a zero euro, cioè sempre sforato.
    """
    if valore is None or (isinstance(valore, str) and not valore.strip()):
        return None
    if isinstance(valore, bool) or not isinstance(valore, int | float | str):
        raise ValoreNonValido(f"non è un importo: {valore!r}")
    try:
        numero = float(str(valore).replace(",", "."))
    except ValueError as errore:
        raise ValoreNonValido(f"non è un importo: {valore!r}") from errore
    if numero <= 0:
        raise ValoreNonValido("un budget deve essere maggiore di zero")
    if numero > 1_000_000:
        raise ValoreNonValido("un budget settimanale di oltre un milione non è un budget")
    return round(numero, 2)


def _minuti(valore: object) -> int:
    """Un numero di minuti fra zero e mezza giornata.

    Il tetto non è prudenza astratta: questo è il margine dopo l'ultima lezione
    (§8.10), e un margine di due giorni non è un margine — è un promemoria che
    non arriva più, e che non si capisce perché.
    """
    if isinstance(valore, bool) or not isinstance(valore, int | str):
        raise ValoreNonValido(f"non è un numero di minuti: {valore!r}")
    try:
        minuti = int(valore)
    except ValueError as errore:
        raise ValoreNonValido(f"non è un numero di minuti: {valore!r}") from errore
    if not 0 <= minuti <= 720:
        raise ValoreNonValido("i minuti devono stare fra 0 e 720 (mezza giornata)")
    return minuti


def _giorno_settimana(valore: object) -> str:
    if valore not in ("domenica", "lunedi"):
        raise ValoreNonValido(f"deve essere «domenica» o «lunedi», non {valore!r}")
    assert isinstance(valore, str)
    return valore


def _orario(valore: object) -> str:
    """HH:MM, e normalizzato: «9:5» entra come «09:05».

    Normalizzare serve perché questa stringa la si confronta e la si rimostra:
    un «9:5» salvato una volta si rileggerebbe storto per sempre.
    """
    if not isinstance(valore, str):
        raise ValoreNonValido(f"non è un orario: {valore!r}")
    pezzi = valore.strip().split(":")
    if len(pezzi) != 2:
        raise ValoreNonValido(f"un orario si scrive HH:MM, non {valore!r}")
    try:
        ore, minuti = int(pezzi[0]), int(pezzi[1])
    except ValueError as errore:
        raise ValoreNonValido(f"un orario si scrive HH:MM, non {valore!r}") from errore
    if not (0 <= ore <= 23 and 0 <= minuti <= 59):
        raise ValoreNonValido(f"orario fuori intervallo: {valore!r}")
    return f"{ore:02d}:{minuti:02d}"


# — il registro —

BUDGET_SETTIMANALE: Impostazione[float | None] = Impostazione(
    chiave="budget_settimanale",
    default=None,
    valida=_euro_o_niente,
)
"""Quanto conti di spendere in una settimana (§8.5).

Senza, la Home omette il blocco «Spese · settimana»: una barra ha bisogno di un
tetto, e inventarlo sarebbe un giudizio su come spendi. Il `.env`
(`CUSTODE_BUDGET_SETTIMANALE`) resta il valore di partenza finché non lo salvi
da qui.
"""

RIEPILOGO_GIORNO: Impostazione[str] = Impostazione(
    chiave="riepilogo_settimanale_giorno",
    default="domenica",
    valida=_giorno_settimana,
)
"""Quando chiudere la settimana del diario (§8.4). Default dal `.env`
(`WORKER_GIORNO_RIEPILOGO`)."""

RIEPILOGO_ORA: Impostazione[str] = Impostazione(
    chiave="riepilogo_settimanale_ora",
    default="21:00",
    valida=_orario,
)
"""A che ora, nel fuso di `CUSTODE_TIMEZONE`. Default dal `.env`
(`WORKER_ORA_RIEPILOGO`).

Sta nel contratto accanto al giorno perché mezzo interruttore non è un
interruttore: scegliere il giorno e non poter scegliere l'ora vuol dire tornare
sul Pi comunque.
"""

CHECK_IN_MINUTI_DOPO: Impostazione[int] = Impostazione(
    chiave="check_in_minuti_dopo",
    default=40,
    valida=_minuti,
)
"""Il margine dopo l'ultima lezione prima di considerarti a casa (§8.10).

**Esiste prima di chi la userà**, come `calendar_events.tipo` prima del tagging
e `habit_proposals.tipo` prima delle proposte: §8.10 chiede esplicitamente che
il buffer sia «configurabile (es. 30-45 min)», e l'inferenza «sei probabilmente
a casa» la leggerà da qui invece di nascere con un numero inchiodato dentro.
Quaranta minuti è il centro dell'intervallo che §8.10 nomina.
"""

REGISTRO: tuple[Impostazione[Any], ...] = (
    BUDGET_SETTIMANALE,
    RIEPILOGO_GIORNO,
    RIEPILOGO_ORA,
    CHECK_IN_MINUTI_DOPO,
)
"""Tutte le impostazioni che esistono. Serve a chi deve elencarle o ripulirle."""


def per_chiave(chiave: str) -> Impostazione[Any]:
    """L'impostazione con questo nome, o `ImpostazioneInesistente`.

    È la porta da cui passa chi scrive per nome (un comando di manutenzione, un
    test): una chiave inventata deve trovare un errore, non diventare una riga
    che nessuno leggerà mai.
    """
    for voce in REGISTRO:
        if voce.chiave == chiave:
            return voce
    raise ImpostazioneInesistente(chiave)


def ore_e_minuti(orario: str) -> tuple[int, int]:
    """Spezza un «HH:MM» in due interi, rivalidandolo.

    Sta qui e non in chi lo usa perché è la coppia di `_orario`: chi salva
    un'ora passa di lì, chi la usa passa di qui, e il controllo è lo stesso nei
    due versi. Solleva `ValoreNonValido` su una stringa storta — che a questo
    punto vorrebbe dire una riga scritta a mano nel database, e un job che
    scattasse a un'ora inventata sarebbe peggio di un job che si lamenta.
    """
    ore, minuti = _orario(orario).split(":")
    return int(ore), int(minuti)


def salvate(conn: sqlite3.Connection) -> dict[str, datetime]:
    """Quali impostazioni hai deciso tu, e quando.

    Non i valori: quelli si leggono una per una col loro tipo. Questo dice
    quali righe **esistono**, che è la differenza fra «vale il `.env`» e «vale
    quello che hai scelto» — l'unica domanda a cui il `.env` da solo non sa
    rispondere.
    """
    return {
        riga["chiave"]: datetime.fromisoformat(riga["aggiornato_il"])
        for riga in conn.execute("SELECT chiave, aggiornato_il FROM impostazioni")
    }
