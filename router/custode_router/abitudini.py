"""Il report narrativo delle abitudini (§6, §8.6).

§8.6 chiede due cose diverse a due modelli diversi, e la divisione è quella di
§6:

- **Capire che «ho fatto x e y ma non z» parla di tre abitudini esistenti** è
  «matching contro lista abitudini esistenti, task semplice» e va a DeepSeek.
  Non sta qui ma in `custode_router.assistente`, dentro la stessa chiamata che
  interpreta ogni messaggio: sono due righe distinte di §6 con lo stesso
  provider, e farne due giri raddoppierebbe latenza e costo su ogni messaggio.
- **Il report narrativo settimanale e mensile** è «sintesi che incrocia più
  segnali» e va a Claude: è l'unico punto in cui si guardano insieme abitudini,
  diario e spese, ed è quello che sta qui.

I numeri non li calcola il modello. Aderenza, strisce e obiettivi centrati
arrivano già fatti da `custode_core.dominio.abitudini` e finiscono nel prompt
come dati: §8.6 li vuole «calcolati in codice, senza LLM», e un modello che
ricalcola una percentuale la sbaglia ogni tanto senza dirlo.

E come sempre il modello non tocca il database: da qui escono un testo e, se
c'è, una proposta di adeguamento del target — che resta una **proposta**, con
il suo bottone, finché non la accetti (§8.6, §8.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from custode_router.compiti import Compito
from custode_router.errori import RispostaNonValida
from custode_router.router import Router

# Un report che non si legge in trenta secondi non lo si legge affatto: il
# limite sta nel prompt e viene fatto rispettare qui, perché una richiesta nel
# prompt è una richiesta, non un vincolo.
MAX_CARATTERI_REPORT = 1200


@dataclass(frozen=True)
class PropostaTarget:
    """Un adeguamento di target proposto dal modello, ancora da approvare."""

    abitudine: str
    target_proposto: int
    motivazione: str


@dataclass(frozen=True)
class Rapporto:
    testo: str
    proposta: PropostaTarget | None = None


SCHEMA_REPORT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "report": {
            "type": "string",
            "description": (
                "Il racconto del periodo, in italiano, dando del tu. Due o tre"
                " paragrafi brevi, al massimo 1000 caratteri in tutto."
            ),
        },
        "proposta_abitudine": {
            "type": "string",
            "description": (
                "Solo se un target non regge da settimane o è chiaramente troppo"
                " basso: il nome dell'abitudine, copiato esattamente dall'elenco."
                " Stringa vuota nella grande maggioranza dei casi."
            ),
        },
        "proposta_target": {
            "type": "integer",
            "description": (
                "Il nuovo numero di volte a settimana da proporre, da 1 a 7,"
                " diverso da quello attuale. 0 se non stai proponendo niente."
            ),
        },
        "proposta_motivazione": {
            "type": "string",
            "description": (
                "Una riga che dice perché, coi numeri veri: «nelle ultime sei"
                " settimane sei a 2,1 di media». Vuota se non proponi niente."
            ),
        },
    },
    "required": ["report"],
    "additionalProperties": False,
}

SISTEMA = """Scrivi il resoconto delle abitudini di Custode, un assistente personale.

Ricevi i numeri già calcolati — quante volte, su quante attese, con che
aderenza — e, quando ci sono, il diario e le spese dello stesso periodo. Il tuo
lavoro è **metterli in relazione**, non ripeterli.

Come scriverlo:
- In italiano, dando del tu, come lo direbbe qualcuno che ti conosce.
- Due o tre paragrafi brevi. I numeri citali solo quando servono a dire
  qualcosa: «tre volte su tre» ha senso, un elenco di percentuali no.
- Il valore sta negli **incroci**: una settimana in cui la palestra è saltata e
  il diario parla di serate in biblioteca racconta qualcosa; le stesse due cose
  elencate una dopo l'altra non raccontano niente.
- Non fare la morale e non dare consigli non richiesti. Descrivi come è andata.
  Se una cosa non è andata, dillo senza girarci intorno e senza drammatizzare.
- Se non c'è abbastanza materiale, scrivi due righe oneste invece di riempire.
- Non inventare mai un numero né un fatto che non è nei dati che ricevi.

**La proposta di target.** Se e solo se i numeri lo dicono chiaramente, puoi
proporre di cambiare la frequenza target di UNA abitudine:
- verso il basso, quando un target è mancato per settimane di fila e continuare
  a mancarlo è l'unico esito possibile;
