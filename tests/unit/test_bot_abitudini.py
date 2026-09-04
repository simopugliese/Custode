"""`/abitudini` su Telegram (§8.6).

§8.6 vuole l'aderenza «sia in dashboard che a richiesta via bot»: qui si
verifica che il bot legga gli stessi numeri della pagina — dalle stesse
funzioni di dominio — e che il tap su un bottone si comporti come una spunta,
non come una dichiarazione di fallimento.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from custode_bot import azioni, risposte
from custode_core.dominio import abitudini as dom


def _crea(conn: sqlite3.Connection, ora: datetime, nome: str, target: int = 3) -> dom.Abitudine:
    return dom.crea(conn, nome=nome, target_settimanale=target, ora=ora)


def test_senza_abitudini_dice_dove_si_aggiungono(conn: sqlite3.Connection, ora: datetime) -> None:
    risposta = risposte.elenco_abitudini(conn, ora)
    assert "Non segui ancora nessuna abitudine" in risposta.testo
    assert "dashboard" in risposta.testo
    assert risposta.bottoni == []


def test_l_elenco_mostra_l_aderenza_della_settimana(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    palestra = _crea(conn, ora, "Palestra", 3)
    _crea(conn, ora, "Lettura", 5)
    dom.segna(conn, palestra.id, giorno=ora.date(), fatto=True, ora=ora)

    testo = risposte.elenco_abitudini(conn, ora).testo

    assert "Palestra" in testo and "1/3" in testo
    assert "Lettura" in testo and "0/5" in testo
    # Segnata oggi e non segnata si distinguono a colpo d'occhio.
    assert "✅" in testo and "▫️" in testo


def test_la_striscia_compare_quando_c_e(conn: sqlite3.Connection, ora: datetime) -> None:
    palestra = _crea(conn, ora, "Palestra")
    for scarto in range(3):
        dom.segna(
            conn, palestra.id, giorno=ora.date() - timedelta(days=scarto), fatto=True, ora=ora
        )
    assert "3 giorni di fila" in risposte.elenco_abitudini(conn, ora).testo


def test_un_tap_segna_oggi(conn: sqlite3.Connection, ora: datetime) -> None:
    palestra = _crea(conn, ora, "Palestra")
    dato = azioni.abitudine("oggi", palestra.id)

    risposta = risposte.esegui_azione(conn, ora, dato)

    assert dom.segnata(conn, palestra.id, ora.date()) is True
    # La risposta è l'elenco aggiornato: si vede subito l'effetto del tap.
    assert "✅" in risposta.testo


def test_un_secondo_tap_toglie_invece_di_scrivere_non_fatta(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Un tap per sbaglio deve riportare al silenzio, non affermare il contrario."""
    palestra = _crea(conn, ora, "Palestra")
    dom.segna(conn, palestra.id, giorno=ora.date(), fatto=True, ora=ora)

    risposte.esegui_azione(conn, ora, azioni.abitudine("oggi", palestra.id))

    assert dom.segnata(conn, palestra.id, ora.date()) is None


def test_il_tap_su_un_abitudine_sparita_non_esplode(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    risposta = risposte.esegui_azione(conn, ora, azioni.abitudine("oggi", 999))
    assert "non c'è più" in risposta.testo


def test_il_resoconto_recente_si_attacca_all_elenco(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _crea(conn, ora, "Palestra")
    dom.salva_report(
        conn,
        periodo=dom.Periodo.SETTIMANA,
        chiave=ora.date(),
        testo="Settimana solida.",
        ora=ora,
    )
    assert "Settimana solida." in risposte.elenco_abitudini(conn, ora).testo


def test_un_resoconto_vecchio_non_si_ripropone(conn: sqlite3.Connection, ora: datetime) -> None:
    """Riproporlo ad ogni `/abitudini` lo svuoterebbe di significato."""
    _crea(conn, ora, "Palestra")
    dom.salva_report(
        conn,
        periodo=dom.Periodo.SETTIMANA,
        chiave=ora.date() - timedelta(days=28),
        testo="Un mese fa.",
        ora=ora,
    )
    assert "Un mese fa." not in risposte.elenco_abitudini(conn, ora).testo
