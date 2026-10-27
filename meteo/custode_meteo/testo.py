"""Dal dato alle parole, senza modello (§8.12).

Il meteo grezzo non ha bisogno di un LLM: un codice WMO è una tabella, e
«porta l'ombrello» è una soglia. Costo: zero.
"""

from __future__ import annotations

SOGLIA_OMBRELLO = 50
"""Da che probabilità di pioggia in su conviene dirlo. Sotto, l'avviso diventa
rumore e si smette di leggerlo."""


def descrizione(codice: int) -> str:
    """Il codice WMO in una parola, nella lingua della dashboard."""
    if codice == 0:
        return "sereno"
    if codice in (1, 2):
        return "poco nuvoloso"
    if codice == 3:
        return "coperto"
    if codice in (45, 48):
        return "nebbia"
    if 51 <= codice <= 57:
        return "pioviggine"
    if 61 <= codice <= 67 or 80 <= codice <= 82:
        return "pioggia"
    if 71 <= codice <= 77 or codice in (85, 86):
        return "neve"
    if codice >= 95:
        return "temporale"
    return "variabile"


def frase_ombrello(prob_pioggia: int | None, impegno: tuple[str, str] | None) -> str | None:
    """«Piove e hai lezione alle 9, porta l'ombrello», o niente.

    `impegno` è (ora, titolo) del prossimo impegno con un orario, se c'è. Senza
    probabilità non si dice nulla: tacere è meglio che indovinare.
    """
    if prob_pioggia is None or prob_pioggia < SOGLIA_OMBRELLO:
        return None
    if impegno is None:
        return f"Pioggia probabile ({prob_pioggia}%): porta l'ombrello."
    ora, titolo = impegno
    return f"Pioggia probabile ({prob_pioggia}%) e hai «{titolo}» alle {ora}: porta l'ombrello."
