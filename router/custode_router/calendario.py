"""Il tipo di un evento di calendario, proposto dal modello (§6, §8.10).

§8.10 vuole che «l'IA proponga il tag la prima volta, tu corregga se serve, e
resti poi fisso per gli eventi ricorrenti». Qui c'è solo la prima metà: da un
elenco di titoli escono dei tipi, e chi chiama decide se e dove scriverli
(`custode_core.dominio.calendario.applica_tag`). Il modello non tocca il
database, come ovunque nel progetto.

**Una chiamata sola per tutta la coda, non una per serie.** Il tagging gira
ad ogni giro del worker, cioè ogni cinque minuti: una chiamata per serie
vorrebbe dire, il giorno che colleghi il calendario, decine di richieste di
fila per un lavoro che sta in una. Gli eventi arrivano quindi numerati e il
modello risponde con un elenco.

**Il numero, non l'ordine.** La risposta si rilegge per numero (`n`) e non per
posizione: un modello che salta una voce farebbe slittare tutte le successive,
e il tag della lezione finirebbe sulla palestra. Con i numeri una voce saltata
resta una voce saltata.

**L'elenco dei tipi non è più fisso** (pezzo 6). Erano quattro costanti qui
dentro; adesso arrivano da `calendar_tags`, e con loro arriva la **descrizione**
di ognuno — che è la parte che fa davvero il lavoro. Il prompt di prima non
diceva «viaggio», diceva «treni, voli, trasferte; non il luogo di un altro
impegno»: quella frase adesso è un dato, e la scrive chi crea il tag. Chi
chiama passa i tipi già letti, perché `router/` non tocca il database (§5) — il
giro del worker li legge e li consegna.

**Una voce illeggibile non blocca le altre.** Manca il numero, o il tipo è
inventato («sport», «lezione universitaria»): quella serie diventa `altro`
*proposto*, cioè lo stesso stato che avrebbe se il modello avesse detto altro
davvero — ed è quanto serve perché la coda si svuoti e tu possa correggerla
dalla pagina. La coda deve svuotarsi: una serie che resta dentro rientra nella
chiamata di ogni sincronizzazione, per sempre. Se invece **niente** è
leggibile, quella non è una classificazione, è un guasto: si solleva, e la
coda resta intatta per il giro dopo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from custode_core.dominio.calendario import SLUG_ALTRO
from custode_router.compiti import Compito
from custode_router.errori import RispostaNonValida
from custode_router.router import Router

MAX_TITOLI_PER_CHIAMATA = 40
"""Quanti eventi stanno in una chiamata sola.

Il vincolo è la **risposta**, non il prompt: `max_token_risposta` di DeepSeek è
1024 token, e ogni voce (`{"n": 12, "tipo": "palestra"}`) ne costa una
quindicina — oltre la sessantina di voci la risposta arriverebbe troncata, e
una risposta troncata è illeggibile per intero. Quaranta lascia il margine, e
la coda che avanza rientra nella chiamata della sincronizzazione dopo, cinque
minuti più tardi.
"""

MAX_CARATTERI_TITOLO = 120
"""Un titolo più lungo di così non aggiunge niente alla classificazione.

E soprattutto: quaranta titoli fluviali gonfierebbero il prompt di una chiamata
che gira ogni cinque minuti.
"""

SENZA_TITOLO = "(senza titolo)"
"""Un evento può non avere titolo. Una riga vuota nell'elenco numerato
sembrerebbe un errore di composizione, e il modello risponderebbe a caso."""


@dataclass(frozen=True)
class Proposta:
    """Il tipo proposto per un evento, e se il modello l'ha davvero detto."""

    tipo: str
    """Lo slug di un tag, non la sua etichetta: è ciò che si scrive in
    `calendar_events.tipo`."""
    letta: bool = True
    """`False` quando la voce mancava o era illeggibile e `tipo` è il ripiego
    (`altro`). Serve ai log del worker: un modello che diventa illeggibile su
    metà della coda è una cosa da poter vedere, anche se l'esito in tabella è
    identico a un «altro» detto sul serio."""


