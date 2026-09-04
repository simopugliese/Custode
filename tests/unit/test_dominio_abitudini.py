"""Abitudini, log e conti (§8.6).

I conti sono la parte che si sbaglia in silenzio: un'aderenza sballata non
rompe niente, dice solo un numero un po' diverso da quello vero, e ci si
accorge mesi dopo. Per questo `attesi`, `aderenza` e `striscia` sono funzioni
pure e qui vengono provate su casi limite che un database renderebbe scomodi
da costruire.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from custode_core.dominio import abitudini as dom


def _crea(conn: sqlite3.Connection, ora: datetime, nome: str = "Palestra", target: int = 3):  # type: ignore[no-untyped-def]
    return dom.crea(conn, nome=nome, target_settimanale=target, ora=ora)


# — creazione e modifica (§8.6: tutto modificabile in qualsiasi momento) —


def test_crea_e_rilegge(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = _crea(conn, ora)
    assert (abitudine.nome, abitudine.target_settimanale, abitudine.attiva) == ("Palestra", 3, True)
    assert dom.elenco(conn) == [abitudine]


@pytest.mark.parametrize("target", [0, 8, -1])
def test_un_target_fuori_scala_non_passa(
    conn: sqlite3.Connection, ora: datetime, target: int
) -> None:
    with pytest.raises(ValueError):
        _crea(conn, ora, target=target)


def test_un_nome_vuoto_non_passa(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(ValueError):
        _crea(conn, ora, nome="   ")


def test_riaggiungere_un_abitudine_disattivata_la_riprende(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Riprenderla non deve spezzare in due la storia già raccolta."""
    abitudine = _crea(conn, ora)
    dom.segna(conn, abitudine.id, giorno=ora.date(), fatto=True, ora=ora)
    dom.modifica(conn, abitudine.id, attiva=False)

    ripresa = _crea(conn, ora, nome="  palestra  ", target=4)

    assert ripresa.id == abitudine.id
    assert (ripresa.attiva, ripresa.target_settimanale) == (True, 4)
    assert dom.log_del_periodo(conn, da=ora.date(), a=ora.date()) == {abitudine.id: {ora.date()}}


