"""Il diario sul database: raccolta, approvazione, annullamento, statistiche.

Nessun modello entra in questi test: qui si verifica la regola che §8.4 pone al
centro — nel diario finisce solo ciò che è stato approvato — e il fatto che
tutto il resto (bozze, materiale grezzo, riscritture) resti fuori.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from custode_core.dominio import diario as dom


def _giorno(conn: sqlite3.Connection, ora: datetime, *testi: str, vocale: bool = False) -> dom.Voce:
    voce = None
    for testo in testi:
        voce, _ = dom.aggiungi_materiale(
            conn, giorno=ora.date(), testo=testo, ora=ora, da_vocale=vocale
        )
    assert voce is not None
    return voce


def _approva(conn: sqlite3.Connection, ora: datetime, giorno: date, testo: str) -> dom.Voce:
    """Una giornata già chiusa e approvata, per i test sulle statistiche."""
    voce, _ = dom.aggiungi_materiale(conn, giorno=giorno, testo="materiale", ora=ora)
    dom.proponi(conn, voce.id, riassunto=testo, tag=["studio"])
    return dom.approva(conn, voce.id, ora)


# — raccolta —


def test_i_messaggi_del_giorno_finiscono_sulla_stessa_voce(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Una voce per giorno, non una per messaggio (§8.4)."""
    voce = _giorno(conn, ora, "mattinata in biblioteca", "poi palestra")

    assert len(dom.elenco(conn)) == 1
    assert voce.grezzo == "mattinata in biblioteca\npoi palestra"
    assert voce.stato is dom.Stato.IN_RACCOLTA


def test_distingue_il_dettato_dallo_scritto(conn: sqlite3.Connection, ora: datetime) -> None:
    """È ciò che la dashboard mostra come «da 1 vocale e 2 messaggi»."""
    dom.aggiungi_materiale(conn, giorno=ora.date(), testo="dettato", ora=ora, da_vocale=True)
    _giorno(conn, ora, "scritto", "altro scritto")

    voce = dom.leggi_giorno(conn, ora.date())
    assert voce is not None
    assert (voce.n_vocali, voce.n_messaggi) == (1, 2)


