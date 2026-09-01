"""Etichette in italiano prodotte dal backend.

Il contratto con la dashboard passa stringhe già formattate (`scadenzaLabel`,
`dataLabel`, …): la logica sta qui, in un posto solo, perché le stesse frasi
le dovrà dire anche il bot Telegram (§8.1).

I nomi di giorni e mesi sono scritti a mano invece di usare `locale`: le
immagini slim non hanno il locale `it_IT` installato, e dipendere da una
configurazione di sistema per il testo dell'interfaccia è un modo silenzioso
di rompersi solo in produzione.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

GIORNI = (
    "lunedì",
    "martedì",
    "mercoledì",
    "giovedì",
    "venerdì",
    "sabato",
    "domenica",
)
MESI = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)
GIORNI_BREVI = (
    "Lun",
    "Mar",
    "Mer",
    "Gio",
    "Ven",
    "Sab",
    "Dom",
)
MESI_BREVI = (
    "gen",
    "feb",
    "mar",
    "apr",
    "mag",
    "giu",
    "lug",
    "ago",
    "set",
    "ott",
    "nov",
    "dic",
)


def adesso(timezone: str) -> datetime:
    """Ora corrente nel fuso configurato, senza informazione di offset.

    Tutto il resto del modulo ragiona su date e ore locali: portarsi dietro il
    tzinfo servirebbe solo a confrontare per sbaglio istanti con date."""
    return datetime.now(ZoneInfo(timezone)).replace(tzinfo=None)


def _mese_breve(giorno: date) -> str:
    return MESI_BREVI[giorno.month - 1]


def etichetta_giorno(giorno: date, oggi: date) -> str:
    """ "oggi", "domani", "giovedì", "26 ago" a seconda di quanto è lontano."""
    delta = (giorno - oggi).days
    if delta == 0:
        return "oggi"
    if delta == 1:
        return "domani"
    if delta == -1:
        return "ieri"
    # Entro la settimana il nome del giorno è più immediato della data.
    if 2 <= delta <= 6:
        return GIORNI[giorno.weekday()]
    if giorno.year != oggi.year:
        return f"{giorno.day} {_mese_breve(giorno)} {giorno.year}"
    return f"{giorno.day} {_mese_breve(giorno)}"


def etichetta_scadenza(scadenza: date | datetime | None, ora: datetime) -> str | None:
    """Etichetta di scadenza per una riga di task.

    Esempi, come da contratto: `"18:00"` (oggi a quell'ora), `"domani"`,
    `"26 ago"`. `None` per un task senza scadenza: la dashboard non mostra nulla.
    """
    if scadenza is None:
        return None

    if isinstance(scadenza, datetime):
        giorno_label = etichetta_giorno(scadenza.date(), ora.date())
        orario = f"{scadenza.hour:02d}:{scadenza.minute:02d}"
        # Per oggi l'ora basta da sola: dire "oggi 18:00" è ridondante.
        return orario if scadenza.date() == ora.date() else f"{giorno_label} {orario}"

    return etichetta_giorno(scadenza, ora.date())


def etichetta_data_lunga(ora: datetime) -> str:
    """ "sabato 30 agosto" — intestazione di pagina."""
    return f"{GIORNI[ora.weekday()]} {ora.day} {MESI[ora.month - 1]}"


def etichetta_data_ora(ora: datetime) -> str:
    """ "sabato 30 agosto, 08:41" — intestazione della Home."""
    return f"{etichetta_data_lunga(ora)}, {etichetta_ora(ora)}"


def etichetta_ora(ora: datetime) -> str:
    return f"{ora.hour:02d}:{ora.minute:02d}"


def etichetta_giorno_voce(giorno: date) -> str:
    """ "Ven 29 agosto" — intestazione di una voce di diario.

    Il giorno della settimana abbreviato e la data per esteso: in una timeline
    serve sapere subito se era un sabato, e la data completa evita di contare
    all'indietro quando si scorre un mese intero.
    """
    return f"{GIORNI_BREVI[giorno.weekday()]} {giorno.day} {MESI[giorno.month - 1]}"


def etichetta_mese(giorno: date, oggi: date) -> str:
    """ "agosto" per l'anno in corso, "agosto 2025" per gli altri."""
    mese = MESI[giorno.month - 1]
    return mese if giorno.year == oggi.year else f"{mese} {giorno.year}"


def plurale(quantita: int, singolare: str, plurale_: str) -> str:
    """ "1 task" / "3 task" — evita di scrivere ogni volta lo stesso ternario."""
    return f"{quantita} {singolare if quantita == 1 else plurale_}"


def inizio_settimana(giorno: date) -> date:
    """Lunedì della settimana di `giorno` (la settimana italiana parte da lì)."""
    return giorno - timedelta(days=giorno.weekday())
