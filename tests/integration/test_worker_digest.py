"""Il digest mattutino (§8.13): cosa dice, e soprattutto cosa dice quando manca un pezzo.

Il criterio è quello di §8.12: si omette e si dice, non si inventa. Un meteo
che manca non deve leggersi come «non piove», un calendario non guardato come
«giornata libera».
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest

from custode_calendario.evento import Evento
from custode_core.dominio import abitudini as dom_abitudini
from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import posizione as dom_posizione
from custode_core.dominio import task as dom_task
from custode_core.registro_job import SYNC_CALENDARIO, segna_eseguito
from custode_meteo import MeteoNonRaggiungibile
from custode_meteo.previsione import Previsione
from custode_router.errori import ProviderNonRaggiungibile
from custode_worker import digest

pytestmark = pytest.mark.integration

MATTINA = datetime(2026, 8, 31, 7, 30)  # lunedì
OGGI = MATTINA.date()


class SorgenteFinta:
    def __init__(self, previsioni: list[Previsione] | Exception) -> None:
        self.previsioni_date = previsioni
        self.chiamate = 0

    def previsioni(self, lat: float, lon: float, giorni: int, fuso: str) -> list[Previsione]:
        self.chiamate += 1
        if isinstance(self.previsioni_date, Exception):
            raise self.previsioni_date
        return self.previsioni_date


class ModelloFinto:
    """`risposta` può essere un dict, o un'eccezione da sollevare; `None` = senza chiave."""

    def __init__(self, risposta: dict[str, Any] | Exception | None = None) -> None:
        self.risposta = risposta
        self.prompt: str | None = None

    def configurato_per(self, compito: Any) -> bool:
        return self.risposta is not None

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.prompt = kwargs["utente"]
        if isinstance(self.risposta, Exception):
            raise self.risposta
        assert self.risposta is not None
        return self.risposta


def piove(prob: int = 70) -> list[Previsione]:
    return [Previsione(giorno=OGGI, codice=61, minima=12.0, massima=18.0, prob_pioggia=prob)]


def _lezione(conn: sqlite3.Connection, titolo: str = "Analisi", ora: int = 9) -> None:
    inizio = datetime.combine(OGGI, time(ora, 0))
    dom_calendario.sincronizza(
        conn,
        [Evento(id="e1", titolo=titolo, inizio=inizio, fine=inizio + timedelta(hours=2))],
        da=OGGI - timedelta(days=7),
        a=OGGI + timedelta(days=14),
        ora=MATTINA,
    )
    segna_eseguito(conn, SYNC_CALENDARIO, MATTINA, MATTINA)


def _componi(
    conn: sqlite3.Connection,
    *,
    meteo: SorgenteFinta | None = None,
    modello: ModelloFinto | None = None,
    casa: tuple[float, float] | None = None,
    calendario: bool = True,
) -> digest.Esito:
    return digest.esegui(
        conn,
        MATTINA,
        router=modello or ModelloFinto(),  # type: ignore[arg-type]
        sorgente_meteo=meteo or SorgenteFinta(piove()),
        casa=casa,
        fuso="Europe/Rome",
        calendario_configurato=calendario,
    )


def _testo(esito: digest.Esito) -> str:
    assert esito.messaggio is not None
    return esito.messaggio.testo


def test_digest_completo_col_testo_di_base(conn: sqlite3.Connection) -> None:
    _lezione(conn)
    dom_posizione.salva(conn, 45.07, 7.69, MATTINA)
    dom_task.crea(conn, titolo="Bolletta", ora=MATTINA, scadenza=OGGI)
    dom_task.crea(conn, titolo="Mail al prof", ora=MATTINA, scadenza=OGGI - timedelta(days=2))
    palestra = dom_abitudini.crea(conn, nome="meditazione", target_settimanale=7, ora=MATTINA)
    assert palestra.id

    esito = _componi(conn)

    testo = _testo(esito)
    assert esito.con_modello is False
    assert "09:00 Analisi" in testo
    assert "Pioggia probabile (70%) e hai «Analisi» alle 09:00: porta l&#x27;ombrello." in testo
    assert "In ritardo" in testo and "Mail al prof" in testo
    assert "Per oggi" in testo and "Bolletta" in testo
    assert "meditazione: 0/7" in testo
    # ✓ per i task di oggi e in ritardo
    assert len(esito.messaggio.bottoni) == 2  # type: ignore[union-attr]


def test_il_modello_riscrive_ma_il_codice_controlla(conn: sqlite3.Connection) -> None:
    _lezione(conn)
    dom_posizione.salva(conn, 45.07, 7.69, MATTINA)
    frase = "Pioggia probabile (70%) e hai «Analisi» alle 09:00: porta l'ombrello."
    modello = ModelloFinto({"testo": f"Ciao! Alle 09:00 hai Analisi. {frase}"})

    esito = _componi(conn, modello=modello)

    assert esito.con_modello is True
    assert "Ciao! Alle 09:00 hai Analisi." in _testo(esito)
    assert modello.prompt is not None and "09:00 Analisi" in modello.prompt


