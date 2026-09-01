"""Dal materiale grezzo di una giornata al riassunto proposto (§8.4).

È il primo compito che manda traffico vero a Claude: §6 lo instrada lì perché
"qualità del linguaggio, sfumature" — un riassunto di diario che appiattisce il
tono non serve a niente, e il profilo cumulativo che ne nasce nemmeno.

Come per l'assistente, il modello non tocca il database: produce un testo e dei
tag, e chi chiama decide se e quando salvarli (`custode_core.dominio.diario`).
Nulla di quello che esce da qui entra nel diario senza passare da te.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from custode_router.compiti import Compito
from custode_router.errori import ErroreRouter, RispostaNonValida
from custode_router.router import Router

# Il riassunto va letto in dieci secondi su un telefono, prima di approvarlo:
# più lungo di così non lo si rilegge davvero, e si finisce per dire sì a scatola
# chiusa — che è esattamente ciò che l'approvazione dovrebbe impedire.
PAROLE_MIN = 40
PAROLE_MAX = 120

SCHEMA_RIASSUNTO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "riassunto": {
            "type": "string",
            "description": (
                f"Il riassunto della giornata, fra {PAROLE_MIN} e {PAROLE_MAX} parole,"
                " in italiano, rivolto al proprietario dandogli del tu."
            ),
        },
        "tag": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Da uno a quattro tag in minuscolo, una o due parole ciascuno, che"
                " categorizzano la giornata (per esempio: studio, lavoro, salute,"
                " umore, famiglia, viaggio)."
            ),
        },
    },
    "required": ["riassunto", "tag"],
    "additionalProperties": False,
}

SISTEMA = f"""Sei il diarista di Custode, l'assistente personale del proprietario.

Ricevi il materiale grezzo di una sua giornata: frasi buttate lì durante il
giorno, vocali trascritti, appunti sconnessi, in ordine di arrivo. Ne scrivi una
voce di diario che lui rileggerà fra mesi.

Regole, in ordine di importanza:
- **Non inventare niente.** Se una cosa non è nel materiale, non esiste. Niente
  conclusioni, niente stati d'animo dedotti, niente dettagli di contorno per
  rendere il testo più bello. È il suo diario, non un racconto.
- Scrivi **dandogli del tu**, al passato: «Hai chiuso il capitolo 3», non «Il
  proprietario ha chiuso» né «Ho chiuso».
- Da {PAROLE_MIN} a {PAROLE_MAX} parole, in italiano, in prosa continua: nessun
  elenco puntato, nessun titolo, nessun a capo.
- Tieni le sfumature: se era una giornata storta, il testo lo deve far sentire.
  Riordina e condensa, non rendere neutro.
- Le cose pratiche già registrate altrove (task, spesa) non sono diario: entrano
  solo se nel materiale hanno un peso personale.
- Se il materiale è scarno, scrivi una voce corta e onesta: meglio due righe
  vere che un paragrafo gonfiato.

I tag servono a ritrovare i temi ricorrenti nei mesi: pochi, generali,
riutilizzabili da un giorno all'altro — non uno diverso per ogni giornata."""


@dataclass(frozen=True)
class Riassunto:
    testo: str
    tag: list[str]


class RiassuntoNonRiuscito(ErroreRouter):
    """Il riassunto non è disponibile: il motivo è già in italiano leggibile."""


def _contesto(giorno: date, grezzo: str, precedente: str | None, profilo: str | None = None) -> str:
    righe = [f"Giornata del {giorno.isoformat()}.", ""]
    if profilo:
        # Il profilo entra qui e non nel prompt di sistema: è dato, non
        # istruzione, e cambia da settimana a settimana mentre il sistema resta
        # fisso. Serve a cogliere le sfumature — «di nuovo il frontend» invece
        # di «ha lavorato al frontend» — non a farsi raccontare cose diverse.
        righe += [
            "Cosa sai già di lui (non ripeterlo nel riassunto: serve solo a",
            "riconoscere ciò che per lui è ricorrente o fuori dal solito):",
            profilo,
            "",
        ]
    if precedente:
        # Succede quando aggiungi qualcosa a una giornata già approvata: la
        # nuova voce deve integrare quella vecchia, non ripartire da zero e
        # perdere pezzi che avevi già confermato.
        righe += [
            "Versione già approvata in precedenza, da integrare con il materiale nuovo:",
            precedente,
            "",
        ]
    righe += ["Materiale grezzo della giornata:", grezzo.strip()]
    return "\n".join(righe)


