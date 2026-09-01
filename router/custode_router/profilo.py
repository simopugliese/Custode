"""La rifusione del profilo (§8.4).

Il pezzo che §8.4 tiene a distinguere da un accodamento: Claude legge la
versione attuale del profilo, il riepilogo della settimana e i candidati che
hai approvato, e **riscrive il documento da capo** in forma compatta. Se ogni
settimana si limitasse ad aggiungere righe, il profilo crescerebbe all'infinito
— costoso da passare ad ogni chiamata e via via più rumore che segnale.

§6 lo manda a Claude perché «va integrato e sintetizzato con giudizio, non solo
concatenato»: è esattamente la parte che un modello economico farebbe male,
accodando invece di fondere.

Come sempre, il modello non tocca il database: produce un testo, e
`custode_core.dominio.profilo` decide se e come salvarlo.
"""

from __future__ import annotations

from typing import Any

from custode_router.compiti import Compito
from custode_router.errori import ErroreRouter, RispostaNonValida
from custode_router.router import Router

# Il profilo viaggia dentro altri prompt, quindi la sua lunghezza è un costo
# ricorrente, non una volta sola. §8.4 chiede «poche centinaia di parole».
PAROLE_MAX = 400

SCHEMA_PROFILO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profilo": {
            "type": "string",
            "description": (
                f"Il profilo riscritto per intero, al massimo {PAROLE_MAX} parole,"
                " in italiano, in terza persona descrittiva."
            ),
        },
        "cambiamenti": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Una riga per ogni cosa cambiata rispetto alla versione precedente:"
                " cosa è stato aggiunto, cosa corretto, cosa tolto perché superato."
            ),
        },
    },
    "required": ["profilo", "cambiamenti"],
    "additionalProperties": False,
}

SISTEMA = f"""Sei il curatore del profilo di Custode, l'assistente personale del
proprietario.

Il profilo è un documento unico che descrive **com'è fatto lui**: cosa gli
piace e cosa no, come lavora, come studia, cosa lo stanca, opinioni che gli
tornano. Serve a Custode come contesto, per non farsi rispiegare le stesse cose
ogni volta.

Ricevi la versione attuale, il riepilogo della settimana appena passata e i
segnali nuovi che lui ha approvato. **Riscrivi il documento da capo.**

Regole, in ordine di importanza:
- **Non è un accodamento.** Fondi il nuovo con il vecchio: se un segnale nuovo
  precisa o contraddice qualcosa che c'era, aggiorna quella frase invece di
  aggiungerne una seconda. Se due punti dicono la stessa cosa, uniscili.
- **Taglia.** Ciò che è superato, occasionale o non è più tornato negli ultimi
  aggiornamenti esce dal documento. Un profilo che cresce e basta smette di
  essere utile. Il massimo è {PAROLE_MAX} parole, ma se ne bastano cento sono
  cento.
- **Non inventare.** Ogni affermazione deve poggiare su ciò che ricevi, sulla
  versione attuale o sui segnali. Niente deduzioni psicologiche, niente
  caratterizzazioni che nessuno ha detto.
- **Distingui il duraturo dal momentaneo.** «Quella settimana era stanco» non è
  un tratto; «si stanca quando il lavoro è tutto frontend» lo è. Nel dubbio,
  lascialo fuori: tornerà se è vero.
- Scrivi in **terza persona descrittiva** («Preferisce il backend», «Studia
  meglio la mattina»), in prosa o brevi paragrafi tematici, senza intestazioni
  e senza elenchi puntati.
- Se non c'era ancora nessun profilo, scrivilo da zero con quello che hai, e
  non riempire i vuoti: un profilo corto e vero vale più di uno lungo e supposto.

In `cambiamenti` elenca cosa hai cambiato rispetto alla versione precedente,
una riga per cosa, in modo che lui possa controllare a colpo d'occhio se la
riscrittura ha perso qualcosa."""


class RifusioneNonRiuscita(ErroreRouter):
    """La rifusione non è disponibile: il motivo è già in italiano leggibile."""


def _contesto(profilo: str | None, riepilogo: str | None, candidati: list[str]) -> str:
    righe: list[str] = []
    if profilo:
        righe += ["Versione attuale del profilo:", profilo, ""]
    else:
        righe += ["Non esiste ancora un profilo: questa sarà la prima versione.", ""]
    if riepilogo:
        righe += ["Riepilogo della settimana appena passata:", riepilogo, ""]
    righe += ["Segnali nuovi, approvati dal proprietario:"]
    righe += [f"- {c}" for c in candidati]
    return "\n".join(righe)


def rifondi(
    router: Router,
    *,
    profilo: str | None,
    riepilogo: str | None,
    candidati: list[str],
) -> tuple[str, list[str]]:
    """Riscrive il profilo. Ritorna il testo nuovo e l'elenco dei cambiamenti.

    Senza né segnali nuovi né riepilogo non c'è niente da rifondere: rifare il
    giro produrrebbe una versione identica alla precedente, a pagamento.
    """
    puliti = [c.strip() for c in candidati if c.strip()]
    if not puliti and not riepilogo:
        raise RifusioneNonRiuscita("Non c'è niente di nuovo da mettere nel profilo.")

    dati = router.chiedi_json(
        # §6: «va integrato e sintetizzato con giudizio, non solo concatenato».
        Compito.RIFUSIONE_PROFILO,
        sistema=SISTEMA,
        utente=_contesto(profilo, riepilogo, puliti),
        schema=SCHEMA_PROFILO,
    )
    return leggi_rifusione(dati)


def leggi_rifusione(dati: dict[str, Any]) -> tuple[str, list[str]]:
    """Valida la risposta: uno schema rispettato non garantisce un testo pieno."""
    testo = str(dati.get("profilo") or "").strip()
    if not testo:
        raise RispostaNonValida("il profilo rifuso è arrivato vuoto")

    grezzi = dati.get("cambiamenti") or []
    cambiamenti = (
        [str(c).strip() for c in grezzi if str(c).strip()] if isinstance(grezzi, list) else []
    )
    return testo, cambiamenti


def messaggio_errore(errore: Exception) -> str:
    """Perché il profilo non è stato aggiornato, detto a chi usa il bot."""
    from custode_router.errori import ProviderNonConfigurato, ProviderNonRaggiungibile

    if isinstance(errore, RifusioneNonRiuscita):
        return str(errore)
    if isinstance(errore, ProviderNonConfigurato):
        return "Il profilo ha bisogno della chiave di Claude, che non è configurata."
    if isinstance(errore, ProviderNonRaggiungibile):
        return (
            "Non riesco a contattare Claude adesso: il profilo resta com'era e"
            " i segnali approvati aspettano la prossima settimana."
        )
    return "Non sono riuscito a riscrivere il profilo. I segnali approvati non si perdono."
