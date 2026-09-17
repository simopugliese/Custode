"""Il giudizio su un pattern, e le parole per proportelo (§6, §8.10).

§6 manda questo compito a **Claude** con una motivazione precisa: «serve
giudizio per capire se un pattern è abbastanza solido da proporre». Questo
modulo è quella riga in codice, e la parola che conta è *giudizio*: i numeri li
ha già fatti `custode_core.dominio.pattern`, in codice puro e gratis, e quello
che resta da decidere non è **se il pattern c'è** ma se **vale la pena
interromperti** — e con che parole.

**Il modello non sceglie la forma della regola.** L'aggancio l'ha deciso il
rilevatore: questo tipo di impegno, o quest'ora in questi giorni. Claude decide
se proporre, cosa dirà il promemoria, perché te lo sta chiedendo, e — sui soli
agganci a un impegno — se ha senso **prima** o **dopo**, e con quanto scarto.
Quella sì è una domanda di giudizio: la creatina si prende dopo la palestra, il
portatile va messo in borsa prima della lezione, e nessun conteggio lo sa. Tutto
il resto arriva già validato, quindi una regola approvata è eseguibile per
costruzione dal valutatore che §8.10 ha già.

**Una chiamata sola per tutta la notte**, coi candidati numerati, come per il
tagging: la risposta si rilegge per numero e non per posizione, perché un
modello che salta una voce farebbe slittare tutte le successive e la
motivazione della corsa finirebbe sulla creatina.

**Una voce illeggibile non blocca le altre**, e qui il ripiego è più severo che
nel tagging: là una serie senza risposta diventava `altro`, che è un esito
legittimo; qui una proposta che non si riesce a leggere si **butta**. Non c'è un
ripiego sensato — inventare un messaggio vorrebbe dire farti approvare una
regola che nessuno ha scritto — e buttarla non lascia coda arretrata, perché il
pattern c'è ancora domani notte.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from custode_core.dominio import pattern as dom_pattern
from custode_core.dominio import regole as dom_regole
from custode_router.compiti import Compito
from custode_router.errori import RispostaNonValida
from custode_router.router import Router

MAX_CANDIDATI = 5
"""Quanti candidati entrano in una chiamata.

Non è il numero di proposte che riceverai — quello lo decide il worker, ed è
uno per notte. È quanti ne vede Claude per poter scegliere: mandargliene uno
solo vorrebbe dire aver già scelto in codice il più forte, e «il più forte» qui
è un ordinamento grezzo che non sa niente di quanto una cosa conti per te.
Oltre i cinque il prompt cresce per una scelta che si gioca comunque fra i
primi.
"""


@dataclass(frozen=True)
class Proposta:
    """Cosa Claude ha deciso di un candidato.

    `proponi = False` è una risposta piena e non un guasto: è il modello che
    fa il lavoro per cui §6 lo chiama, cioè dire che quel pattern regge nei
    numeri ma non vale un'interruzione.
    """

    candidato: dom_pattern.Candidato
    proponi: bool
    confidenza: dom_regole.Confidenza
    messaggio: str
    """Cosa dirà il promemoria quando la regola scatta."""
    motivazione: str
    """Perché te la sta proponendo, coi numeri dentro."""
    trigger: dom_regole.Trigger
    """Già deciso: per un aggancio a un impegno è la scelta di Claude fra prima
    e dopo, per un orario è `Trigger.ORARIO` e basta."""
    minuti: int = 0
    """Solo per gli agganci a un impegno."""


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposte": {
            "type": "array",
            "description": (
                "Una voce per ogni candidato ricevuto, col suo numero. Nessuno va saltato."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "n": {
                        "type": "integer",
                        "description": "Il numero del candidato, esattamente come nell'elenco.",
                    },
                    "proponi": {
                        "type": "boolean",
                        "description": (
                            "true se vale la pena interrompere il proprietario per"
                            " chiedergli se vuole questa regola."
                        ),
                    },
                    "confidenza": {
                        "type": "string",
                        "enum": [c.value for c in dom_regole.Confidenza],
                        "description": "Quanto sei convinto che questa regola gli servirà.",
                    },
                    "messaggio": {
                        "type": "string",
                        "description": (
                            "Il promemoria che gli arriverà su Telegram quando la regola"
                            " scatta. Una riga, in italiano, rivolta a lui: «prendi la"
                            " creatina», «metti il portatile nello zaino». Al massimo"
                            f" {dom_regole.MAX_CARATTERI_MESSAGGIO} caratteri."
                        ),
                    },
                    "motivazione": {
                        "type": "string",
                        "description": (
                            "Perché gliela stai proponendo, coi numeri che te l'hanno"
                            " fatta pensare, in una o due frasi e in italiano. Al massimo"
                            f" {dom_regole.MAX_CARATTERI_MOTIVAZIONE} caratteri."
                        ),
                    },
                    "quando": {
                        "type": "string",
                        "enum": ["prima", "dopo"],
                        "description": (
                            "Solo per i candidati agganciati a un impegno: se il"
                            " promemoria serve prima che cominci o dopo che è finito."
                        ),
                    },
                    "minuti": {
                        "type": "integer",
                        "description": (
                            "Solo per i candidati agganciati a un impegno: quanti minuti"
                            " prima dell'inizio, o dopo la fine. 0 vuol dire «appena"
                            f" comincia» o «appena finisce». Al massimo {dom_regole.MAX_MINUTI}."
                        ),
                    },
                },
                "required": ["n", "proponi", "confidenza", "messaggio", "motivazione"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["proposte"],
    "additionalProperties": False,
}


SISTEMA = f"""Aiuti Custode, l'assistente personale di una persona sola, a decidere
quali promemoria automatici proporle.

