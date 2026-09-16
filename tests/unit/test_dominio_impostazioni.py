"""Le impostazioni modificabili a caldo (ARCHITECTURE.md §8).

Quello che conta qui non è che un valore si salvi — quello lo fa qualunque
tabella — ma **quando il `.env` conta ancora e quando smette**: è la differenza
fra un'installazione che riparte con la sua configurazione e una seconda fonte
di verità che nessuno sa più quale delle due vinca.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from custode_core.dominio import impostazioni as dom

ORA = datetime(2026, 9, 16, 9, 30)


# — il `.env` come punto di partenza —


def test_senza_riga_vale_il_default_di_chi_legge(conn: sqlite3.Connection) -> None:
    """È il `.env`: la configurazione con cui l'installazione è nata."""
    assert dom.BUDGET_SETTIMANALE.leggi(conn, default=120.0) == 120.0
    assert dom.RIEPILOGO_GIORNO.leggi(conn, default="lunedi") == "lunedi"


def test_senza_riga_e_senza_env_vale_il_default_del_registro(conn: sqlite3.Connection) -> None:
    """L'ultima spiaggia: un'installazione che non ha scelto niente, da nessuna parte."""
    assert dom.BUDGET_SETTIMANALE.leggi(conn) is None
    assert dom.RIEPILOGO_GIORNO.leggi(conn) == "domenica"
    assert dom.CHECK_IN_MINUTI_DOPO.leggi(conn) == 40


def test_dal_primo_salvataggio_il_env_smette_di_contare(conn: sqlite3.Connection) -> None:
    """Il punto di tutta la scelta: una fonte di verità sola, e si sa quale."""
    dom.BUDGET_SETTIMANALE.scrivi(conn, 80, ORA)

    # Anche passando il valore del `.env`, vince quello che hai scelto tu.
    assert dom.BUDGET_SETTIMANALE.leggi(conn, default=120.0) == 80.0


def test_salvare_null_e_una_scelta_non_un_ripensamento(conn: sqlite3.Connection) -> None:
    """Svuotare il budget deve **spegnere** il blocco spese, non riesumare il `.env`.

    Se un `null` cancellasse la riga, il valore del `.env` tornerebbe a valere e
    al ricaricamento successivo il budget ricomparirebbe: la pagina rifiuterebbe
    in silenzio la cosa che le hai appena chiesto.
    """
    dom.BUDGET_SETTIMANALE.scrivi(conn, None, ORA)

    assert dom.BUDGET_SETTIMANALE.leggi(conn, default=120.0) is None
    assert "budget_settimanale" in dom.salvate(conn)


def test_salvate_dice_cosa_hai_deciso_tu(conn: sqlite3.Connection) -> None:
    assert dom.salvate(conn) == {}

    dom.CHECK_IN_MINUTI_DOPO.scrivi(conn, 25, ORA)

    assert dom.salvate(conn) == {"check_in_minuti_dopo": ORA}


def test_riscrivere_aggiorna_invece_di_accodare(conn: sqlite3.Connection) -> None:
    dom.CHECK_IN_MINUTI_DOPO.scrivi(conn, 25, ORA)
    dom.CHECK_IN_MINUTI_DOPO.scrivi(conn, 45, datetime(2026, 9, 17, 8, 0))

    assert dom.CHECK_IN_MINUTI_DOPO.leggi(conn) == 45
    assert conn.execute("SELECT count(*) AS n FROM impostazioni").fetchone()["n"] == 1


# — una riga storta non deve fermare niente —


def test_una_riga_illeggibile_vale_come_assente(conn: sqlite3.Connection) -> None:
    """Scritta a mano con sqlite3, o rimasta da una versione che voleva altro.

    Sollevare qui vorrebbe dire una pagina che non si apre — o, peggio, un
    worker che muore ad ogni giro — per una riga che si sistema sovrascrivendola.
    """
    conn.execute(
        "INSERT INTO impostazioni (chiave, valore, aggiornato_il) VALUES (?, ?, ?)",
        ("check_in_minuti_dopo", "non è json", ORA.isoformat()),
    )
    assert dom.CHECK_IN_MINUTI_DOPO.leggi(conn, default=30) == 30

    conn.execute(
        "UPDATE impostazioni SET valore = ? WHERE chiave = ?", ("99999", "check_in_minuti_dopo")
    )
    assert dom.CHECK_IN_MINUTI_DOPO.leggi(conn, default=30) == 30