- verso l'alto, quando lo superi regolarmente da settimane.
Un periodo storto non basta: serve una tendenza. Nella maggior parte dei
resoconti non c'è nessuna proposta, e va benissimo così — proporre qualcosa ad
ogni giro è il modo più rapido perché smetta di essere ascoltato."""


def _riga_abitudine(dati: dict[str, Any]) -> str:
    return (
        f"- {dati['nome']}: obiettivo {dati['target']} volte a settimana,"
        f" fatta {dati['fatte']} volte su {dati['attese']:.1f} attese"
        f" ({dati['aderenza']}% del target), striscia attuale {dati['striscia']} giorni"
    )


def componi_prompt(
    *,
    periodo: str,
    intervallo: str,
    abitudini: list[dict[str, Any]],
    diario: list[str],
    spese: str | None,
) -> str:
    """Il testo che il modello riceve. A parte perché è la cosa da rileggere.

    Sta fuori da `report` per poterlo guardare in un test senza chiamare
    nessuno: il prompt è la parte che si sbaglia più spesso, e vederlo scritto
    è l'unico modo di accorgersene.
    """
    righe = [f"Resoconto {periodo} delle abitudini — {intervallo}.", "", "Abitudini:"]
    righe += [_riga_abitudine(a) for a in abitudini] or ["- nessuna abitudine attiva"]

    if diario:
        righe += ["", "Dal diario dello stesso periodo (voci approvate):"]
        righe += [f"- {voce}" for voce in diario]
    else:
        righe += ["", "Nel diario non c'è niente per questo periodo."]

    # Le spese entrano come una riga sola: servono a dare contesto («settimana
    # di spese fuori casa»), non a essere analizzate — quello è §8.5.
    righe += ["", f"Spese del periodo: {spese}" if spese else "Spese del periodo: nessuna."]

    if periodo == "settimanale":
        # Chiederla e poi scartarla sarebbe uno spreco: nel settimanale la
        # proposta non viene registrata comunque, perché sette giorni non sono
        # una tendenza (§8.6 parla di settimane che reggono e poi calano).
        righe += ["", "Questo è un resoconto settimanale: non proporre adeguamenti di target."]
    return "\n".join(righe)


def report(
    router: Router,
    *,
    periodo: str,
    intervallo: str,
    abitudini: list[dict[str, Any]],
    diario: list[str],
    spese: str | None = None,
) -> Rapporto:
    """Il racconto del periodo, con l'eventuale proposta di target (§8.6)."""
    dati = router.chiedi_json(
        # §6: «sintesi che incrocia più segnali (abitudini, diario, spese)».
        Compito.REPORT_ABITUDINI,
        sistema=SISTEMA,
        utente=componi_prompt(
            periodo=periodo,
            intervallo=intervallo,
            abitudini=abitudini,
            diario=diario,
            spese=spese,
        ),
        schema=SCHEMA_REPORT,
    )
    return leggi_risposta(dati, nomi_validi=[a["nome"] for a in abitudini])


def leggi_risposta(dati: dict[str, Any], *, nomi_validi: list[str]) -> Rapporto:
    """Valida la risposta prima che diventi un messaggio e una proposta."""
    testo = str(dati.get("report") or "").strip()
    if not testo:
        raise RispostaNonValida("il report è arrivato vuoto")
    return Rapporto(testo=testo[:MAX_CARATTERI_REPORT], proposta=_leggi_proposta(dati, nomi_validi))


def _leggi_proposta(dati: dict[str, Any], nomi_validi: list[str]) -> PropostaTarget | None:
    """La proposta, solo se è su un'abitudine che esiste e con un target sensato.

    Stessa regola della categoria di spesa in §8.5: la descrizione dello schema
    chiede già di copiare dall'elenco, ma è una richiesta e non un vincolo, e
    una proposta su un'abitudine inventata finirebbe sul database come una
    riga che non si può nemmeno accettare.
    """
    nome = str(dati.get("proposta_abitudine") or "").strip()
    if not nome:
        return None
    esatto = next((n for n in nomi_validi if n.casefold() == nome.casefold()), None)
    if esatto is None:
        return None

    grezzo = dati.get("proposta_target")
    if isinstance(grezzo, bool) or not isinstance(grezzo, int) or not 1 <= grezzo <= 7:
        return None
    motivazione = str(dati.get("proposta_motivazione") or "").strip()
    if not motivazione:
        # Senza il perché non è una proposta, è un ordine: la si scarta invece
        # di mostrare un bottone «Accetta» che non spiega cosa accetti.
        return None
    return PropostaTarget(abitudine=esatto, target_proposto=grezzo, motivazione=motivazione)


def messaggio_errore(errore: Exception) -> str:
    """Perché il resoconto non è arrivato, detto a chi usa il bot."""
    from custode_router.errori import ProviderNonConfigurato, ProviderNonRaggiungibile

    if isinstance(errore, ProviderNonConfigurato):
        return (
            "Il resoconto delle abitudini ha bisogno della chiave di Claude, che non è configurata."
        )
    if isinstance(errore, ProviderNonRaggiungibile):
        return "Non riesco a contattare Claude adesso: il resoconto arriverà al prossimo giro."
    return "Non sono riuscito a scrivere il resoconto delle abitudini."