def test_disattivare_non_cancella_i_log(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = _crea(conn, ora)
    dom.segna(conn, abitudine.id, giorno=ora.date(), fatto=True, ora=ora)
    dom.modifica(conn, abitudine.id, attiva=False)

    assert dom.elenco(conn) == []
    assert [a.nome for a in dom.elenco(conn, solo_attive=False)] == ["Palestra"]
    assert dom.log_del_periodo(conn, da=ora.date(), a=ora.date())


def test_rinominare_su_un_nome_gia_preso_non_passa(conn: sqlite3.Connection, ora: datetime) -> None:
    """Due «Palestra» renderebbero ambiguo il matching del testo libero."""
    _crea(conn, ora, nome="Palestra")
    lettura = _crea(conn, ora, nome="Lettura")
    with pytest.raises(ValueError):
        dom.modifica(conn, lettura.id, nome="palestra")


def test_leggere_qualcosa_che_non_esiste(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.AbitudineInesistente):
        dom.leggi(conn, 999)


# — log —


def test_segnare_due_volte_lo_stesso_giorno_aggiorna(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    abitudine = _crea(conn, ora)
    dom.segna(conn, abitudine.id, giorno=ora.date(), fatto=True, ora=ora)
    dom.segna(conn, abitudine.id, giorno=ora.date(), fatto=False, ora=ora)

    assert dom.segnata(conn, abitudine.id, ora.date()) is False
    assert dom.log_del_periodo(conn, da=ora.date(), a=ora.date()) == {}


def test_un_non_fatto_non_e_un_silenzio(conn: sqlite3.Connection, ora: datetime) -> None:
    """«non ho fatto meditazione» è una cosa detta; il silenzio no."""
    abitudine = _crea(conn, ora)
    assert dom.segnata(conn, abitudine.id, ora.date()) is None
    dom.segna(conn, abitudine.id, giorno=ora.date(), fatto=False, ora=ora)
    assert dom.segnata(conn, abitudine.id, ora.date()) is False


def test_annullare_riporta_al_silenzio(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = _crea(conn, ora)
    dom.segna(conn, abitudine.id, giorno=ora.date(), fatto=True, ora=ora)
    dom.togli_log(conn, abitudine.id, ora.date())
    assert dom.segnata(conn, abitudine.id, ora.date()) is None


def test_un_log_su_un_abitudine_inesistente_non_resta_orfano(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    with pytest.raises(dom.AbitudineInesistente):
        dom.segna(conn, 999, giorno=ora.date(), fatto=True, ora=ora)


def test_i_log_arrivano_divisi_per_abitudine(conn: sqlite3.Connection, ora: datetime) -> None:
    palestra = _crea(conn, ora, nome="Palestra")
    lettura = _crea(conn, ora, nome="Lettura")
    ieri = ora.date() - timedelta(days=1)
    dom.segna(conn, palestra.id, giorno=ora.date(), fatto=True, ora=ora)
    dom.segna(conn, palestra.id, giorno=ieri, fatto=True, ora=ora)
    dom.segna(conn, lettura.id, giorno=ieri, fatto=True, ora=ora)

    assert dom.log_del_periodo(conn, da=ieri, a=ora.date()) == {
        palestra.id: {ieri, ora.date()},
        lettura.id: {ieri},
    }


# — i conti, che non passano da nessun modello —


@pytest.mark.parametrize(
    ("target", "giorni", "atteso"),
    [
        (3, 7, 3.0),
        (3, 14, 6.0),
        (7, 7, 7.0),
        (3, 3, 3 * 3 / 7),  # a metà settimana il target è proporzionale
        (3, 0, 0.0),
    ],
)
def test_attesi(target: int, giorni: int, atteso: float) -> None:
    assert dom.attesi(target, giorni) == pytest.approx(atteso)


@pytest.mark.parametrize(
    ("fatti", "attesi", "atteso"),
    [
        (3, 3.0, 1.0),
        (2, 4.0, 0.5),
        (0, 3.0, 0.0),
        (5, 3.0, 1.0),  # sopra il 100% non si va: coprirebbe le altre in media
        (2, 0.0, 0.0),  # nessuna attesa: non è un'aderenza infinita
    ],
)
def test_aderenza(fatti: int, attesi: float, atteso: float) -> None:
    assert dom.aderenza(fatti, attesi) == pytest.approx(atteso)


def test_percentuale_e_intera() -> None:
    assert dom.percentuale(0.6349) == 63


def test_striscia_conta_i_giorni_di_fila() -> None:
    oggi = date(2026, 9, 3)
    fatti = {oggi, oggi - timedelta(days=1), oggi - timedelta(days=2)}
    assert dom.striscia(fatti, oggi) == 3


def test_una_striscia_interrotta_riparte(conn: sqlite3.Connection) -> None:
    oggi = date(2026, 9, 3)
    fatti = {oggi, oggi - timedelta(days=2), oggi - timedelta(days=3)}
    assert dom.striscia(fatti, oggi) == 1


def test_la_striscia_non_si_azzera_perche_oggi_non_e_ancora_segnato() -> None:
    """Alle nove del mattino ogni striscia sarebbe zero, e direbbe solo che ore sono."""
    oggi = date(2026, 9, 3)
    fatti = {oggi - timedelta(days=1), oggi - timedelta(days=2)}
    assert dom.striscia(fatti, oggi) == 2


def test_nessun_log_nessuna_striscia() -> None:
    assert dom.striscia(set(), date(2026, 9, 3)) == 0


def test_presenze_seguono_l_ordine_dei_giorni() -> None:
    lunedi = date(2026, 8, 31)
    giorni = dom.giorni_fra(lunedi, lunedi + timedelta(days=6))
    assert len(giorni) == 7
    assert dom.presenze({lunedi, lunedi + timedelta(days=2)}, giorni) == [
        True,
        False,
        True,
        False,
        False,
        False,
        False,
    ]


# — proposte di adeguamento del target —


def test_una_proposta_non_cambia_niente_da_sola(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = _crea(conn, ora, target=3)
    proposta = dom.proponi(
        conn, abitudine.id, target_proposto=2, motivazione="sei a 2,1 di media", ora=ora
    )

    assert proposta.target_attuale == 3
    assert dom.leggi(conn, abitudine.id).target_settimanale == 3
    assert dom.proposta_aperta(conn) == proposta


def test_accettare_applica_il_nuovo_target(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = _crea(conn, ora, target=3)
    proposta = dom.proponi(conn, abitudine.id, target_proposto=2, motivazione="perché", ora=ora)

    decisa = dom.decidi(conn, proposta.id, accetta=True, ora=ora)

    assert decisa.stato is dom.StatoProposta.ACCETTATA
    assert dom.leggi(conn, abitudine.id).target_settimanale == 2
    assert dom.proposta_aperta(conn) is None


def test_rifiutare_lascia_tutto_com_era(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = _crea(conn, ora, target=3)
    proposta = dom.proponi(conn, abitudine.id, target_proposto=2, motivazione="perché", ora=ora)

    dom.decidi(conn, proposta.id, accetta=False, ora=ora)

    assert dom.leggi(conn, abitudine.id).target_settimanale == 3
    assert dom.proposta_aperta(conn) is None
    assert dom.rifiutata_di_recente(conn, abitudine.id, dal=ora.date() - timedelta(days=30))


def test_decidere_due_volte_non_si_puo(conn: sqlite3.Connection, ora: datetime) -> None:
    abitudine = _crea(conn, ora, target=3)
    proposta = dom.proponi(conn, abitudine.id, target_proposto=2, motivazione="perché", ora=ora)
    dom.decidi(conn, proposta.id, accetta=True, ora=ora)
    with pytest.raises(ValueError):
        dom.decidi(conn, proposta.id, accetta=False, ora=ora)


def test_una_proposta_nuova_sostituisce_quella_in_attesa(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Quella vecchia è stata scritta su numeri che nel frattempo sono cambiati."""
    abitudine = _crea(conn, ora, target=3)
    dom.proponi(conn, abitudine.id, target_proposto=2, motivazione="vecchia", ora=ora)
    nuova = dom.proponi(conn, abitudine.id, target_proposto=4, motivazione="nuova", ora=ora)

    aperta = dom.proposta_aperta(conn)
    assert aperta is not None
    assert (aperta.id, aperta.motivazione) == (nuova.id, "nuova")


def test_una_proposta_identica_al_target_non_ha_senso(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    abitudine = _crea(conn, ora, target=3)
    with pytest.raises(ValueError):
        dom.proponi(conn, abitudine.id, target_proposto=3, motivazione="uguale", ora=ora)


def test_una_proposta_senza_motivazione_non_e_valutabile(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    abitudine = _crea(conn, ora, target=3)
    with pytest.raises(ValueError):
        dom.proponi(conn, abitudine.id, target_proposto=2, motivazione="  ", ora=ora)


def test_le_proposte_di_abitudini_disattivate_non_si_mostrano(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    abitudine = _crea(conn, ora, target=3)
    dom.proponi(conn, abitudine.id, target_proposto=2, motivazione="perché", ora=ora)
    dom.modifica(conn, abitudine.id, attiva=False)
    assert dom.proposta_aperta(conn) is None


def test_decidere_una_proposta_che_non_c_e(conn: sqlite3.Connection, ora: datetime) -> None:
    with pytest.raises(dom.PropostaInesistente):
        dom.decidi(conn, 999, accetta=True, ora=ora)


# — report narrativi —


def test_il_report_si_salva_e_si_rilegge(conn: sqlite3.Connection, ora: datetime) -> None:
    lunedi = ora.date()
    salvato = dom.salva_report(
        conn, periodo=dom.Periodo.SETTIMANA, chiave=lunedi, testo="Settimana solida.", ora=ora
    )
    assert salvato.testo == "Settimana solida."
    assert dom.report(conn, periodo=dom.Periodo.SETTIMANA, chiave=lunedi) == salvato
    assert dom.ultimo_report(conn, periodo=dom.Periodo.SETTIMANA) == salvato
    # I due periodi non si confondono fra loro.
    assert dom.ultimo_report(conn, periodo=dom.Periodo.MESE) is None


def test_riscrivere_lo_stesso_periodo_sostituisce(conn: sqlite3.Connection, ora: datetime) -> None:
    lunedi = ora.date()
    dom.salva_report(conn, periodo=dom.Periodo.SETTIMANA, chiave=lunedi, testo="prima", ora=ora)
    dom.salva_report(conn, periodo=dom.Periodo.SETTIMANA, chiave=lunedi, testo="dopo", ora=ora)
    riletto = dom.report(conn, periodo=dom.Periodo.SETTIMANA, chiave=lunedi)
    assert riletto is not None and riletto.testo == "dopo"


def test_l_ultimo_report_e_il_piu_recente(conn: sqlite3.Connection, ora: datetime) -> None:
    lunedi = ora.date()
    dom.salva_report(
        conn,
        periodo=dom.Periodo.SETTIMANA,
        chiave=lunedi - timedelta(days=7),
        testo="vecchio",
        ora=ora,
    )
    dom.salva_report(conn, periodo=dom.Periodo.SETTIMANA, chiave=lunedi, testo="nuovo", ora=ora)
    ultimo = dom.ultimo_report(conn, periodo=dom.Periodo.SETTIMANA)
    assert ultimo is not None and ultimo.testo == "nuovo"