def test_se_il_modello_perde_un_fatto_esce_il_testo_di_base(conn: sqlite3.Connection) -> None:
    _lezione(conn)
    dom_posizione.salva(conn, 45.07, 7.69, MATTINA)

    esito = _componi(conn, modello=ModelloFinto({"testo": "Buongiorno, giornata piena."}))

    assert esito.con_modello is False
    assert esito.errore is not None
    assert "09:00 Analisi" in _testo(esito)


def test_se_il_modello_non_risponde_esce_il_testo_di_base(conn: sqlite3.Connection) -> None:
    _lezione(conn)

    esito = _componi(conn, modello=ModelloFinto(ProviderNonRaggiungibile("giù")))

    assert esito.con_modello is False
    assert "09:00 Analisi" in _testo(esito)


def test_senza_posizione_niente_meteo_e_lo_dice(conn: sqlite3.Connection) -> None:
    _lezione(conn)
    meteo = SorgenteFinta(piove())

    testo = _testo(_componi(conn, meteo=meteo))

    assert "Non so dove sei" in testo
    assert "Meteo:" not in testo and "ombrello" not in testo
    assert meteo.chiamate == 0


def test_con_la_casa_del_env_il_meteo_c_e_e_lo_dice(conn: sqlite3.Connection) -> None:
    _lezione(conn)
    testo = _testo(_componi(conn, casa=(45.0, 7.6)))
    assert "Meteo:" in testo and "(casa)" in testo


def test_openmeteo_giu_si_omette_e_si_dice(conn: sqlite3.Connection) -> None:
    _lezione(conn)
    dom_posizione.salva(conn, 45.07, 7.69, MATTINA)

    testo = _testo(_componi(conn, meteo=SorgenteFinta(MeteoNonRaggiungibile("giù"))))

    assert "Il meteo non risponde" in testo
    assert "Meteo:" not in testo
    assert "09:00 Analisi" in testo  # il resto parte lo stesso


def test_calendario_non_collegato_lo_dice(conn: sqlite3.Connection) -> None:
    dom_task.crea(conn, titolo="Bolletta", ora=MATTINA, scadenza=OGGI)

    testo = _testo(_componi(conn, calendario=False))

    assert "non è collegato" in testo
    assert "Nessun impegno" not in testo


def test_calendario_mai_sincronizzato_non_dice_che_la_giornata_e_libera(
    conn: sqlite3.Connection,
) -> None:
    dom_task.crea(conn, titolo="Bolletta", ora=MATTINA, scadenza=OGGI)

    testo = _testo(_componi(conn))

    assert dom_calendario.NON_ANCORA_SINCRONIZZATO in testo
    assert "Nessun impegno" not in testo


def test_calendario_sincronizzato_e_vuoto_dice_nessun_impegno(conn: sqlite3.Connection) -> None:
    segna_eseguito(conn, SYNC_CALENDARIO, MATTINA, MATTINA)
    dom_task.crea(conn, titolo="Bolletta", ora=MATTINA, scadenza=OGGI)

    assert "Nessun impegno oggi." in _testo(_componi(conn))


def test_senza_task_la_sezione_si_omette_in_silenzio(conn: sqlite3.Connection) -> None:
    _lezione(conn)

    testo = _testo(_componi(conn))

    assert "Per oggi" not in testo and "In ritardo" not in testo


def test_i_task_senza_scadenza_sono_solo_un_conteggio(conn: sqlite3.Connection) -> None:
    _lezione(conn)
    dom_task.crea(conn, titolo="Un giorno o l'altro", ora=MATTINA)

    testo = _testo(_componi(conn))

    assert "Senza scadenza: 1 task aperto." in testo
    assert "Un giorno o l'altro" not in testo


def test_tutto_vuoto_non_manda_niente(conn: sqlite3.Connection) -> None:
    """Solo note e «nessun impegno»: sarebbe una notifica sprecata."""
    segna_eseguito(conn, SYNC_CALENDARIO, MATTINA, MATTINA)

    esito = _componi(conn)

    assert esito.messaggio is None


def test_un_impegno_di_giornata_non_ha_un_orario_inventato(conn: sqlite3.Connection) -> None:
    dom_calendario.sincronizza(
        conn,
        [
            Evento(
                id="g1",
                titolo="Compleanno Anna",
                inizio=datetime.combine(OGGI, time(0, 0)),
                fine=datetime.combine(OGGI + timedelta(days=1), time(0, 0)),
                tutto_il_giorno=True,
            )
        ],
        da=date(2026, 8, 24),
        a=date(2026, 9, 14),
        ora=MATTINA,
    )

    assert "Compleanno Anna (tutto il giorno)" in _testo(_componi(conn))