class TagDisponibile(Protocol):
    """Un tipo di evento come lo vede chi compone il prompt.

    Un Protocol e non `custode_core.dominio.calendario.Tag` per la stessa
    ragione per cui il dominio descrive `EventoEsterno` invece di importare la
    sorgente: qui serve la forma, non la riga di tabella. Chi chiama passa i
    tag che ha già letto, e `router/` resta senza database.
    """

    @property
    def slug(self) -> str: ...
    @property
    def descrizione(self) -> str: ...


def schema_tag(tag: Sequence[TagDisponibile]) -> dict[str, Any]:
    """Lo schema della risposta, con l'enum degli slug che esistono adesso.

    L'enum non è una decorazione: è ciò che impedisce al modello di inventare
    un tipo, e va ricostruito ad ogni chiamata perché fra un giro e l'altro un
    tag può nascere o essere archiviato.
    """
    slug = [voce.slug for voce in tag]
    return {
        "type": "object",
        "properties": {
            "tag": {
                "type": "array",
                "description": (
                    "Un elemento per ogni evento ricevuto, con il suo numero."
                    " Nessun evento va saltato."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {
                            "type": "integer",
                            "description": "Il numero dell'evento, esattamente come nell'elenco.",
                        },
                        "tipo": {
                            "type": "string",
                            "enum": slug,
                            "description": f"Uno dei {len(slug)} tipi, in minuscolo.",
                        },
                    },
                    "required": ["n", "tipo"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["tag"],
        "additionalProperties": False,
    }


APERTURA = """Classifichi gli impegni del calendario di Custode, un assistente personale.

Ricevi un elenco numerato di titoli di eventi. Per ognuno dici di che tipo è,
scegliendo fra questi e nessun altro:"""

REGOLE = """Come rispondere:
- Una voce per **ogni** numero che hai ricevuto, riportando il numero com'è.
  Non riordinare, non raggruppare, non saltare niente.
- Solo i tipi elencati qui sopra, scritti così, in minuscolo. Un tipo diverso
  non viene capito e la classificazione di quell'evento va persa.
- Il titolo è tutto quello che hai: non dedurre niente dalla posizione
  nell'elenco né dagli eventi vicini. Il fatto che il 3 sia una lezione non
  dice niente sul 4.
- Nel dubbio **{ripiego}**: è un tipo legittimo, non una resa. Un evento messo
  nella casella sbagliata è peggio di uno lasciato nel mucchio, perché non si
  vede finché non produce un promemoria fuori posto.
- I titoli sono in italiano, spesso abbreviati come li scriveresti di corsa
  sul telefono («Anal. Mat. I», «pale», «volo MXP→FCO»)."""


def sistema(tag: Sequence[TagDisponibile]) -> str:
    """Il prompt di sistema, con dentro i tipi che esistono adesso.

    Al modello arriva lo **slug** e la sua descrizione, non l'etichetta: lo
    slug è ciò che deve rispondere, e mostrargli anche il nome («Allenamento»)
    accanto a uno slug diverso (`palestra`) gli darebbe due parole fra cui
    scegliere per dire la stessa cosa. Chi rinomina un tag e vuole che il
    modello se ne accorga cambia la descrizione, che è la riga che legge
    davvero.
    """
    elenco = "\n".join(f"- **{voce.slug}** — {voce.descrizione}" for voce in tag)
    return f"{APERTURA}\n\n{elenco}\n\n{REGOLE.format(ripiego=SLUG_ALTRO)}"


def _ripulisci(titolo: str) -> str:
    """Un titolo su una riga sola, corto. L'elenco è numerato: un titolo con
    un a capo dentro sembrerebbe due eventi, e il modello risponderebbe a due."""
    pulito = " ".join(titolo.split())
    if not pulito:
        return SENZA_TITOLO
    return pulito[:MAX_CARATTERI_TITOLO]


def componi_prompt(titoli: list[str]) -> str:
    """L'elenco numerato che il modello riceve.

    A parte da `tag_per` per poterlo guardare senza chiamare nessuno: il prompt
    è la parte che si sbaglia più spesso.
    """
    righe = [f"{n}. {_ripulisci(titolo)}" for n, titolo in enumerate(titoli, start=1)]
    return "Eventi da classificare:\n" + "\n".join(righe)


MIN_TAG = 2
"""Sotto due tipi non c'è niente da classificare.

Non è un caso di scuola: `altro` non si può archiviare, ma gli altri sì, e con
un tipo solo ogni risposta possibile sarebbe «altro». Chiamare il modello per
farselo dire costerebbe una richiesta ogni cinque minuti per una conclusione
già nota.
"""


def tag_per(router: Router, titoli: list[str], tag: Sequence[TagDisponibile]) -> list[Proposta]:
    """Un tipo proposto per ogni titolo, nello stesso ordine.

    La lista che esce è **lunga quanto quella che entra**, sempre: chi chiama
    la appaia ai suoi gruppi, e una lista più corta gli farebbe scrivere il tag
    di un evento su un altro.

    `tag` sono i tipi **attivi**, letti da chi chiama: un tipo archiviato non
    va proposto, ma resta addosso agli eventi che già ce l'hanno.
    """
    if not titoli:
        # Non è un caso da difendere in astratto: il worker chiama solo quando
        # la coda non è vuota. Ma una chiamata a vuoto al modello si pagherebbe
        # comunque, e la risposta sarebbe illeggibile per costruzione.
        return []
    if len(titoli) > MAX_TITOLI_PER_CHIAMATA:
        raise ValueError(
            f"{len(titoli)} titoli in una chiamata sola: il massimo è {MAX_TITOLI_PER_CHIAMATA}"
        )
    if len(tag) < MIN_TAG:
        raise ValueError(f"{len(tag)} tipi disponibili: ne servono almeno {MIN_TAG}")

    dati = router.chiedi_json(
        # §6: «classificazione semplice da un titolo».
        Compito.TAG_CALENDARIO,
        sistema=sistema(tag),
        utente=componi_prompt(titoli),
        schema=schema_tag(tag),
    )
    return leggi_risposta(dati, quanti=len(titoli), slug=[voce.slug for voce in tag])


def leggi_risposta(dati: dict[str, Any], *, quanti: int, slug: Sequence[str]) -> list[Proposta]:
    """Rilegge la risposta per numero, con `altro` al posto di ciò che manca.

    Solleva se non si legge **niente**: una risposta in cui nessuna voce è
    valida non è «sono tutti altro», è un guasto, e scriverla in tabella
    seppellirebbe una coda intera dietro un tag che nessuno ha mai proposto.

    `slug` sono i tipi ammessi in questa risposta, e non si ricavano da una
    costante: sono quelli che il prompt ha davvero elencato. Un tipo fuori da
    quell'elenco è inventato — e lo è anche se nel frattempo qualcuno l'ha
    creato, perché il modello non l'ha mai visto.
    """
    ammessi = set(slug)
    per_numero: dict[int, str] = {}
    for voce in dati.get("tag") or []:
        if not isinstance(voce, dict):
            continue
        numero = voce.get("n")
        if isinstance(numero, bool) or not isinstance(numero, int) or not 1 <= numero <= quanti:
            continue
        tipo = _tipo(voce.get("tipo"), ammessi)
        if tipo is None or numero in per_numero:
            # Il primo che arriva vince: una seconda voce sullo stesso numero è
            # un ripensamento del modello, e non c'è motivo di credere alla
            # seconda più che alla prima.
            continue
        per_numero[numero] = tipo

    if not per_numero:
        raise RispostaNonValida(f"nessun tag leggibile fra {quanti} eventi: {dati!r}")

    return [
        Proposta(tipo=per_numero[n]) if n in per_numero else Proposta(tipo=SLUG_ALTRO, letta=False)
        for n in range(1, quanti + 1)
    ]


def _tipo(valore: object, ammessi: set[str]) -> str | None:
    """Lo slug, se è fra quelli ammessi. Maiuscole e spazi non fanno differenza.

    Lo schema lo chiede già in minuscolo, ma una richiesta nel prompt è una
    richiesta e non un vincolo: scartare un «Lezione» per la maiuscola
    costerebbe una classificazione giusta.
    """
    if not isinstance(valore, str):
        return None
    pulito = valore.strip().casefold()
    return pulito if pulito in ammessi else None