def test_materiale_vuoto_e_un_errore(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(ValueError):
        dom.aggiungi_materiale(conn, giorno=ora.date(), testo="   ", ora=ora)


def test_una_frase_nuova_invalida_la_bozza(conn: sqlite3.Connection, ora: datetime) -> None:
    """Una bozza calcolata prima dell'ultima frase non la comprende."""
    voce = _giorno(conn, ora, "prima frase")
    dom.proponi(conn, voce.id, riassunto="bozza", tag=["studio"])

    _giorno(conn, ora, "seconda frase")

    aggiornata = dom.leggi(conn, voce.id)
    assert aggiornata.riassunto_proposto is None
    assert aggiornata.stato is dom.Stato.IN_RACCOLTA


# — approvazione: il cuore di §8.4 —


def test_solo_la_versione_approvata_entra_nel_diario(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    voce = _giorno(conn, ora, "giornata piena")
    dom.proponi(conn, voce.id, riassunto="Hai lavorato tutto il giorno.", tag=["lavoro"])

    in_bozza = dom.leggi(conn, voce.id)
    assert in_bozza.riassunto_approvato is None  # niente diario finché non approvi
    assert in_bozza.stato is dom.Stato.DA_APPROVARE

    approvata = dom.approva(conn, voce.id, ora)
    assert approvata.riassunto_approvato == "Hai lavorato tutto il giorno."
    # La bozza sparisce: da qui in poi esiste una sola versione.
    assert approvata.riassunto_proposto is None
    assert approvata.approvata_il == ora


def test_la_riscrittura_vince_sulla_bozza_parola_per_parola(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """La modifica di §8.4 punto 5: ciò che entra nel diario è tuo."""
    voce = _giorno(conn, ora, "giornata")
    dom.proponi(conn, voce.id, riassunto="Versione del modello.", tag=["umore"])

    approvata = dom.approva(conn, voce.id, ora, testo="  Le mie parole.  ")
    assert approvata.riassunto_approvato == "Le mie parole."


def test_non_si_approva_il_vuoto(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _giorno(conn, ora, "giornata")
    with pytest.raises(ValueError):
        dom.approva(conn, voce.id, ora)


def test_scartare_non_lascia_niente(conn: sqlite3.Connection, ora: datetime) -> None:
    """Scartare butta anche il grezzo: nel diario non resta traccia."""
    voce = _giorno(conn, ora, "sfogo di cui mi sono pentito")
    dom.proponi(conn, voce.id, riassunto="bozza", tag=[])

    dom.scarta(conn, voce.id)

    assert dom.leggi_giorno(conn, ora.date()) is None
    # I frammenti se ne vanno con la voce (ON DELETE CASCADE).
    assert conn.execute("SELECT count(*) AS n FROM diary_fragments").fetchone()["n"] == 0


def test_aggiungere_a_una_giornata_approvata_non_cancella_l_approvato(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    voce = _giorno(conn, ora, "prima parte")
    dom.proponi(conn, voce.id, riassunto="Prima versione.", tag=["studio"])
    dom.approva(conn, voce.id, ora)

    _giorno(conn, ora, "poi è successo altro")

    riaperta = dom.leggi(conn, voce.id)
    assert riaperta.stato is dom.Stato.IN_RACCOLTA
    # Finché non ne approvi una nuova, quella vecchia resta leggibile.
    assert riaperta.riassunto_approvato == "Prima versione."


# — riscrittura: la macchina a stati che sopravvive a un riavvio —


def test_il_giro_della_modifica(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _giorno(conn, ora, "giornata")
    dom.proponi(conn, voce.id, riassunto="bozza", tag=[])

    dom.chiedi_modifica(conn, voce.id)
    # `in_modifica` si legge dal database, non dalla memoria del processo: è
    # quello che permette al bot di riprendere il filo dopo un riavvio.
    attesa = dom.in_modifica(conn)
    assert attesa is not None and attesa.id == voce.id

    dom.annulla_modifica(conn, voce.id)
    assert dom.in_modifica(conn) is None
    assert dom.leggi(conn, voce.id).stato is dom.Stato.DA_APPROVARE


def test_si_riscrive_solo_una_bozza_in_attesa(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _giorno(conn, ora, "giornata")  # ancora in raccolta
    with pytest.raises(ValueError):
        dom.chiedi_modifica(conn, voce.id)


# — annullamento (§8.1): togliere esattamente la frase aggiunta —


def test_annullare_toglie_solo_la_frase_giusta(conn: sqlite3.Connection, ora: datetime) -> None:
    _giorno(conn, ora, "prima")
    _voce, frammento = dom.aggiungi_materiale(
        conn, giorno=ora.date(), testo="questa non c'entra", ora=ora
    )
    _giorno(conn, ora, "terza")

    tolto = dom.togli_frammento(conn, frammento)

    assert tolto == "questa non c'entra"
    voce = dom.leggi_giorno(conn, ora.date())
    assert voce is not None
    assert voce.grezzo == "prima\nterza"


def test_annullare_l_unica_frase_fa_sparire_la_giornata(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _voce, frammento = dom.aggiungi_materiale(conn, giorno=ora.date(), testo="unica", ora=ora)

    dom.togli_frammento(conn, frammento)

    # Non una giornata vuota da mostrare: una giornata di cui non hai scritto.
    assert dom.leggi_giorno(conn, ora.date()) is None


def test_annullare_non_cancella_una_giornata_gia_nel_diario(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    voce = _giorno(conn, ora, "materiale")
    dom.proponi(conn, voce.id, riassunto="Già approvato.", tag=[])
    dom.approva(conn, voce.id, ora)

    dopo = ora + timedelta(hours=2)
    _v, frammento = dom.aggiungi_materiale(conn, giorno=ora.date(), testo="aggiunta", ora=dopo)
    assert dom.leggi(conn, voce.id).stato is dom.Stato.IN_RACCOLTA  # riaperta

    dom.togli_frammento(conn, frammento)

    rimasta = dom.leggi(conn, voce.id)
    assert rimasta.riassunto_approvato == "Già approvato."
    # Annullare l'aggiunta rimette la giornata com'era: chiusa.
    assert rimasta.stato is dom.Stato.APPROVATA


def test_annullare_una_sola_aggiunta_su_due_lascia_la_giornata_da_riscrivere(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    voce = _giorno(conn, ora, "materiale")
    dom.proponi(conn, voce.id, riassunto="Già approvato.", tag=[])
    dom.approva(conn, voce.id, ora)

    dopo = ora + timedelta(hours=2)
    _v, primo = dom.aggiungi_materiale(conn, giorno=ora.date(), testo="aggiunta", ora=dopo)
    dom.aggiungi_materiale(conn, giorno=ora.date(), testo="altra aggiunta", ora=dopo)

    dom.togli_frammento(conn, primo)

    # Resta materiale che il riassunto approvato non ha mai visto: la giornata
    # ha ancora qualcosa da incorporare.
    assert dom.leggi(conn, voce.id).stato is dom.Stato.IN_RACCOLTA


def test_annullare_due_volte_non_esplode(conn: sqlite3.Connection, ora: datetime) -> None:
    """Capita col bottone di un messaggio vecchio in cronologia."""
    _voce, frammento = dom.aggiungi_materiale(conn, giorno=ora.date(), testo="x", ora=ora)
    dom.togli_frammento(conn, frammento)

    with pytest.raises(dom.FrammentoInesistente):
        dom.togli_frammento(conn, frammento)


def test_id_inesistente(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(dom.VoceInesistente):
        dom.leggi(conn, 999)


# — tag —


def test_i_tag_si_normalizzano_e_non_si_ripetono(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _giorno(conn, ora, "giornata")
    aggiornata = dom.proponi(conn, voce.id, riassunto="x", tag=["Studio", "  studio ", "UMORE", ""])
    assert aggiornata.tag == ["studio", "umore"]


def test_un_tag_scritto_male_sul_database_non_rompe_la_lettura(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    voce = _giorno(conn, ora, "giornata")
    conn.execute("UPDATE diary_entries SET tag = 'non json' WHERE id = ?", (voce.id,))
    assert dom.leggi(conn, voce.id).tag == []


# — statistiche —


def test_giorni_consecutivi(conn: sqlite3.Connection, ora: datetime) -> None:
    oggi = ora.date()
    for scarto in (1, 2, 3):
        _approva(conn, ora, oggi - timedelta(days=scarto), "testo")

    voci = dom.elenco(conn)
    # Oggi non è ancora scritto: a metà giornata la serie non è interrotta.
    assert dom.giorni_consecutivi(voci, oggi) == 3

    _approva(conn, ora, oggi, "testo")
    assert dom.giorni_consecutivi(dom.elenco(conn), oggi) == 4


def test_giorni_consecutivi_si_ferma_al_buco(conn: sqlite3.Connection, ora: datetime) -> None:
    oggi = ora.date()
    _approva(conn, ora, oggi - timedelta(days=1), "testo")
    _approva(conn, ora, oggi - timedelta(days=3), "testo")  # manca il giorno 2

    assert dom.giorni_consecutivi(dom.elenco(conn), oggi) == 1


def test_le_statistiche_guardano_solo_l_approvato(conn: sqlite3.Connection, ora: datetime) -> None:
    _approva(conn, ora, ora.date(), "una due tre quattro")
    ieri = ora.date() - timedelta(days=1)
    bozza, _ = dom.aggiungi_materiale(conn, giorno=ieri, testo="materiale di ieri", ora=ora)
    dom.proponi(conn, bozza.id, riassunto="una due tre quattro cinque sei", tag=["lavoro"])

    voci = dom.elenco(conn)
    assert dom.parole_media(voci) == 4  # la bozza non entra nella media
    assert dom.conteggio_tag(voci) == [("studio", 1)]  # né fra i temi
    assert dom.giorni_consecutivi(voci, ora.date()) == 1


def test_copertura(conn: sqlite3.Connection, ora: datetime) -> None:
    primo = date(2026, 8, 1)
    _approva(conn, ora, date(2026, 8, 1), "testo")
    _approva(conn, ora, date(2026, 8, 3), "testo")

    assert dom.copertura(dom.elenco(conn), da=primo, giorni=4) == [True, False, True, False]


@pytest.mark.parametrize(
    ("giorno", "attesi"),
    [(date(2026, 2, 10), 28), (date(2028, 2, 10), 29), (date(2026, 8, 5), 31)],
)
def test_giorni_nel_mese(giorno: date, attesi: int) -> None:
    assert dom.giorni_nel_mese(giorno) == attesi


def test_approvate_in_ordine_cronologico(conn: sqlite3.Connection, ora: datetime) -> None:
    """L'ordine che serve al job settimanale: dal lunedì in avanti."""
    oggi = ora.date()
    for scarto in (2, 0, 1):
        _approva(conn, ora, oggi - timedelta(days=scarto), f"giorno {scarto}")

    settimana = dom.approvate(conn, da=oggi - timedelta(days=6), a=oggi)
    assert [v.giorno for v in settimana] == [
        oggi - timedelta(days=2),
        oggi - timedelta(days=1),
        oggi,
    ]


def test_in_attesa_non_guarda_il_periodo(conn: sqlite3.Connection, ora: datetime) -> None:
    """Le bozze si trovano tutte, anche quelle di mesi fa."""
    vecchia, _ = dom.aggiungi_materiale(conn, giorno=date(2026, 1, 5), testo="vecchia", ora=ora)
    dom.proponi(conn, vecchia.id, riassunto="bozza vecchia", tag=[])
    _approva(conn, ora, ora.date(), "già approvata")

    assert [v.id for v in dom.in_attesa(conn)] == [vecchia.id]


def test_anche_una_voce_in_riscrittura_e_in_attesa(conn: sqlite3.Connection, ora: datetime) -> None:
    """Sta aspettando te: va contata fra le cose da sbrigare."""
    voce = _giorno(conn, ora, "materiale")
    dom.proponi(conn, voce.id, riassunto="bozza", tag=[])
    dom.chiedi_modifica(conn, voce.id)

    assert [v.id for v in dom.in_attesa(conn)] == [voce.id]
