"""Quando un job è dovuto — logica pura, nessun orologio e nessun database.

Tutto ciò che decide *se* è il momento sta qui e prende `adesso` come
parametro: la differenza fra un test che gira in un millesimo di secondo e uno
che aspetterebbe fino a domenica sera.

Cosa un job ha *già fatto* sta invece in `custode_core.registro_job`, perché
quella tabella ormai la leggono in due — il worker e l'API.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from custode_core.formato import inizio_settimana

MINUTI_SYNC_CALENDARIO = 5
"""Ogni quanto risincronizzare il calendario (§8.10).

Uguale a `WORKER_INTERVALLO_SECONDI` di default (300 secondi): con la fascia
alla stessa misura del risveglio, ogni giro del worker prova a sincronizzare —
il calendario si aggiorna in tempo quasi reale invece che a scatti di un
quarto d'ora. Il costo resta trascurabile: `events.list` non è a pagamento, e
288 chiamate al giorno sono lo 0,03% del tetto di quota di Google (1.000.000
al giorno per progetto).

Resta comunque una **fascia**, non «sincronizza ad ogni giro» scritto a mano:
se `WORKER_INTERVALLO_SECONDI` fosse configurato più stretto di cinque minuti,
o il worker si svegliasse due volte a distanza ravvicinata (un riavvio), la
fascia evita comunque una seconda chiamata a Google per lo stesso minuto —
`job_runs` resta l'unico posto che decide «l'ho già fatto per questo periodo».

Non è configurabile: è una costante che discende da una scelta di progetto, non
un gusto della macchina su cui gira.
"""


def momento_previsto(lunedi: date, giorno: str, ore: int, minuti: int) -> datetime:
    """Quando va chiusa la settimana che comincia il `lunedi` indicato.

    Con `domenica` è la sera dell'ultimo giorno della settimana stessa; con
    `lunedi` è il giorno dopo, cioè il lunedì successivo — in entrambi i casi
    la settimana è finita quando la si riepiloga.
    """
    scarto = 6 if giorno == "domenica" else 7
    return datetime.combine(lunedi + timedelta(days=scarto), time(hour=ore, minute=minuti))


def settimana_dovuta(adesso: datetime, *, giorno: str, ore: int, minuti: int) -> date | None:
    """Il lunedì della settimana da riepilogare adesso, o None se non è ora.

    Si guarda indietro di due settimane invece di controllare solo «è oggi il
    giorno giusto?»: se il Pi era spento all'ora prevista, il job deve partire
    appena torna acceso invece di saltare la settimana. Due e non di più perché
    dopo un'assenza lunga ha senso riprendere dall'ultima settimana, non
    rovesciare addosso quattro revisioni tutte insieme.
    """
    lunedi = inizio_settimana(adesso.date())
    for candidato in (lunedi, lunedi - timedelta(days=7)):
        if adesso >= momento_previsto(candidato, giorno, ore, minuti):
            return candidato
    return None


def giorno_dovuto(adesso: datetime, *, ore: int, minuti: int) -> date:
    """Il giorno per cui un job *giornaliero* è dovuto adesso.

    Stessa forma del settimanale: prima dell'ora di oggi si guarda a ieri,
    perché se il Pi era spento a quell'ora il backup di ieri non è stato fatto e
    va recuperato appena torna su. Ritorna sempre una data — sarà il registro a
    dire se quel giorno è già stato coperto.
    """
    if adesso >= datetime.combine(adesso.date(), time(hour=ore, minute=minuti)):
        return adesso.date()
    return adesso.date() - timedelta(days=1)


def fascia_dovuta(adesso: datetime, *, ogni_minuti: int) -> datetime:
    """L'inizio della fascia di `ogni_minuti` in cui cade `adesso`.

    È la forma che prende «cosa è dovuto adesso?» per un job che gira più volte
    al giorno: la fascia fa da periodo, esattamente come il lunedì per il
    riepilogo settimanale, e il registro dice se quella è già stata coperta. Il
    worker si sveglia più spesso di così, quindi una fascia può essere
    interrogata più volte e coperta una sola.

    **Non si guarda indietro**, al contrario del settimanale e del giornaliero.
    Se il Pi era spento non c'è niente da recuperare: le fasce perse non
    contengono lavoro arretrato, contengono lo stesso lavoro di adesso. Rifarle
    una per una vorrebbe dire risincronizzare novantasei volte di fila per
    ottenere ciò che un solo giro ottiene subito.

    Le fasce sono ancorate all'ora, non al momento dell'avvio: con quindici
    minuti sono :00, :15, :30, :45, uguali dopo ogni riavvio. Se `ogni_minuti`
    non divide 60 l'ultima fascia dell'ora resta più corta — accettabile, e la
    ragione per cui i divisori di 60 sono gli unici valori sensati.
    """
    if not 1 <= ogni_minuti <= 60:
        raise ValueError(f"la fascia dev'essere fra 1 e 60 minuti, non {ogni_minuti}")
    return adesso.replace(
        minute=(adesso.minute // ogni_minuti) * ogni_minuti, second=0, microsecond=0
    )


def mese_dovuto(adesso: datetime, *, ore: int, minuti: int) -> date | None:
    """Il primo giorno del mese da raccontare adesso, o None se non è ora.

    Il mese si chiude quando è finito: il resoconto di settembre parte il primo
    di ottobre, alla stessa ora del riepilogo settimanale. Come per la
    settimana si guarda anche a quello prima, così un Pi spento il primo del
    mese recupera appena torna acceso invece di saltare un mese intero —
    e più indietro no, perché un resoconto di due mesi fa non lo legge nessuno.
    """
    primo = adesso.date().replace(day=1)
    scorso = (primo - timedelta(days=1)).replace(day=1)
    for candidato in (scorso, (scorso - timedelta(days=1)).replace(day=1)):
        fine = _primo_del_mese_dopo(candidato)
        if adesso >= datetime.combine(fine, time(hour=ore, minute=minuti)):
            return candidato
    return None


def _primo_del_mese_dopo(primo: date) -> date:
    return (primo.replace(day=28) + timedelta(days=4)).replace(day=1)