def riassumi(
    router: Router,
    *,
    giorno: date,
    grezzo: str,
    precedente: str | None = None,
    profilo: str | None = None,
) -> Riassunto:
    """Chiede a Claude la voce di diario per una giornata (§6, §8.4).

    `profilo` è il documento cumulativo di §8.4: è l'unico posto, oggi, in cui
    conoscere il proprietario cambia davvero l'uscita, e costa una chiamata al
    giorno invece di una per messaggio.
    """
    if not grezzo.strip():
        raise RiassuntoNonRiuscito("Non c'è ancora niente da riassumere per questa giornata.")

    dati = router.chiedi_json(
        # Si nomina il compito, mai il modello: la tabella §6 lo manda a Claude.
        Compito.RIASSUNTO_DIARIO,
        sistema=SISTEMA,
        utente=_contesto(giorno, grezzo, precedente, profilo),
        schema=SCHEMA_RIASSUNTO,
    )
    return leggi_riassunto(dati)


def leggi_riassunto(dati: dict[str, Any]) -> Riassunto:
    """Valida la risposta del modello.

    Structured outputs garantisce la forma, non che il campo sia pieno: un
    riassunto vuoto passerebbe lo schema e finirebbe come bozza da approvare.
    """
    testo = str(dati.get("riassunto") or "").strip()
    if not testo:
        raise RispostaNonValida("il riassunto del diario è arrivato vuoto")

    grezzi = dati.get("tag") or []
    tag = (
        [str(t).strip().lower() for t in grezzi if str(t).strip()]
        if isinstance(grezzi, list)
        else []
    )
    return Riassunto(testo=testo, tag=tag)


# — riepilogo settimanale (§8.4 punto 7) —

# Più lungo di una voce giornaliera perché copre sette giorni, ma resta una
# cosa che si legge: è un riepilogo, non un secondo diario.
PAROLE_SETTIMANA_MAX = 250

SCHEMA_SETTIMANA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "riepilogo": {
            "type": "string",
            "description": (
                f"Il riepilogo della settimana, al massimo {PAROLE_SETTIMANA_MAX}"
                " parole, in italiano, dando del tu al proprietario."
            ),
        }
    },
    "required": ["riepilogo"],
    "additionalProperties": False,
}

SISTEMA_SETTIMANA = f"""Sei il diarista di Custode.

Ricevi le voci di diario **già approvate** di una settimana, in ordine di
giorno. Ne scrivi un riepilogo che il proprietario rileggerà per capire com'è
andata nel suo insieme.

Regole:
- **Non inventare niente**: vale solo ciò che c'è nelle voci.
- Cerca i **fili che attraversano i giorni** — cosa è tornato più volte, cosa è
  cambiato dal lunedì alla domenica, cosa è rimasto in sospeso. Un elenco di
  riassunti giornalieri incollati non serve a niente: quello ce l'ha già.
- Dagli del tu, al passato, in prosa continua. Al massimo
  {PAROLE_SETTIMANA_MAX} parole.
- Se la settimana ha poche voci, dillo e sii breve: meglio corto che gonfiato.
- Niente incoraggiamenti, niente consigli, niente morale. È un resoconto."""


def riepilogo_settimanale(router: Router, *, lunedi: date, voci: list[tuple[date, str]]) -> str:
    """Il riepilogo di una settimana dalle sue voci approvate (§6, §8.4)."""
    if not voci:
        raise RiassuntoNonRiuscito("Questa settimana non hai nessuna voce approvata.")

    righe = [f"Settimana dal {lunedi.isoformat()}.", ""]
    for giorno, testo in voci:
        righe += [f"{giorno.isoformat()}: {testo}"]

    dati = router.chiedi_json(
        Compito.RIEPILOGO_SETTIMANALE_DIARIO,
        sistema=SISTEMA_SETTIMANA,
        utente="\n".join(righe),
        schema=SCHEMA_SETTIMANA,
    )
    testo = str(dati.get("riepilogo") or "").strip()
    if not testo:
        raise RispostaNonValida("il riepilogo settimanale è arrivato vuoto")
    return testo


def messaggio_errore(errore: Exception) -> str:
    """Perché il riassunto non c'è, detto a chi sta usando il bot."""
    from custode_router.errori import ProviderNonConfigurato, ProviderNonRaggiungibile

    if isinstance(errore, RiassuntoNonRiuscito):
        return str(errore)
    if isinstance(errore, ProviderNonConfigurato):
        return "Il diario ha bisogno della chiave di Claude, che non è configurata."
    if isinstance(errore, ProviderNonRaggiungibile):
        return "Non riesco a contattare Claude adesso. Il materiale è salvato: riprova fra poco."
    return "Non sono riuscito a scrivere il riassunto. Il materiale della giornata è salvo."
