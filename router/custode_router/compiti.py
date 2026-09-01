"""La tabella di ARCHITECTURE.md §6, in codice.

Ogni riga della tabella del documento è qui sotto, compreso il motivo: se un
giorno una scelta va rivista, la si rivede in un posto solo e la si vede
accanto a tutte le altre.
"""

from __future__ import annotations

from enum import StrEnum


class Provider(StrEnum):
    DEEPSEEK = "deepseek"
    CLAUDE = "claude"


class Compito(StrEnum):
    """I compiti che possono richiedere un modello."""

    PARSING_LISTA_SPESA = "parsing_lista_spesa"
    CRUD_TASK = "crud_task"
    LOG_ABITUDINI = "log_abitudini"
    CATEGORIZZAZIONE_SPESA = "categorizzazione_spesa"
    SEGNALE_PROFILO = "segnale_profilo"
    CHIARIMENTO_SEGNALE = "chiarimento_segnale"
    DIGEST_MATTUTINO = "digest_mattutino"
    LETTURA_SCONTRINO = "lettura_scontrino"
    RIASSUNTO_DIARIO = "riassunto_diario"
    RIEPILOGO_SETTIMANALE_DIARIO = "riepilogo_settimanale_diario"
    RIFUSIONE_PROFILO = "rifusione_profilo"
    CATEGORIE_SPESA = "categorie_spesa"
    PROPOSTA_REGOLE = "proposta_regole"
    PIANO_RIPASSO = "piano_ripasso"
    REPORT_ABITUDINI = "report_abitudini"
    RIASSUNTO_EMAIL = "riassunto_email"


# Compito -> (provider, motivo). Il motivo è quello scritto in §6: tenerlo qui
# accanto alla scelta evita che la tabella e il documento divergano in silenzio.
TABELLA: dict[Compito, tuple[Provider, str]] = {
    Compito.PARSING_LISTA_SPESA: (Provider.DEEPSEEK, "task semplice, alto volume"),
    Compito.CRUD_TASK: (Provider.DEEPSEEK, "task semplice"),
    Compito.LOG_ABITUDINI: (Provider.DEEPSEEK, "matching contro una lista esistente"),
    Compito.CATEGORIZZAZIONE_SPESA: (Provider.DEEPSEEK, "classificazione semplice"),
    Compito.SEGNALE_PROFILO: (Provider.DEEPSEEK, "classificazione leggera, alto volume"),
    Compito.CHIARIMENTO_SEGNALE: (Provider.DEEPSEEK, "interazione semplice"),
    Compito.DIGEST_MATTUTINO: (Provider.DEEPSEEK, "composizione da template"),
    Compito.LETTURA_SCONTRINO: (Provider.CLAUDE, "serve qualità nella lettura OCR + vision"),
    Compito.RIASSUNTO_DIARIO: (Provider.CLAUDE, "qualità del linguaggio, sfumature"),
    Compito.RIEPILOGO_SETTIMANALE_DIARIO: (Provider.CLAUDE, "ragionamento su più giorni"),
    Compito.RIFUSIONE_PROFILO: (Provider.CLAUDE, "va integrato con giudizio, non concatenato"),
    Compito.CATEGORIE_SPESA: (Provider.CLAUDE, "evitare categorie duplicate o incoerenti"),
    Compito.PROPOSTA_REGOLE: (Provider.CLAUDE, "giudizio su quanto un pattern regge"),
    Compito.PIANO_RIPASSO: (Provider.CLAUDE, "ragionamento incrociando risposte e syllabus"),
    Compito.REPORT_ABITUDINI: (Provider.CLAUDE, "sintesi che incrocia più segnali"),
    Compito.RIASSUNTO_EMAIL: (Provider.CLAUDE, "contenuto sensibile, un solo fornitore fidato"),
}

# Compiti che richiedono di mandare un'immagine al modello.
CON_IMMAGINI: frozenset[Compito] = frozenset({Compito.LETTURA_SCONTRINO})

# §6 lo dice esplicitamente: valutare una regola di contesto già approvata è
# logica pura (confronto di orari ed eventi), non passa da nessun modello e
# quindi non ha una voce qui. Costo zero, e va tenuto così.
SENZA_MODELLO = "valutazione di una regola di contesto già approvata"


def provider_per(compito: Compito) -> Provider:
    return TABELLA[compito][0]


def motivo(compito: Compito) -> str:
    return TABELLA[compito][1]
