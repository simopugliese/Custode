"""I nomi che vanno a Whisper come prompt (§8.1).

È una funzione pura di lettura: qui si verifica cosa raccoglie, in che ordine,
e che il taglio in coda non lasci mai una frase a metà.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from custode_core.dominio import abitudini as dom_abitudini
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import spese as dom_spese
from custode_core.dominio import task as dom_task
from custode_core.dominio import vocabolario


def test_un_installazione_appena_avviata_non_suggerisce_niente(
    conn: sqlite3.Connection,
) -> None:
    """Meglio nessun prompt che uno che promette parole inesistenti."""
    assert vocabolario.nomi(conn) == []
    assert vocabolario.suggerimento(conn) == ""


def test_raccoglie_i_nomi_dei_moduli_che_contano(conn: sqlite3.Connection, ora: datetime) -> None:
    dom_abitudini.crea(conn, nome="Meditazione", target_settimanale=3, ora=ora)
    dom_spese.assicura_categoria(conn, "Bricoman", ora)
    dom_lista.aggiungi(conn, nome="carta forno", ora=ora, reparto="Casalinghi")
    dom_task.crea(conn, titolo="Chiamare l'officina", ora=ora)

    raccolti = vocabolario.nomi(conn)

    assert "Meditazione" in raccolti
    assert "Bricoman" in raccolti
    assert "Casalinghi" in raccolti
    assert "carta forno" in raccolti
    assert "Chiamare l'officina" in raccolti


def test_le_abitudini_vengono_prima_dei_task(conn: sqlite3.Connection, ora: datetime) -> None:
    """L'ordine è quello del taglio: si perde prima il titolo lungo di un task."""
    dom_task.crea(conn, titolo="Chiamare l'officina", ora=ora)
    dom_abitudini.crea(conn, nome="Meditazione", target_settimanale=3, ora=ora)

    raccolti = vocabolario.nomi(conn)

    assert raccolti.index("Meditazione") < raccolti.index("Chiamare l'officina")


def test_una_voce_gia_presa_non_conta(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il vocabolario è quello di adesso: ciò che hai già comprato non lo dirai."""
    voce = dom_lista.aggiungi(conn, nome="carta forno", ora=ora)
    dom_lista.imposta_preso(conn, voce.id, True, ora)
    assert "carta forno" not in vocabolario.nomi(conn)


def test_un_task_gia_fatto_non_conta(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="Chiamare l'officina", ora=ora)
    dom_task.imposta_fatto(conn, task.id, True, ora)
    assert "Chiamare l'officina" not in vocabolario.nomi(conn)


def test_un_abitudine_spenta_non_conta(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = dom_abitudini.crea(conn, nome="Meditazione", target_settimanale=3, ora=ora)
    dom_abitudini.modifica(conn, abitudine.id, attiva=False)
    assert "Meditazione" not in vocabolario.nomi(conn)


def test_niente_ripetizioni_nemmeno_di_maiuscola(conn: sqlite3.Connection, ora: datetime) -> None:
    """Ripetere una parola non la rende più probabile: toglie posto a un'altra."""
    dom_abitudini.crea(conn, nome="Palestra", target_settimanale=3, ora=ora)
    dom_spese.assicura_categoria(conn, "palestra", ora)

    raccolti = [n.casefold() for n in vocabolario.nomi(conn)]

    assert raccolti.count("palestra") == 1


def test_il_suggerimento_e_una_frase(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il prompt di Whisper è testo, non un elenco puntato: lo tratta come discorso."""
    dom_abitudini.crea(conn, nome="Meditazione", target_settimanale=3, ora=ora)
    dom_spese.assicura_categoria(conn, "Bricoman", ora)

    frase = vocabolario.suggerimento(conn)

    assert frase.endswith(".")
    assert frase == "Meditazione, Bricoman."


def test_il_suggerimento_sta_dentro_il_tetto(conn: sqlite3.Connection, ora: datetime) -> None:
    """Un prompt lungo viene tagliato da whisper.cpp e mette parole in bocca."""
    for i in range(120):
        dom_task.crea(conn, titolo=f"Un titolo di task piuttosto lungo numero {i}", ora=ora)

    frase = vocabolario.suggerimento(conn)

    assert len(frase) <= vocabolario.MASSIMO_CARATTERI
    # E si taglia fra un nome e l'altro, mai a metà parola.
    assert all(pezzo.strip() for pezzo in frase.rstrip(".").split(","))
    assert "numero" in frase


def test_un_nome_piu_lungo_del_tetto_non_produce_una_frase_monca(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    dom_task.crea(conn, titolo="x" * (vocabolario.MASSIMO_CARATTERI + 50), ora=ora)
    assert vocabolario.suggerimento(conn) == ""
