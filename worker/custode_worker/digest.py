"""Il digest mattutino (ARCHITECTURE.md §8.13).

Una volta la mattina: gli impegni del giorno dal calendario, il meteo dove sei,
i task aperti e le abitudini che oggi vanno fatte per non mancare il target.

**Il codice calcola, il modello scrive.** Orari, scadenze, aderenza, soglia
dell'ombrello e il «dove sei» sono tutti già decisi quando si arriva al
modello (§6: composizione, DeepSeek). Il testo di base è costruito dal codice
ed è sempre pronto: il modello lo *riscrive* in una prosa più naturale, e se
risponde male — o non c'è la chiave — si manda quello di base. Un digest che
non parte perché DeepSeek è lento sarebbe peggio di uno meno elegante.

**Quando manca un pezzo si omette e si dice** (stesso criterio di §8.12): senza
posizione niente meteo, e non «non piove»; con Open-Meteo giù lo stesso; con il
calendario scollegato, una nota. Una sezione vuota *perché non c'è niente* (nessun
task) si omette in silenzio: tacere sul non so e tacere sul non c'è sono due cose.

Non manda niente e non segna niente: prepara il messaggio e lo ritorna, come il
riepilogo settimanale, così tutto il ragionamento si prova senza rete.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from custode_bot import risposte
from custode_core.dominio import abitudini as dom_abitudini
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import meteo as dom_meteo
from custode_core.dominio import task as dom_task
from custode_core.formato import etichetta_data_lunga, etichetta_ora, etichetta_scadenza, plurale
from custode_meteo import MeteoNonRaggiungibile, SorgenteMeteo
from custode_meteo.testo import descrizione, emoji, frase_ombrello
from custode_router import Router
from custode_router import digest as router_digest
from custode_router.compiti import Compito
from custode_router.errori import ErroreRouter

log = logging.getLogger("custode.worker")

# Righe per sezione: il digest si legge in un colpo d'occhio, e il resto sta
# nell'elenco dei task.
MAX_RIGHE = 8

PROSSIMI_GIORNI = 3

NOTA_NON_SO_DOVE_SEI = "Non so dove sei, quindi niente meteo."
NOTA_METEO_GIU = "Il meteo non risponde adesso: riprova con /meteo fra poco."
NOTA_CALENDARIO_SCOLLEGATO = "Non ho il calendario: non è collegato."


@dataclass(frozen=True)
class Esito:
    messaggio: risposte.Risposta | None
    """Cosa mandare. `None` = non c'è niente di vero da dire, e non si manda."""

    con_modello: bool = False
    """Se il testo l'ha scritto il modello o è quello di base."""

    errore: str | None = None


@dataclass
class _Fatti:
    """I pezzi del digest, già calcolati."""

    righe: list[str] = field(default_factory=list)
    obbligatori: list[str] = field(default_factory=list)
    contenuti: int = 0
    note: list[str] = field(default_factory=list)
    da_segnare: list[dom_task.Task] = field(default_factory=list)


def _impegni(conn: sqlite3.Connection, ora: datetime, configurato: bool, fatti: _Fatti) -> None:
    if not configurato:
        fatti.note.append(NOTA_CALENDARIO_SCOLLEGATO)
        return
    oggi = ora.date()
    eventi = dom_calendario.del_giorno(conn, oggi)
    if not eventi:
        vuota = dom_calendario.nota_giornata_vuota(conn)
        if vuota == dom_calendario.NON_ANCORA_SINCRONIZZATO:
            # Non sappiamo se la giornata è libera: lo si dice, non si indovina.
            fatti.note.append(vuota)
        else:
            fatti.righe.append("Nessun impegno oggi.")
        return

    fatti.righe.append("Impegni di oggi:")
    for e in eventi[:MAX_RIGHE]:
        if e.tutto_il_giorno:
            fatti.righe.append(f"{e.titolo} (tutto il giorno)")
            fatti.obbligatori.append(e.titolo)
        elif e.inizio.date() < oggi:
            # Cominciato prima di oggi: l'ora d'inizio è di un altro giorno.
            fatti.righe.append(f"{e.titolo} (in corso)")
            fatti.obbligatori.append(e.titolo)
        else:
            quando = etichetta_ora(e.inizio)
            fatti.righe.append(f"{quando} {e.titolo}")
            fatti.obbligatori += [quando, e.titolo]
    if len(eventi) > MAX_RIGHE:
        fatti.righe.append(f"…e altri {len(eventi) - MAX_RIGHE}")
    fatti.contenuti += 1


