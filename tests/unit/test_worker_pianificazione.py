"""Quando il worker deve svegliarsi davvero.

È la parte che, senza queste prove, si verificherebbe solo aspettando domenica
sera: `settimana_dovuta` prende `adesso` come parametro apposta.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custode_worker import pianificazione
from custode_worker.config import ImpostazioniWorker

# Domenica 6 settembre 2026; il lunedì di quella settimana è il 31 agosto.
DOMENICA = date(2026, 9, 6)
LUNEDI = date(2026, 8, 31)


def _dovuta(quando: datetime, giorno: str = "domenica") -> date | None:
    return pianificazione.settimana_dovuta(quando, giorno=giorno, ore=21, minuti=0)


# — il caso normale —


def test_prima_dell_ora_non_e_dovuto() -> None:
    assert _dovuta(datetime(2026, 9, 6, 20, 59)) != LUNEDI


def test_all_ora_esatta_e_dovuto() -> None:
    assert _dovuta(datetime(2026, 9, 6, 21, 0)) == LUNEDI


def test_dopo_l_ora_resta_dovuto() -> None:
    assert _dovuta(datetime(2026, 9, 6, 23, 30)) == LUNEDI


def test_a_meta_settimana_e_dovuta_quella_prima() -> None:
    """Mercoledì la settimana in corso non è finita: si guarda alla precedente."""
    assert _dovuta(datetime(2026, 9, 2, 12, 0)) == LUNEDI - timedelta(days=7)


# — recupero dopo che il Pi è stato spento —


def test_se_il_pi_era_spento_il_job_parte_appena_torna_su() -> None:
    """Lunedì mattina la settimana di domenica è ancora da fare, non persa."""
    assert _dovuta(datetime(2026, 9, 7, 9, 0)) == LUNEDI


def test_dopo_un_assenza_lunga_si_riprende_dall_ultima_settimana() -> None:
    """Non quattro revisioni tutte insieme: quella più recente e basta."""
    lontano = _dovuta(datetime(2026, 10, 5, 9, 0))
    assert lontano == date(2026, 9, 28)  # non il 31 agosto


# — la variante «lunedì» —


def test_col_riepilogo_al_lunedi_si_chiude_la_settimana_appena_finita() -> None:
    # Domenica sera non è ancora ora.
    assert _dovuta(datetime(2026, 9, 6, 22, 0), giorno="lunedi") != LUNEDI
    # Lunedì sera sì, e riguarda la settimana che si è appena chiusa.
    assert _dovuta(datetime(2026, 9, 7, 21, 0), giorno="lunedi") == LUNEDI


@pytest.mark.parametrize(
    ("giorno", "atteso"),
    [("domenica", datetime(2026, 9, 6, 21, 0)), ("lunedi", datetime(2026, 9, 7, 21, 0))],
)
def test_momento_previsto(giorno: str, atteso: datetime) -> None:
    assert pianificazione.momento_previsto(LUNEDI, giorno, 21, 0) == atteso


# — configurazione —


@pytest.mark.parametrize("valore", ["21:00", "07:30", "00:00", "23:59"])
def test_orari_validi(valore: str) -> None:
    assert ImpostazioniWorker(ora_riepilogo=valore, _env_file=None).ora_e_minuto()  # type: ignore[call-arg]


@pytest.mark.parametrize("valore", ["21", "21:00:00", "venticinque", "25:00", "21:70", ""])
def test_un_orario_storto_si_scopre_subito(valore: str) -> None:
    """Meglio che il worker si rifiuti di partire che girare senza scattare mai."""
    with pytest.raises(ValueError):
        ImpostazioniWorker(ora_riepilogo=valore, _env_file=None).ora_e_minuto()  # type: ignore[call-arg]


# — il resoconto mensile delle abitudini (§8.6) —


@pytest.mark.parametrize(
    ("adesso", "atteso"),
    [
        # Il primo di settembre alle 21:00 si racconta agosto.
        (datetime(2026, 9, 1, 21, 0), date(2026, 8, 1)),
        # Alle 20:59 agosto non è ancora dovuto: si guarda indietro di uno, e
        # il candidato è luglio — che al primo giro è già stato fatto e viene
        # fermato dal registro. È la stessa finestra di recupero della
        # settimana: un Pi spento all'ora prevista non perde il periodo.
        (datetime(2026, 9, 1, 20, 59), date(2026, 7, 1)),
        # A metà mese resta agosto: che sia già stato raccontato lo dice il registro.
        (datetime(2026, 9, 15, 12, 0), date(2026, 8, 1)),
        # Pi spento per due settimane: si recupera appena torna su.
        (datetime(2026, 9, 14, 21, 0), date(2026, 8, 1)),
    ],
)
def test_mese_dovuto(adesso: datetime, atteso: date | None) -> None:
    assert pianificazione.mese_dovuto(adesso, ore=21, minuti=0) == atteso


def test_a_gennaio_si_guarda_a_dicembre_dell_anno_prima() -> None:
    """Il cambio d'anno non deve far saltare un mese."""
    assert pianificazione.mese_dovuto(datetime(2027, 1, 1, 21, 0), ore=21, minuti=0) == date(
        2026, 12, 1
    )


# — le fasce, per i job che girano più volte al giorno (§8.10) —


@pytest.mark.parametrize(
    ("adesso", "atteso"),
    [
        # Le fasce sono ancorate all'ora, non al momento dell'avvio.
        (datetime(2026, 9, 14, 10, 0, 0), datetime(2026, 9, 14, 10, 0)),
        (datetime(2026, 9, 14, 10, 7, 30), datetime(2026, 9, 14, 10, 0)),
        (datetime(2026, 9, 14, 10, 14, 59), datetime(2026, 9, 14, 10, 0)),
        (datetime(2026, 9, 14, 10, 15, 0), datetime(2026, 9, 14, 10, 15)),
        (datetime(2026, 9, 14, 10, 59, 59), datetime(2026, 9, 14, 10, 45)),
        (datetime(2026, 9, 14, 23, 50), datetime(2026, 9, 14, 23, 45)),
    ],
)
def test_fascia_dovuta(adesso: datetime, atteso: datetime) -> None:
    assert pianificazione.fascia_dovuta(adesso, ogni_minuti=15) == atteso


def test_tre_risvegli_dentro_la_stessa_fascia_danno_lo_stesso_periodo() -> None:
    """Il worker si sveglia ogni cinque minuti: la fascia va coperta una volta sola."""
    fasce = {
        pianificazione.fascia_dovuta(datetime(2026, 9, 14, 10, m), ogni_minuti=15)
        for m in (0, 5, 10, 14)
    }
    assert len(fasce) == 1


def test_una_fascia_non_guarda_indietro() -> None:
    """Un Pi spento non ha fasce arretrate da recuperare.

    Le fasce perse non contengono lavoro diverso da quello di adesso: rifarle
    una per una vorrebbe dire risincronizzare novantasei volte per ottenere ciò
    che un giro solo ottiene subito. Quindi c'è sempre e solo la fascia corrente.
    """
    assert pianificazione.fascia_dovuta(datetime(2026, 9, 14, 10, 3), ogni_minuti=15) == datetime(
        2026, 9, 14, 10, 0
    )


@pytest.mark.parametrize("minuti", [0, -5, 61, 1440])
def test_una_fascia_fuori_misura_e_un_errore_subito(minuti: int) -> None:
    with pytest.raises(ValueError):
        pianificazione.fascia_dovuta(datetime(2026, 9, 14, 10, 3), ogni_minuti=minuti)
