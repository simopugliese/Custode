"""Candidati e profilo sul database: raccolta, chiarimento, revisione, versioni.

Il punto di §8.4 che questi test difendono: il profilo si **riscrive**, non si
accoda, e ogni riscrittura si può disfare senza perdere il materiale che l'aveva
prodotta.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from custode_core.dominio import profilo as dom


def _candidato(
    conn: sqlite3.Connection, ora: datetime, estratto: str, **extra: object
) -> dom.Candidato:
    return dom.aggiungi_candidato(
        conn,
        messaggio_origine=f"messaggio su «{estratto}»",
        estratto=estratto,
        ora=ora,
        **extra,  # type: ignore[arg-type]
    )


# — raccolta —


def test_un_segnale_chiaro_entra_in_silenzio(conn: sqlite3.Connection, ora: datetime) -> None:
    candidato = _candidato(conn, ora, "Preferisce il backend")

    assert candidato.stato is dom.Stato.IN_CODA
    assert candidato.chiarimento_domanda is None
    # Nessuna domanda in sospeso: la chat non è stata interrotta.
    assert dom.in_chiarimento(conn) is None


def test_un_segnale_ambiguo_nasce_con_la_sua_domanda(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _candidato(conn, ora, "Odia il frontend", domanda="Vale sempre o era la giornata?")

    attesa = dom.in_chiarimento(conn)
    assert attesa is not None
    assert attesa.chiarimento_domanda == "Vale sempre o era la giornata?"


def test_un_estratto_vuoto_e_un_errore(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(ValueError):
        _candidato(conn, ora, "   ")


# — chiarimento —


def test_un_si_lo_rende_un_segnale_vero(conn: sqlite3.Connection, ora: datetime) -> None:
    candidato = _candidato(conn, ora, "Odia il frontend", domanda="Vale sempre?")

    chiarito = dom.chiarisci(conn, candidato.id, risposta="vale in generale", vale=True)

    assert chiarito.stato is dom.Stato.CHIARITO
    assert chiarito.chiarimento_risposta == "vale in generale"
    assert dom.in_chiarimento(conn) is None  # non chiede più
    assert [c.id for c in dom.da_rivedere(conn)] == [candidato.id]


def test_un_no_lo_scarta_subito(conn: sqlite3.Connection, ora: datetime) -> None:
    """Tenerlo in coda vorrebbe dire richiedertelo alla revisione settimanale."""
    candidato = _candidato(conn, ora, "Odia il frontend", domanda="Vale sempre?")

    dom.chiarisci(conn, candidato.id, risposta="era il momento", vale=False)

    assert dom.leggi_candidato(conn, candidato.id).stato is dom.Stato.SCARTATO
    assert dom.da_rivedere(conn) == []


# — revisione settimanale —


def test_la_revisione_funziona_per_sottrazione(conn: sqlite3.Connection, ora: datetime) -> None:
    tenuto = _candidato(conn, ora, "Preferisce il backend")
    buttato = _candidato(conn, ora, "Odia tutto")

    dom.scarta_candidato(conn, buttato.id)
    approvati = dom.approva_rimanenti(conn)

    assert [c.id for c in approvati] == [tenuto.id]
    assert dom.leggi_candidato(conn, buttato.id).stato is dom.Stato.SCARTATO
    assert dom.da_rivedere(conn) == []


def test_i_candidati_gia_rifusi_non_tornano_nella_revisione(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Altrimenti ogni settimana il modello rileggerebbe tutta la storia."""
    candidato = _candidato(conn, ora, "Preferisce il backend")
    approvati = dom.approva_rimanenti(conn)
    dom.salva_versione(conn, testo="Prima versione.", ora=ora, candidati=approvati)

    assert dom.da_rivedere(conn) == []
    assert dom.approvati(conn) == []
    assert dom.leggi_candidato(conn, candidato.id).versione_profilo == 1


# — versioni del profilo —


def test_la_prima_versione(conn: sqlite3.Connection, ora: datetime) -> None:
    assert dom.corrente(conn) is None
    assert dom.testo_corrente(conn) is None

    versione = dom.salva_versione(conn, testo="  Preferisce il backend.  ", ora=ora, candidati=[])

    assert versione.versione == 1
    assert versione.testo == "Preferisce il backend."
    assert dom.testo_corrente(conn) == "Preferisce il backend."


def test_le_versioni_si_accumulano_ma_il_profilo_e_uno(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Il documento si riscrive; la storia resta, ed è la rete di sicurezza."""
    dom.salva_versione(conn, testo="Prima.", ora=ora, candidati=[])
    dom.salva_versione(conn, testo="Seconda.", ora=ora, candidati=[])

    assert dom.testo_corrente(conn) == "Seconda."
    assert [v.versione for v in dom.versioni(conn)] == [2, 1]


def test_un_profilo_vuoto_e_un_errore(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(ValueError):
        dom.salva_versione(conn, testo="   ", ora=ora, candidati=[])


# — tornare indietro —


def test_tornare_indietro_rimette_le_cose_com_erano(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    dom.salva_versione(conn, testo="Prima.", ora=ora, candidati=[])
    candidato = _candidato(conn, ora, "Preferisce il backend")
    approvati = dom.approva_rimanenti(conn)
    dom.salva_versione(conn, testo="Seconda.", ora=ora, candidati=approvati)

    tornata = dom.torna_indietro(conn)

    assert tornata is not None and tornata.testo == "Prima."
    assert [v.versione for v in dom.versioni(conn)] == [1]
    # Il materiale non si perde: rientra nella prossima rifusione.
    ancora = dom.leggi_candidato(conn, candidato.id)
    assert ancora.versione_profilo is None
    assert ancora.stato is dom.Stato.APPROVATO
    assert [c.id for c in dom.approvati(conn)] == [candidato.id]


def test_tornare_indietro_dalla_prima_versione_lascia_il_profilo_vuoto(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    dom.salva_versione(conn, testo="Prima.", ora=ora, candidati=[])

    assert dom.torna_indietro(conn) is None
    assert dom.corrente(conn) is None


def test_tornare_indietro_senza_profilo(conn: sqlite3.Connection, ora: datetime) -> None:
    assert dom.torna_indietro(conn) is None


def test_dopo_essere_tornati_indietro_la_versione_si_rifa(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """La numerazione riparte da dov'era: non restano buchi né doppioni."""
    dom.salva_versione(conn, testo="Prima.", ora=ora, candidati=[])
    dom.salva_versione(conn, testo="Sbagliata.", ora=ora, candidati=[])
    dom.torna_indietro(conn)

    rifatta = dom.salva_versione(conn, testo="Giusta.", ora=ora, candidati=[])

    assert rifatta.versione == 2
    assert dom.testo_corrente(conn) == "Giusta."


def test_id_inesistente(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.CandidatoInesistente):
        dom.leggi_candidato(conn, 999)
