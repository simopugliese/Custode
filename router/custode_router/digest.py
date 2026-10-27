"""La prosa del digest mattutino (§6, §8.13).

§6 mette il digest su DeepSeek: «composizione/template, nessun ragionamento
complesso». Il modello **compone soltanto il testo**: orari, titoli, aderenza,
la frase dell'ombrello e le note «manca X» arrivano già calcolati dal codice, e
gli si chiede di riportarli alla lettera.

Chiederlo non basta, e per questo c'è `leggi_risposta`: un testo in cui manca un
orario o un titolo, o che è lungo il triplo del previsto, non è una
composizione, è un fatto cambiato. In quel caso chi chiama usa il testo di base
che il codice ha già in mano, e il digest esce comunque.
"""

from __future__ import annotations

from typing import Any

from custode_router.compiti import Compito
from custode_router.errori import RispostaNonValida
from custode_router.router import Router

# Un digest che non si legge in un colpo d'occhio la mattina non si legge: il
# limite sta nel prompt e viene fatto rispettare qui.
MAX_CARATTERI_DIGEST = 1200

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "testo": {
            "type": "string",
            "description": (
                "Il messaggio del mattino, in italiano, dando del tu, al massimo"
                " 1000 caratteri. Testo semplice, senza markup."
            ),
        }
    },
    "required": ["testo"],
    "additionalProperties": False,
}

SISTEMA = """Scrivi il messaggio del mattino di Custode, un assistente personale.

Ricevi i fatti della giornata **già calcolati**: impegni, meteo, task, abitudini.
Il tuo lavoro è metterli in un messaggio breve e leggibile, non verificarli.

Come scriverlo:
- In italiano, dando del tu, tono diretto, come un messaggio a una persona che
  conosci. Poche righe, a capo fra un argomento e l'altro.
- Orari, titoli degli impegni, nomi di task e abitudini, e le frasi segnate
  «da dire così» vanno riportati **esattamente come li ricevi**, parola per parola.
- Non aggiungere nessun fatto che non è nell'elenco: niente consigli sul
  vestiario, niente impegni dedotti, niente numeri tuoi.
- Le note «non ho …» dicono cosa manca: riportale, non cercare di rimediare.
- Niente markup (né HTML né Markdown), niente emoji se non le ricevi già."""


def componi_prompt(fatti: list[str]) -> str:
    """Il testo che il modello riceve. A parte per poterlo guardare in un test."""
    return "Fatti di oggi:\n" + "\n".join(f"- {fatto}" for fatto in fatti)


def leggi_risposta(dati: dict[str, Any], *, obbligatori: list[str]) -> str:
    """Il testo, solo se non ha perso né cambiato niente di quello che serve."""
    testo = str(dati.get("testo") or "").strip()
    if not testo:
        raise RispostaNonValida("il digest è arrivato vuoto")
    if len(testo) > MAX_CARATTERI_DIGEST:
        raise RispostaNonValida(f"il digest è lungo {len(testo)} caratteri")
    mancanti = [fatto for fatto in obbligatori if fatto not in testo]
    if mancanti:
        raise RispostaNonValida(f"nel digest manca: {mancanti[0]!r}")
    return testo


def componi(router: Router, fatti: list[str], *, obbligatori: list[str]) -> str:
    """Il testo del digest. Solleva `ErroreRouter` se non c'è un testo buono."""
    dati = router.chiedi_json(
        # §6: «composizione/template, nessun ragionamento complesso».
        Compito.DIGEST_MATTUTINO,
        sistema=SISTEMA,
        utente=componi_prompt(fatti),
        schema=SCHEMA,
    )
    return leggi_risposta(dati, obbligatori=obbligatori)
