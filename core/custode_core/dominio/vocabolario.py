"""I nomi che il proprietario usa davvero, per aiutare Whisper a sentirli.

Whisper indovina le parole dal suono, e sui **nomi propri** sbaglia in modo
sistematico: «Bricoman» diventa «bricomane», «Analisi II» diventa «analisi
due», il nome di un'abitudine diventa una parola comune che gli somiglia. Sono
esattamente le parole che poi servono per agganciare un'abitudine, una
categoria di spesa o un task esistente — quindi lo sbaglio non resta nella
trascrizione, si propaga: l'interprete non trova più il riferimento e il
messaggio non fa niente.

whisper.cpp accetta un `--prompt`, cioè un testo iniziale che sposta le
probabilità verso quelle parole. Il vocabolario ce l'abbiamo già in casa: è
quasi lo stesso elenco che l'interprete riceve nel suo contesto (§8.1). Qui si
raccoglie in una funzione **pura di lettura**, che non sa niente né di Whisper
né del bot: chi trascrive decide come usarlo.
"""

from __future__ import annotations

import sqlite3

from custode_core.dominio import abitudini as dom_abitudini
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import spese as dom_spese
from custode_core.dominio import task as dom_task

# Quanto può essere lungo il testo passato a `--prompt`. whisper.cpp tiene al
# massimo `n_text_ctx/2` token — 224 per il modello `base` — e un prompt più
# lungo verrebbe tagliato dove capita. Ma il motivo vero del tetto è un altro:
# più parole si mettono, più il modello è disposto a *produrle* anche quando
# non le ha sentite. Un elenco corto di nomi distintivi aiuta; un dizionario
# intero comincia a mettere in bocca parole mai dette.
MASSIMO_CARATTERI = 400


def nomi(conn: sqlite3.Connection) -> list[str]:
    """I nomi in uso, dal più utile al meno utile.

    L'ordine conta perché la lista viene tagliata in coda: abitudini e
    categorie di spesa sono poche, ricorrenti e spesso inventate («Cardio
    breve», «Bricoman»), quindi valgono di più di un titolo di task, che è
    lungo, capita una volta sola e per giunta è già scritto in italiano
    corrente.
    """
    raccolti: list[str] = []
    raccolti += [a.nome for a in dom_abitudini.elenco(conn)]
    raccolti += [c.nome for c in dom_spese.categorie(conn, solo_attive=True)]
    voci = dom_lista.elenco(conn, preso=False)
    raccolti += sorted({v.reparto for v in voci})
    raccolti += [v.nome for v in voci]
    raccolti += [t.titolo for t in dom_task.elenco(conn, fatto=False)]

    # Senza ripetizioni e senza distinguere maiuscole: «Palestra» e «palestra»
    # sono la stessa parola per chi ascolta, e ripeterla non la rende più
    # probabile — toglie solo spazio a un'altra.
    visti: set[str] = set()
    unici: list[str] = []
    for nome in raccolti:
        pulito = nome.strip()
        if not pulito or pulito.casefold() in visti:
            continue
        visti.add(pulito.casefold())
        unici.append(pulito)
    return unici


def suggerimento(conn: sqlite3.Connection, massimo: int = MASSIMO_CARATTERI) -> str:
    """I nomi in una frase sola, pronta da passare a chi trascrive.

    È scritta come una frase italiana e non come un elenco di parole nude
    perché il prompt di Whisper *è* testo: il modello lo tratta come «ciò che è
    stato detto prima», e un elenco puntato lo porterebbe a continuare
    l'elenco invece del discorso. Vuota se non c'è ancora niente da suggerire —
    a un'installazione appena avviata non serve, e una frase vuota è meglio di
    una che promette parole che non esistono.
    """
    elenco = nomi(conn)
    if not elenco:
        return ""

    tenuti: list[str] = []
    lunghezza = 0
    for nome in elenco:
        aggiunta = len(nome) + 2  # il nome più «, »
        if lunghezza + aggiunta > massimo:
            break
        tenuti.append(nome)
        lunghezza += aggiunta
    if not tenuti:
        return ""
    return ", ".join(tenuti) + "."
