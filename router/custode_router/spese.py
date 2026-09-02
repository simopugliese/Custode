"""Spese: categoria nuova e lettura degli scontrini (§6, §8.5).

Due compiti distinti della tabella §6, con due provider diversi, ed è una
distinzione che vale la pena tenere:

- **Assegnare** una spesa a una categoria che esiste già è «classificazione
  semplice» e va a DeepSeek. Succede nella stessa chiamata che interpreta il
  messaggio, quindi non costa niente in più.
- **Creare** una categoria nuova va a Claude, perché §6 chiede giudizio per
  «evitare categorie duplicate o incoerenti»: è il momento in cui si decide se
  quello che stai comprando è già «Alimentari» o merita un nome suo, e
  sbagliarlo lascia il doppione lì per sempre.
- **Leggere uno scontrino** è l'unica riga vision di §6.

Come sempre, il modello non tocca il database: qui escono nomi e numeri, e
`custode_core.dominio.spese` decide se salvarli.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from custode_router.compiti import Compito
from custode_router.errori import ErroreRouter, RispostaNonValida
from custode_router.router import Router

# Uno scontrino fotografato male può produrre righe all'infinito: oltre questo
# non è più una sintesi da confermare a colpo d'occhio.
MAX_VOCI = 40


class LetturaNonRiuscita(ErroreRouter):
    """Lo scontrino non si è potuto leggere: il motivo è già in italiano."""


# — categoria nuova (Claude, §6) —————————————————————————

SCHEMA_CATEGORIA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "categoria": {
            "type": "string",
            "description": (
                "Il nome della categoria: una o due parole, iniziale maiuscola,"
                " al singolare o plurale come si direbbe normalmente."
            ),
        },
        "esistente": {
            "type": "boolean",
            "description": (
                "true se hai scelto una categoria già presente nell'elenco,"
                " false se ne stai proponendo una nuova."
            ),
        },
    },
    "required": ["categoria", "esistente"],
    "additionalProperties": False,
}

SISTEMA_CATEGORIA = """Curi le categorie di spesa di Custode.

Ricevi una spesa e l'elenco delle categorie già in uso. Decidi in quale va.

Regole:
- **Prima guarda se ce n'è già una che calza.** Una categoria in più è un costo
  permanente: sporca i grafici e va poi unita a mano. Nel dubbio, riusa.
- Considera equivalenti i sinonimi: se esiste «Alimentari», la spesa al
  supermercato va lì e non in una nuova «Cibo» o «Spesa».
- Proponi una categoria nuova solo quando nessuna di quelle esistenti la
  conterrebbe in modo sensato.
- Le categorie devono restare **poche e larghe**: descrivono a cosa serve la
  spesa, non cosa hai comprato. «Trasporti», non «Biglietto del treno».
- **Il nome del negozio non è mai una categoria.** Da Bricoman si compra vernice
  e da Esselunga si compra la cena: la categoria dice a cosa ti è servita la
  spesa («Casa», «Alimentari»), non dove l'hai fatta — quello è già salvato a
  parte. Una categoria per negozio ne farebbe nascere una nuova ogni volta.
- Se non c'è ancora nessuna categoria, proponi la prima con lo stesso criterio:
  larga abbastanza da contenerne altre simili."""


def categoria_per(
    router: Router, *, descrizione: str, luogo: str | None, esistenti: list[str]
) -> str:
    """La categoria in cui va una spesa, riusando le esistenti quando può."""
    righe = [f"Spesa: {descrizione.strip()}"]
    if luogo:
        righe.append(f"Luogo: {luogo.strip()}")
    righe.append("")
    righe.append(
        "Categorie già in uso: " + ("; ".join(esistenti) if esistenti else "nessuna, è la prima")
    )

    dati = router.chiedi_json(
        # §6: «richiede giudizio, evita categorie duplicate/incoerenti».
        Compito.CATEGORIE_SPESA,
        sistema=SISTEMA_CATEGORIA,
        utente="\n".join(righe),
        schema=SCHEMA_CATEGORIA,
    )
    nome = str(dati.get("categoria") or "").strip()
    if not nome:
        raise RispostaNonValida("la categoria proposta è arrivata vuota")
    return nome


# — lettura dello scontrino (Claude vision, §6) ————————————


@dataclass(frozen=True)
class Scontrino:
    centesimi: int
    luogo: str
    giorno: date | None
    voci: list[str] = field(default_factory=list)

    @property
    def dettaglio(self) -> str:
        """Le voci lette, da conservare in `scontrino_raw_estratto` (§7)."""
        return "\n".join(self.voci)


SCHEMA_SCONTRINO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "leggibile": {
            "type": "boolean",
            "description": (
                "false se l'immagine non è uno scontrino, o è troppo sfocata,"
                " tagliata o scura per leggerne il totale con sicurezza."
            ),
        },
        "totale": {
            "type": "number",
            "description": "Il totale pagato in euro, come numero. 0 se non leggibile.",
        },
        "luogo": {
            "type": "string",
            "description": "Il nome dell'esercizio come compare sullo scontrino.",
        },
        "data": {
            "type": "string",
            "description": "La data dello scontrino in formato AAAA-MM-GG, vuota se assente.",
        },
        "voci": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Le righe acquistate, una per voce, nella forma «nome — prezzo»."
                " Vuoto se non si leggono."
            ),
        },
    },
    "required": ["leggibile", "totale", "luogo", "data", "voci"],
    "additionalProperties": False,
}

SISTEMA_SCONTRINO = """Leggi scontrini fotografati per Custode.

