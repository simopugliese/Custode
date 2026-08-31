"""Regole di dominio della lista della spesa (§8.3)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from custode_core.dominio import lista_spesa as dom


def test_aggiungi_e_rileggi(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = dom.aggiungi(conn, nome="  latte  ", ora=ora, quantita="1 L", reparto="Latticini")
    assert voce.nome == "latte"
    assert voce.quantita == "1 L"
    assert voce.reparto == "Latticini"
    assert voce.preso is False


def test_senza_reparto_finisce_in_altro(conn: sqlite3.Connection, ora: datetime) -> None:
    assert dom.aggiungi(conn, nome="carta forno", ora=ora).reparto == "Altro"
    assert dom.aggiungi(conn, nome="scottex", ora=ora, reparto="   ").reparto == "Altro"


def test_nome_vuoto_rifiutato(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(ValueError):
        dom.aggiungi(conn, nome="   ", ora=ora)


def test_non_duplica_una_voce_gia_da_prendere(conn: sqlite3.Connection, ora: datetime) -> None:
    # «sto finendo il latte» detto due volte non deve produrre due righe.
    prima = dom.aggiungi(conn, nome="latte", ora=ora)
    seconda = dom.aggiungi(conn, nome="LATTE", ora=ora)
    assert seconda.id == prima.id
    assert len(dom.elenco(conn)) == 1


def test_una_voce_gia_presa_non_blocca_il_riacquisto(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    vecchia = dom.aggiungi(conn, nome="latte", ora=ora)
    dom.imposta_preso(conn, vecchia.id, True, ora)

    nuova = dom.aggiungi(conn, nome="latte", ora=ora + timedelta(days=7))
    assert nuova.id != vecchia.id
    assert len(dom.elenco(conn, preso=False)) == 1


def test_spunta_e_ripristino(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = dom.aggiungi(conn, nome="mele", ora=ora)

    presa = dom.imposta_preso(conn, voce.id, True, ora)
    assert presa.preso is True
    assert presa.comprato_il == ora

    ripristinata = dom.imposta_preso(conn, voce.id, False, ora)
    assert ripristinata.preso is False
    assert ripristinata.comprato_il is None


def test_voce_inesistente(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(dom.VoceInesistente):
        dom.imposta_preso(conn, 999, True, ora)


def test_svuota_presi_lascia_le_altre(conn: sqlite3.Connection, ora: datetime) -> None:
    presa = dom.aggiungi(conn, nome="carta forno", ora=ora)
    dom.aggiungi(conn, nome="mele", ora=ora)
    dom.imposta_preso(conn, presa.id, True, ora)

    assert dom.svuota_presi(conn) == 1
    assert [v.nome for v in dom.elenco(conn)] == ["mele"]


def test_raggruppamento_per_reparto_con_altro_in_fondo(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    dom.aggiungi(conn, nome="carta forno", ora=ora)  # Altro
    dom.aggiungi(conn, nome="mele", ora=ora, reparto="Frutta e verdura")
    dom.aggiungi(conn, nome="latte", ora=ora, reparto="Latticini")
    dom.aggiungi(conn, nome="yogurt", ora=ora, reparto="Latticini")

    gruppi = dom.per_reparto(dom.elenco(conn))
    assert [nome for nome, _ in gruppi] == ["Frutta e verdura", "Latticini", "Altro"]
    assert [v.nome for v in gruppi[1][1]] == ["latte", "yogurt"]