def _meteo(
    conn: sqlite3.Connection,
    ora: datetime,
    sorgente: SorgenteMeteo,
    casa: tuple[float, float] | None,
    fuso: str,
    fatti: _Fatti,
) -> None:
    dove = dom_meteo.punto(conn, casa, ora)
    if dove is None:
        fatti.note.append(NOTA_NON_SO_DOVE_SEI)
        return
    lat, lon, posizione = dove
    try:
        previsioni = sorgente.previsioni(lat, lon, 1, fuso)
    except MeteoNonRaggiungibile:
        fatti.note.append(NOTA_METEO_GIU)
        return
    oggi = next((p for p in previsioni if p.giorno == ora.date()), None)
    if oggi is None:
        fatti.note.append(NOTA_METEO_GIU)
        return

    riga = (
        f"Meteo: {emoji(oggi.codice)} {descrizione(oggi.codice)},"
        f" {round(oggi.minima)}–{round(oggi.massima)}°"
    )
    if oggi.prob_pioggia is not None:
        riga += f", pioggia {oggi.prob_pioggia}%"
    if posizione:
        riga += f" ({posizione})"
    fatti.righe.append(riga)
    consiglio = frase_ombrello(oggi.prob_pioggia, dom_meteo.prossimo_impegno(conn, ora))
    if consiglio:
        fatti.righe.append(consiglio)
        fatti.obbligatori.append(consiglio)
    fatti.contenuti += 1


def _riga_task(task: dom_task.Task, ora: datetime) -> str:
    etichetta = etichetta_scadenza(task.scadenza, ora)
    return f"{task.titolo} ({etichetta})" if etichetta else task.titolo


def _task(conn: sqlite3.Connection, ora: datetime, fatti: _Fatti) -> None:
    oggi = ora.date()
    aperti = dom_task.elenco(conn, fatto=False)
    sezioni = (
        ("In ritardo", [t for t in aperti if dom_task.in_ritardo(t, oggi)], True),
        ("Per oggi", [t for t in aperti if dom_task.per_oggi(t, oggi)], True),
        (
            f"Nei prossimi {PROSSIMI_GIORNI} giorni",
            [t for t in aperti if dom_task.entro_giorni(t, oggi, PROSSIMI_GIORNI)],
            False,
        ),
    )
    for titolo, elenco, con_bottone in sezioni:
        if not elenco:
            continue
        fatti.righe.append(f"{titolo}:")
        for t in elenco[:MAX_RIGHE]:
            fatti.righe.append(_riga_task(t, ora))
            fatti.obbligatori.append(t.titolo)
            if con_bottone:
                fatti.da_segnare.append(t)
        if len(elenco) > MAX_RIGHE:
            fatti.righe.append(f"…e altri {len(elenco) - MAX_RIGHE}")
        fatti.contenuti += 1

    senza = sum(1 for t in aperti if t.scadenza is None)
    if senza:
        fatti.righe.append(f"Senza scadenza: {plurale(senza, 'task aperto', 'task aperti')}.")


def _abitudini(conn: sqlite3.Connection, ora: datetime, fatti: _Fatti) -> None:
    a_rischio = dom_abitudini.da_non_perdere(conn, ora.date())
    if not a_rischio:
        return
    fatti.righe.append("Abitudini da non perdere:")
    for a in a_rischio:
        giorni = plurale(a.giorni_rimasti, "giorno", "giorni")
        fatti.righe.append(f"{a.nome}: {a.fatte}/{a.target} questa settimana, ti restano {giorni}")
        fatti.obbligatori.append(a.nome)
    fatti.contenuti += 1


def _testo_di_base(fatti: _Fatti) -> str:
    corpo = "\n".join(fatti.righe)
    if fatti.note:
        corpo += "\n\n" + "\n".join(fatti.note)
    return corpo


def esegui(
    conn: sqlite3.Connection,
    ora: datetime,
    *,
    router: Router,
    sorgente_meteo: SorgenteMeteo,
    casa: tuple[float, float] | None,
    fuso: str,
    calendario_configurato: bool,
) -> Esito:
    """Compone il digest di oggi. Non manda e non segna niente."""
    fatti = _Fatti()
    _impegni(conn, ora, calendario_configurato, fatti)
    _meteo(conn, ora, sorgente_meteo, casa, fuso, fatti)
    _task(conn, ora, fatti)
    _abitudini(conn, ora, fatti)

    if not fatti.contenuti:
        # Solo note e «nessun impegno»: un messaggio che dice «non ho niente» è
        # una notifica sprecata, come per il riepilogo settimanale.
        return Esito(messaggio=None)

    testo = _testo_di_base(fatti)
    obbligatori = fatti.obbligatori + fatti.note
    con_modello = False
    errore: str | None = None
    if router.configurato_per(Compito.DIGEST_MATTUTINO):
        try:
            testo = router_digest.componi(
                router, [*fatti.righe, *fatti.note], obbligatori=obbligatori
            )
            con_modello = True
        except ErroreRouter as guasto:
            # Il digest esce lo stesso, col testo del codice.
            errore = str(guasto)
            log.warning(
                "digest: il modello non ha dato un testo buono, uso quello di base: %s", guasto
            )

    messaggio = risposte.digest_mattutino(testo, fatti.da_segnare, etichetta_data_lunga(ora))
    return Esito(messaggio=messaggio, con_modello=con_modello, errore=errore)
