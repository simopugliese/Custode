"""Il job settimanale per intero, su un database vero (§8.4 punto 7).

Non c'è nessun orologio: `esegui` prende la settimana e `adesso` come
parametri, e il ciclo del worker li calcola con `pianificazione`, provata a
parte. Qui si verifica cosa il job legge, cosa scrive e cosa manda.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from custode_core.dominio import diario as dom_diario
from custode_core.dominio import profilo as dom_profilo
from custode_router.errori import ProviderNonRaggiungibile
from custode_worker import settimanale
from custode_worker.pianificazione import (
    RIEPILOGO_SETTIMANALE,
    gia_eseguito,
    segna_eseguito,
)

pytestmark = pytest.mark.integration

# `ora` è lunedì 31 agosto 2026: la settimana che comincia quel giorno.
LUNEDI = date(2026, 8, 31)


class RouterFinto:
    def __init__(self, riepilogo: str = "Una settimana passata sul capitolo 3."):
        self.riepilogo = riepilogo
        self.errore: Exception | None = None
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return {"riepilogo": self.riepilogo}


def _voce_approvata(
    conn: sqlite3.Connection, ora: datetime, giorno: date, testo: str
) -> dom_diario.Voce:
    voce, _ = dom_diario.aggiungi_materiale(conn, giorno=giorno, testo="materiale", ora=ora)
    dom_diario.proponi(conn, voce.id, riassunto=testo, tag=["studio"])
    return dom_diario.approva(conn, voce.id, ora)


def _candidato(conn: sqlite3.Connection, ora: datetime, estratto: str) -> dom_profilo.Candidato:
    return dom_profilo.aggiungi_candidato(
        conn, messaggio_origine="un messaggio", estratto=estratto, ora=ora
    )


def _esegui(
    conn: sqlite3.Connection, ora: datetime, router: RouterFinto | None = None
) -> settimanale.Esito:
    return settimanale.esegui(
        conn,
        ora,
        lunedi=LUNEDI,
        router=router or RouterFinto(),  # type: ignore[arg-type]
    )


# — settimana vuota —


def test_una_settimana_senza_niente_non_manda_niente(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Un messaggio automatico che dice «non ho niente da dirti» è solo rumore."""
    router = RouterFinto()

    esito = _esegui(conn, ora, router)

    assert esito.messaggio is None
    assert esito.voci_lette == 0
    assert router.chiamate == []  # nessuna chiamata a Claude per il vuoto


# — il riepilogo —


def test_legge_solo_le_voci_approvate_della_settimana(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _voce_approvata(conn, ora, LUNEDI, "Lunedì sul capitolo 3.")
    _voce_approvata(conn, ora, LUNEDI + timedelta(days=2), "Mercoledì in palestra.")
    # Fuori settimana: non deve entrare.
    _voce_approvata(conn, ora, LUNEDI - timedelta(days=1), "Domenica scorsa.")
    # Solo una bozza: non è diario, non entra (§8.4).
    bozza, _ = dom_diario.aggiungi_materiale(
        conn, giorno=LUNEDI + timedelta(days=3), testo="materiale", ora=ora
    )
    dom_diario.proponi(conn, bozza.id, riassunto="Non approvata.", tag=[])

    router = RouterFinto()
    esito = _esegui(conn, ora, router)

    assert esito.voci_lette == 2
    utente = router.chiamate[0]["utente"]
    assert "Lunedì sul capitolo 3." in utente
    assert "Mercoledì in palestra." in utente
    assert "Domenica scorsa." not in utente
    assert "Non approvata." not in utente


def test_il_riepilogo_si_salva_e_finisce_nel_messaggio(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _voce_approvata(conn, ora, LUNEDI, "Lunedì sul capitolo 3.")

    esito = _esegui(conn, ora, RouterFinto("Hai passato la settimana sul capitolo 3."))

    assert esito.riepilogo_scritto is True
    assert esito.messaggio is not None
    assert "Hai passato la settimana sul capitolo 3." in esito.messaggio.testo
    salvato = dom_diario.riepilogo(conn, LUNEDI)
    assert salvato is not None and salvato.testo == "Hai passato la settimana sul capitolo 3."


def test_un_riepilogo_gia_scritto_non_si_rifa(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il riepilogo di una settimana chiusa non cambia: richiamarlo è spesa."""
    _voce_approvata(conn, ora, LUNEDI, "Lunedì.")
    dom_diario.salva_riepilogo(conn, settimana_inizio=LUNEDI, testo="Già scritto.", ora=ora)

    router = RouterFinto()
    esito = _esegui(conn, ora, router)

    assert router.chiamate == []
    assert esito.messaggio is not None and "Già scritto." in esito.messaggio.testo


def test_se_claude_non_risponde_la_revisione_va_avanti_lo_stesso(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Riepilogo e revisione sono indipendenti: perderli entrambi è sproporzionato."""
    _voce_approvata(conn, ora, LUNEDI, "Lunedì.")
    _candidato(conn, ora, "Preferisce il backend")
    router = RouterFinto()
    router.errore = ProviderNonRaggiungibile("giù")

    esito = _esegui(conn, ora, router)

    assert esito.riepilogo_scritto is False
    assert esito.errore is not None
    assert esito.messaggio is not None
    assert "Preferisce il backend" in esito.messaggio.testo
    # E il riepilogo non è stato salvato a metà.
    assert dom_diario.riepilogo(conn, LUNEDI) is None


# — la revisione dei candidati —


def test_i_candidati_arrivano_con_i_loro_bottoni(conn: sqlite3.Connection, ora: datetime) -> None:
    _candidato(conn, ora, "Preferisce il backend")
    _candidato(conn, ora, "Studia meglio la mattina")

    esito = _esegui(conn, ora)

    assert esito.candidati_da_rivedere == 2
    assert esito.messaggio is not None
    dati = [b.dato for riga in esito.messaggio.bottoni for b in riga]
    assert sum(1 for d in dati if ":scarta:" in d) == 2
    assert any("rifondi" in d for d in dati)


def test_riepilogo_e_revisione_nello_stesso_messaggio(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _voce_approvata(conn, ora, LUNEDI, "Lunedì.")
    _candidato(conn, ora, "Preferisce il backend")

    esito = _esegui(conn, ora, RouterFinto("La settimana è andata così."))

    assert esito.messaggio is not None
    testo = esito.messaggio.testo
    assert "La tua settimana" in testo
    assert "La settimana è andata così." in testo
    assert "Da mettere nel profilo" in testo


def test_i_candidati_gia_rifusi_non_ricompaiono(conn: sqlite3.Connection, ora: datetime) -> None:
    _candidato(conn, ora, "Vecchio segnale")
    approvati = dom_profilo.approva_rimanenti(conn)
    dom_profilo.salva_versione(conn, testo="Prima versione.", ora=ora, candidati=approvati)

    esito = _esegui(conn, ora)

    assert esito.candidati_da_rivedere == 0
    assert esito.messaggio is None


# — il registro delle esecuzioni —


def test_il_registro_impedisce_di_rifare_la_settimana(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Anche quando il job non ha prodotto niente: senza, riproverebbe per sempre."""
    assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI) is False
    _esegui(conn, ora)
    segna_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI, ora)
    assert gia_eseguito(conn, RIEPILOGO_SETTIMANALE, LUNEDI) is True