# — i controlli —


@pytest.mark.parametrize("valore", [0, -10, "zero", True, 2_000_000])
def test_un_budget_assurdo_si_rifiuta(conn: sqlite3.Connection, valore: object) -> None:
    with pytest.raises(dom.ValoreNonValido):
        dom.BUDGET_SETTIMANALE.scrivi(conn, valore, ORA)


def test_un_budget_si_scrive_anche_con_la_virgola(conn: sqlite3.Connection) -> None:
    """È come lo si digita in italiano, e il campo della pagina manda testo."""
    assert dom.BUDGET_SETTIMANALE.scrivi(conn, "85,50", ORA) == 85.50


def test_un_budget_vuoto_vale_nessun_budget(conn: sqlite3.Connection) -> None:
    """Un campo di testo svuotato a mano manda una stringa vuota, non `null`."""
    assert dom.BUDGET_SETTIMANALE.scrivi(conn, "  ", ORA) is None


@pytest.mark.parametrize("valore", [-1, 721, "mezz'ora", True])
def test_un_margine_assurdo_si_rifiuta(conn: sqlite3.Connection, valore: object) -> None:
    """Mezza giornata è il tetto: un margine di due giorni non è un margine,
    è un promemoria che non arriva più e non si capisce perché."""
    with pytest.raises(dom.ValoreNonValido):
        dom.CHECK_IN_MINUTI_DOPO.scrivi(conn, valore, ORA)


@pytest.mark.parametrize("valore", ["sabato", "", "Lunedì", 1])
def test_un_giorno_inventato_si_rifiuta(conn: sqlite3.Connection, valore: object) -> None:
    with pytest.raises(dom.ValoreNonValido):
        dom.RIEPILOGO_GIORNO.scrivi(conn, valore, ORA)


@pytest.mark.parametrize(
    ("dentro", "fuori"), [("9:5", "09:05"), ("21:00", "21:00"), (" 7:30 ", "07:30")]
)
def test_un_orario_si_normalizza(conn: sqlite3.Connection, dentro: str, fuori: str) -> None:
    """«9:5» salvato una volta si rileggerebbe storto per sempre."""
    assert dom.RIEPILOGO_ORA.scrivi(conn, dentro, ORA) == fuori


@pytest.mark.parametrize("valore", ["25:00", "21:61", "sera", "21", "21:00:00"])
def test_un_orario_storto_si_rifiuta(conn: sqlite3.Connection, valore: object) -> None:
    with pytest.raises(dom.ValoreNonValido):
        dom.RIEPILOGO_ORA.scrivi(conn, valore, ORA)


def test_ore_e_minuti_rivalida(conn: sqlite3.Connection) -> None:
    assert dom.ore_e_minuti("21:00") == (21, 0)
    with pytest.raises(dom.ValoreNonValido):
        dom.ore_e_minuti("25:00")


# — il registro —


def test_una_chiave_fuori_dal_registro_non_esiste() -> None:
    """Un errore di battitura in una PATCH non deve diventare una riga muta."""
    assert dom.per_chiave("budget_settimanale") is dom.BUDGET_SETTIMANALE
    with pytest.raises(dom.ImpostazioneInesistente):
        dom.per_chiave("budget_mensile")


def test_il_registro_non_ha_chiavi_doppie() -> None:
    """Due voci con la stessa chiave si scriverebbero addosso a vicenda, e la
    seconda non si leggerebbe mai."""
    chiavi = [voce.chiave for voce in dom.REGISTRO]
    assert len(chiavi) == len(set(chiavi))


def test_ogni_voce_del_registro_accetta_il_proprio_default() -> None:
    """Un default che il suo stesso controllo rifiuta è una bomba a orologeria:
    salta la prima volta che qualcuno salva quel valore invece di un altro."""
    for voce in dom.REGISTRO:
        assert voce.valida(voce.default) == voce.default