Ricevi la foto di uno scontrino e ne estrai i dati. Quello che conta di più è
il **totale**: è il numero che finirà nei conti del proprietario.

Regole:
- **Se non sei sicuro, dillo.** Meglio `leggibile: false` che un totale
  inventato: un numero sbagliato nei conti è peggio di una foto da rifare, e
  lui la foto ce l'ha ancora nel telefono.
- Il totale è quello **effettivamente pagato**: dopo sconti e resto, non il
  subtotale e non il contante consegnato.
- Il luogo è il nome dell'esercizio in cima allo scontrino, non l'indirizzo né
  la ragione sociale per esteso se c'è un'insegna più corta.
- Le voci vanno riportate come sono scritte, senza normalizzarle e senza
  raggrupparle. Se sono troppe o illeggibili, lasciale vuote: il totale resta
  la cosa importante.
- Non inventare mai una data: se non si legge, lasciala vuota."""


def leggi_scontrino(
    router: Router, *, immagine: bytes, oggi: date, media_type: str = "image/jpeg"
) -> Scontrino:
    """Estrae totale, luogo e voci dalla foto di uno scontrino (§8.5).

    `oggi` serve a scartare una data impossibile: il modello non ha un
    orologio, e senza un riferimento non può accorgersi di aver letto male.
    """
    if not immagine:
        raise LetturaNonRiuscita("Non ho ricevuto nessuna immagine.")

    dati = router.chiedi_json_con_immagine(
        Compito.LETTURA_SCONTRINO,
        sistema=SISTEMA_SCONTRINO,
        utente="Leggi questo scontrino.",
        schema=SCHEMA_SCONTRINO,
        immagine=immagine,
        media_type=media_type,
    )
    return leggi_risposta(dati, oggi=oggi)


def leggi_risposta(dati: dict[str, Any], *, oggi: date) -> Scontrino:
    """Valida la risposta del modello prima che diventi una spesa da confermare."""
    if not dati.get("leggibile"):
        raise LetturaNonRiuscita(
            "Non riesco a leggere questo scontrino. Riprova con una foto più"
            " nitida, dritta e con tutto il totale dentro."
        )

    grezzo = dati.get("totale")
    if not isinstance(grezzo, int | float) or isinstance(grezzo, bool):
        raise RispostaNonValida(f"totale non numerico: {grezzo!r}")
    centesimi = round(float(grezzo) * 100)
    if centesimi <= 0:
        raise LetturaNonRiuscita("Il totale letto è zero: controlla la foto.")

    giorno: date | None = None
    testo_data = str(dati.get("data") or "").strip()
    if testo_data:
        try:
            giorno = date.fromisoformat(testo_data)
        except ValueError:
            # Una data storta non fa buttare via il resto: si userà oggi.
            giorno = None
    # Una spesa già pagata non può essere di domani: una data nel futuro è una
    # lettura sbagliata, e prenderla per buona farebbe sparire lo scontrino da
    # ogni vista — tutte finiscono a oggi — senza dire niente a nessuno.
    if giorno is not None and giorno > oggi:
        giorno = None

    grezze = dati.get("voci") or []
    voci = (
        [str(v).strip() for v in grezze if str(v).strip()][:MAX_VOCI]
        if isinstance(grezze, list)
        else []
    )
    return Scontrino(
        centesimi=centesimi,
        luogo=str(dati.get("luogo") or "").strip(),
        giorno=giorno,
        voci=voci,
    )


def messaggio_errore(errore: Exception) -> str:
    """Perché la spesa non è stata registrata, detto a chi usa il bot."""
    from custode_router.errori import ProviderNonConfigurato, ProviderNonRaggiungibile

    if isinstance(errore, LetturaNonRiuscita):
        return str(errore)
    if isinstance(errore, ProviderNonConfigurato):
        return "Leggere gli scontrini ha bisogno della chiave di Claude, che non è configurata."
    if isinstance(errore, ProviderNonRaggiungibile):
        return "Non riesco a contattare Claude adesso. Riprova fra poco, o scrivimi la spesa."
    return "Non sono riuscito a leggere lo scontrino. Prova a scrivermi la spesa a parole."