Custode ha già trovato delle regolarità nei suoi ultimi due mesi: cose che fa
quasi sempre insieme a un certo tipo di impegno, o quasi sempre alla stessa ora.
I conti sono già fatti e te li do. Quello che devi decidere tu è un'altra cosa:
**se valga la pena interromperla per chiederle se vuole quel promemoria**, e con
che parole dirglielo.

Come si decide:
- Un promemoria serve quando la cosa **si può dimenticare** e dimenticarla
  costa qualcosa. «Prendi la creatina dopo la palestra» serve. «Ricordati di
  cenare alle 20» no: mangiare non lo si dimentica, e quel promemoria diventa
  rumore che fa mettere in pausa anche quelli utili.
- Una regolarità forte nei numeri può comunque non meritare una regola: se una
  cosa la fa sempre e non l'ha mai saltata, un promemoria non aggiunge niente.
  Sono i **buchi** che rendono utile un promemoria.
- Nel dubbio, **non proporre**. Una proposta sbagliata costa più di una
  proposta mancata: la mancata torna domani notte, la sbagliata insegna a non
  guardare più la pagina.

Come rispondere:
- Una voce per **ogni** numero ricevuto, riportando il numero com'è. Anche per
  quelli che non proponi: `proponi` a false, e il messaggio e la motivazione
  scrivili lo stesso in breve.
- Il **messaggio** è quello che le arriverà su Telegram quando scatta: una
  riga, rivolta a lei, senza preamboli e senza ripetere quando scatta — l'ora
  e l'impegno glieli mostra Custode accanto. «Prendi la creatina», non
  «Ricordati che dopo la palestra dovresti prendere la creatina».
- La **motivazione** è quello che legge prima di approvare: dille i numeri che
  te l'hanno fatta pensare, non un'impressione. «In 15 delle 16 giornate con
  palestra hai segnato la creatina, e quasi mai negli altri giorni.»
- Per i candidati agganciati a un impegno, scegli anche **quando**: `prima` se
  il promemoria serve per arrivare preparata (il portatile prima della
  lezione), `dopo` se serve a cosa viene dopo (la creatina a fine allenamento).
  E quanti `minuti`: 0 vuol dire appena comincia o appena finisce, e va
  benissimo quando non c'è niente da preparare. Un anticipo ha senso se le
  serve tempo per fare la cosa.
- Per i candidati a orario, `quando` e `minuti` lasciali stare: l'ora è già
  decisa.
- Scrivi in italiano, dandole del tu.

