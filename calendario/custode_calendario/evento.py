"""Un evento di calendario, come lo vede Custode.

È volutamente più povero di quello che Google restituisce: qui stanno solo i
campi che §8.10 usa davvero. Tutto il resto — partecipanti, allegati, colori,
promemoria di Google — non entra, perché ogni campo in più è un campo da
mantenere e da spiegare, e nessuno di quelli serve a far scattare una regola.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class Evento:
    """Un impegno, con gli orari già in ora locale e **senza fuso**.

    La scelta del naive locale non è di questo modulo: è quella del progetto
    (`custode_core.formato.adesso` fa lo stesso). Se qui restassero datetime
    con fuso, ogni confronto con «adesso» — che è ciò che fa una regola di
    contesto — mescolerebbe due tipi che Python si rifiuta di confrontare, e la
    scoperta arriverebbe la prima volta che una regola deve scattare.
    """

    id: str
    """L'id dell'evento su Google. Stabile fra una sincronizzazione e l'altra."""

    titolo: str
    inizio: datetime
    fine: datetime

    tutto_il_giorno: bool = False
    """Un evento «di giornata» non ha un'ora, e `prima_evento` non si applica."""

    luogo: str = ""

    serie_id: str = ""
    """L'evento ricorrente di cui questo è una ripetizione, se lo è.

    Serve al passo successivo di §8.10: il tipo si decide una volta per la
    **serie** («Analisi II» è una lezione) e non ogni martedì da capo. Costa
    zero raccoglierlo adesso, e raccoglierlo dopo vorrebbe dire risincronizzare.
    """

    @property
    def giorno(self) -> date:
        return self.inizio.date()


class SorgenteCalendario(Protocol):
    """Da dove arrivano gli eventi.

    Esiste perché il resto di §8.10 non deve sapere che dietro c'è Google: il
    motore di contesto ragiona su `Evento`, e cambiare sorgente — o aggiungerne
    una seconda, come un feed iCal — non lo tocca.
    """

    def configurata(self) -> bool:
        """False se mancano le credenziali: il modulo è spento, non rotto."""
        ...

    def eventi(self, da: date, a: date) -> list[Evento]:
        """Gli eventi fra due giorni, estremi inclusi, ordinati per inizio."""
        ...
