"""Spese e categorie (§8.5): importi in centesimi, totali che tornano."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

import pytest

from custode_core.dominio import spese as dom

ORA = datetime(2026, 8, 31, 8, 41)
OGGI = ORA.date()


def _spesa(
    conn: sqlite3.Connection,
    centesimi: int = 800,
    descrizione: str = "colazione",
    **extra: Any,
) -> dom.Spesa:
    return dom.registra(conn, centesimi=centesimi, descrizione=descrizione, ora=ORA, **extra)


# — centesimi —————————————————————————————————————————


@pytest.mark.parametrize(
    ("euro", "centesimi"),
    [(8.0, 800), (8.15, 815), (0.01, 1), (12.999, 1300), (1234.56, 123456)],
)
def test_gli_euro_diventano_centesimi_senza_perdere_niente(euro: float, centesimi: int) -> None:
    # `int(8.15 * 100)` farebbe 814: il centesimo mancante è il motivo per cui
    # qui c'è `round` e non un troncamento.
    assert dom.in_centesimi(euro) == centesimi


def test_i_totali_di_molte_spese_tornano_al_centesimo(conn: sqlite3.Connection) -> None:
    for _ in range(100):
        _spesa(conn, centesimi=dom.in_centesimi(0.07))
    assert dom.totale(dom.elenco(conn)) == 700


def test_una_spesa_sa_dire_i_suoi_euro(conn: sqlite3.Connection) -> None:
    assert _spesa(conn, centesimi=815).euro == 8.15


# — categorie —————————————————————————————————————————


def test_la_prima_spesa_fa_nascere_la_prima_categoria(conn: sqlite3.Connection) -> None:
    assert dom.categorie(conn) == []
    _spesa(conn, categoria="Alimentari")
    assert [c.nome for c in dom.categorie(conn)] == ["Alimentari"]


def test_maiuscole_e_spazi_non_creano_un_doppione(conn: sqlite3.Connection) -> None:
    dom.assicura_categoria(conn, "Alimentari", ORA)
    dom.assicura_categoria(conn, "  alimentari ", ORA)
    dom.assicura_categoria(conn, "ALIMENTARI", ORA)
    assert len(dom.categorie(conn)) == 1


def test_una_categoria_scritta_da_te_resta_marcata_come_tua(conn: sqlite3.Connection) -> None:
    # Serve a distinguere ciò che hai deciso tu da ciò che ha proposto il
    # modello: sono due cose che si correggono con criteri diversi.
    dom.assicura_categoria(conn, "Casa", ORA, da_utente=True)
    dom.assicura_categoria(conn, "Trasporti", ORA)
    per_nome = {c.nome: c.creata_da for c in dom.categorie(conn)}
    assert per_nome == {"Casa": "utente", "Trasporti": "ia"}


def test_una_categoria_vuota_non_si_puo_creare(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        dom.assicura_categoria(conn, "   ", ORA)


def test_unire_due_categorie_sposta_le_spese_e_spegne_la_vecchia(conn: sqlite3.Connection) -> None:
    _spesa(conn, categoria="Cibo")
    _spesa(conn, categoria="Alimentari")
    cibo = dom.trova_categoria(conn, "Cibo")
    alimentari = dom.trova_categoria(conn, "Alimentari")
    assert cibo is not None and alimentari is not None

    dom.unisci_categorie(conn, cibo.id, alimentari.id)

    assert dom.per_categoria(dom.elenco(conn)) == [("Alimentari", 1600)]
    # Disattivata, non cancellata: le spese vecchie restano leggibili.
    assert [c.nome for c in dom.categorie(conn, solo_attive=True)] == ["Alimentari"]
    assert len(dom.categorie(conn)) == 2


def test_unire_una_categoria_con_se_stessa_non_fa_niente(conn: sqlite3.Connection) -> None:
    categoria = dom.assicura_categoria(conn, "Casa", ORA)
    dom.unisci_categorie(conn, categoria.id, categoria.id)
    assert [c.attiva for c in dom.categorie(conn)] == [True]


def test_rinominare_una_categoria_non_tocca_le_spese(conn: sqlite3.Connection) -> None:
    spesa = _spesa(conn, categoria="Cibo")
    categoria = dom.trova_categoria(conn, "Cibo")
    assert categoria is not None
    dom.rinomina_categoria(conn, categoria.id, "Alimentari")
    assert dom.leggi(conn, spesa.id).categoria == "Alimentari"


# — registrazione ——————————————————————————————————————


def test_una_spesa_da_testo_nasce_gia_nei_conti(conn: sqlite3.Connection) -> None:
    # §8.5: quello che dici a voce o per iscritto entra subito, e si disfa con
    # «Annulla». È la conferma preventiva a essere l'eccezione, non la regola.
    spesa = _spesa(conn)
    assert spesa.stato is dom.Stato.CONFERMATA
    assert spesa.fonte is dom.Fonte.TESTO
    assert dom.elenco(conn) == [spesa]


def test_uno_scontrino_letto_aspetta_il_tuo_si(conn: sqlite3.Connection) -> None:
    spesa = _spesa(conn, fonte=dom.Fonte.SCONTRINO, stato=dom.Stato.DA_CONFERMARE)
    # Fuori dai totali finché non è confermato: è il punto della conferma.
    assert dom.elenco(conn) == []
    assert dom.in_attesa(conn) == [spesa]


def test_confermare_uno_scontrino_lo_fa_entrare_nei_conti(conn: sqlite3.Connection) -> None:
    spesa = _spesa(conn, fonte=dom.Fonte.SCONTRINO, stato=dom.Stato.DA_CONFERMARE)
    confermata = dom.conferma(conn, spesa.id, ORA)
    assert confermata.stato is dom.Stato.CONFERMATA
    assert dom.in_attesa(conn) == []
    assert dom.totale(dom.elenco(conn)) == 800


def test_confermare_puo_correggere_la_categoria_proposta(conn: sqlite3.Connection) -> None:
    spesa = _spesa(
        conn, categoria="Alimentari", fonte=dom.Fonte.SCONTRINO, stato=dom.Stato.DA_CONFERMARE
    )
    confermata = dom.conferma(conn, spesa.id, ORA, categoria="Casa")
    assert confermata.categoria == "Casa"
    # La correzione arriva da te, e resta marcata come tua.
    casa = dom.trova_categoria(conn, "Casa")
    assert casa is not None and casa.creata_da == "utente"


def test_confermare_due_volte_e_un_errore(conn: sqlite3.Connection) -> None:
    spesa = _spesa(conn)
    with pytest.raises(ValueError):
        dom.conferma(conn, spesa.id, ORA)


def test_una_spesa_a_zero_non_si_registra(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        _spesa(conn, centesimi=0)


def test_una_spesa_senza_descrizione_non_si_registra(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        _spesa(conn, descrizione="   ")


def test_leggere_una_spesa_che_non_esiste_lo_dice(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.SpesaInesistente):
        dom.leggi(conn, 999)


def test_eliminare_una_spesa_la_toglie_dai_conti(conn: sqlite3.Connection) -> None:
    spesa = _spesa(conn)
    dom.elimina(conn, spesa.id)
    assert dom.elenco(conn) == []
    with pytest.raises(dom.SpesaInesistente):
        dom.elimina(conn, spesa.id)


def test_il_giorno_della_spesa_e_quello_che_conta(conn: sqlite3.Connection) -> None:
    # Registrata oggi, ma pagata ieri: nei totali va sotto ieri.
    spesa = _spesa(conn, giorno=date(2026, 8, 30))
    assert spesa.giorno == date(2026, 8, 30)
    assert dom.elenco(conn, da=OGGI, a=OGGI) == []


# — aggregati ——————————————————————————————————————————


def test_le_spese_si_leggono_dalla_piu_recente(conn: sqlite3.Connection) -> None:
    _spesa(conn, descrizione="vecchia", giorno=date(2026, 8, 20))
    _spesa(conn, descrizione="nuova", giorno=date(2026, 8, 30))
    assert [s.descrizione for s in dom.elenco(conn)] == ["nuova", "vecchia"]


def test_per_categoria_ordina_dalla_piu_pesante(conn: sqlite3.Connection) -> None:
    _spesa(conn, centesimi=500, categoria="Alimentari")
    _spesa(conn, centesimi=3000, categoria="Casa")
    _spesa(conn, centesimi=1000, categoria="Alimentari")
    assert dom.per_categoria(dom.elenco(conn)) == [("Casa", 3000), ("Alimentari", 1500)]


def test_le_spese_senza_categoria_finiscono_in_un_gruppo_dichiarato(
    conn: sqlite3.Connection,
) -> None:
    _spesa(conn, centesimi=500)
    assert dom.per_categoria(dom.elenco(conn)) == [("Senza categoria", 500)]


def test_per_giorno_riempie_anche_i_giorni_a_zero(conn: sqlite3.Connection) -> None:
    _spesa(conn, centesimi=1000, giorno=date(2026, 8, 29))
    _spesa(conn, centesimi=500, giorno=date(2026, 8, 31))
    assert dom.per_giorno(dom.elenco(conn), da=date(2026, 8, 29), giorni=3) == [1000, 0, 500]


def test_i_luoghi_frequenti_contano_le_volte_non_gli_euro(conn: sqlite3.Connection) -> None:
    _spesa(conn, centesimi=9000, luogo="Coop")
    _spesa(conn, centesimi=100, luogo="Bar Rossi")
    _spesa(conn, centesimi=100, luogo="Bar Rossi")
    _spesa(conn, centesimi=100)
    assert dom.luoghi_frequenti(dom.elenco(conn)) == [("Bar Rossi", 2), ("Coop", 1)]


def test_giorni_dall_ultima_spesa(conn: sqlite3.Connection) -> None:
    assert dom.giorni_dall_ultima([], OGGI) is None
    _spesa(conn, giorno=date(2026, 8, 28))
    assert dom.giorni_dall_ultima(dom.elenco(conn), OGGI) == 3


def test_una_spesa_datata_domani_non_confonde_il_conto_dei_giorni(conn: sqlite3.Connection) -> None:
    # Una data letta male su uno scontrino non deve dare "-2 giorni".
    _spesa(conn, giorno=date(2026, 9, 2))
    _spesa(conn, giorno=date(2026, 8, 28))
    assert dom.giorni_dall_ultima(dom.elenco(conn), OGGI) == 3


def test_chi_ha_scelto_la_categoria_resta_scritto(conn: sqlite3.Connection) -> None:
    # Una categoria che hai scritto tu e una proposta dal modello si
    # correggono con criteri diversi: la distinzione va tenuta.
    _spesa(conn, descrizione="dal modello", categoria="Alimentari")
    _spesa(conn, descrizione="scritta da me", categoria="Casa", categoria_da_utente=True)
    per_nome = {c.nome: c.creata_da for c in dom.categorie(conn)}
    assert per_nome == {"Alimentari": "ia", "Casa": "utente"}