Al massimo {dom_regole.MAX_CARATTERI_MESSAGGIO} caratteri per il messaggio e
{dom_regole.MAX_CARATTERI_MOTIVAZIONE} per la motivazione."""


def _riga(candidato: dom_pattern.Candidato) -> str:
    """Un candidato come lo legge il modello: i conti, in italiano."""
    if candidato.genere is dom_pattern.Genere.SU_IMPEGNO:
        return (
            f"abitudine «{candidato.soggetto}», agganciata agli impegni di tipo"
            f" «{candidato.tipo_evento}». Nelle ultime otto settimane ha avuto"
            f" {candidato.occasioni} giornate con un impegno di quel tipo, e in"
            f" {candidato.coperte} di quelle ha segnato «{candidato.soggetto}»."
            f" Nelle {candidato.giornate_altrove} giornate senza quell'impegno l'ha"
            f" segnata {candidato.altrove} volte."
        )
    quando = dom_regole.etichetta_giorni(candidato.giorni)
    return (
        f"abitudine «{candidato.soggetto}», a orario fisso. La segna {quando}:"
        f" {candidato.coperte} giornate utili su {candidato.occasioni}. Delle"
        f" {candidato.segnate} volte in cui l'ha scritta in giornata,"
        f" {candidato.nel_grappolo} erano intorno alle {candidato.ora}, che è"
        f" l'ora proposta per il promemoria."
    )


def componi_prompt(candidati: Sequence[dom_pattern.Candidato]) -> str:
    """L'elenco numerato che il modello riceve.

    A parte da `giudica` per poterlo guardare senza chiamare nessuno: il prompt
    è la parte che si sbaglia più spesso, e qui è anche l'unica che non si può
    provare con le chiavi vere in un test.
    """
    righe = [f"{n}. {_riga(c)}" for n, c in enumerate(candidati, start=1)]
    return "Regolarità trovate:\n" + "\n".join(righe)


def _testo(grezzo: object, massimo: int) -> str | None:
    if not isinstance(grezzo, str):
        return None
    pulito = " ".join(grezzo.strip().split())
    if not pulito or len(pulito) > massimo:
        return None
    return pulito


def _trigger_e_minuti(
    candidato: dom_pattern.Candidato, voce: dict[str, Any]
) -> tuple[dom_regole.Trigger, int] | None:
    """Prima o dopo, e con quanto scarto. `None` se la risposta non si può usare.

    Il ripiego su `dopo` e zero minuti è deliberato e vale solo per i **campi
    assenti**: «appena finisce» è la lettura più innocua di un aggancio a un
    impegno, e un modello che si dimentica il campo non deve costare la
    proposta. Un valore **presente e fuori scala** invece butta la voce: un
    anticipo di tre giorni non è una svista da correggere in silenzio, e
    troncarlo a un giorno vorrebbe dire far approvare una regola diversa da
    quella che il modello ha proposto.
    """
    if candidato.genere is not dom_pattern.Genere.SU_IMPEGNO:
        return dom_regole.Trigger.ORARIO, 0

    quando = voce.get("quando", "dopo")
    if quando not in ("prima", "dopo"):
        return None
    minuti = voce.get("minuti", 0)
    if not isinstance(minuti, int) or isinstance(minuti, bool):
        return None
    if not 0 <= minuti <= dom_regole.MAX_MINUTI:
        return None
    trigger = (
        dom_regole.Trigger.PRIMA_EVENTO if quando == "prima" else dom_regole.Trigger.DOPO_EVENTO
    )
    return trigger, minuti


def _leggi(candidati: Sequence[dom_pattern.Candidato], risposta: dict[str, Any]) -> list[Proposta]:
    grezze = risposta.get("proposte")
    if not isinstance(grezze, list):
        raise RispostaNonValida("la risposta non contiene un elenco di proposte")

    per_numero: dict[int, dict[str, Any]] = {}
    for voce in grezze:
        if isinstance(voce, dict) and isinstance(voce.get("n"), int):
            per_numero[voce["n"]] = voce

    lette: list[Proposta] = []
    for n, candidato in enumerate(candidati, start=1):
        voce = per_numero.get(n)
        if voce is None:
            continue
        messaggio = _testo(voce.get("messaggio"), dom_regole.MAX_CARATTERI_MESSAGGIO)
        motivazione = _testo(voce.get("motivazione"), dom_regole.MAX_CARATTERI_MOTIVAZIONE)
        if messaggio is None or motivazione is None:
            continue
        try:
            confidenza = dom_regole.Confidenza(voce.get("confidenza"))
        except ValueError:
            continue
        forma = _trigger_e_minuti(candidato, voce)
        if forma is None:
            continue
        trigger, minuti = forma
        lette.append(
            Proposta(
                candidato=candidato,
                proponi=bool(voce.get("proponi")),
                confidenza=confidenza,
                messaggio=messaggio,
                motivazione=motivazione,
                trigger=trigger,
                minuti=minuti,
            )
        )

    if not lette and candidati:
        # Niente di leggibile non è «nessuna proposta»: è un guasto, e dirlo
        # così permette a chi chiama di non segnare la notte come fatta.
        raise RispostaNonValida("nessuna delle proposte è leggibile")
    return lette


def giudica(router: Router, candidati: Sequence[dom_pattern.Candidato]) -> list[Proposta]:
    """Chiede a Claude quali di questi candidati valgano una domanda.

    Su elenco vuoto **non chiama nessuno**: è il caso di quasi tutte le notti,
    ed è la ragione per cui la soglia sta in codice prima di qui.
    """
    if not candidati:
        return []
    scelti = list(candidati[:MAX_CANDIDATI])
    risposta = router.chiedi_json(
        Compito.PROPOSTA_REGOLE,
        sistema=SISTEMA,
        utente=componi_prompt(scelti),
        schema=SCHEMA,
    )
    return _leggi(scelti, risposta)
