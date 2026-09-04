"""Il resoconto delle abitudini, settimanale e mensile (§8.6).

Il modello è finto: quello che si verifica qui è ciò che gli arriva (numeri già
calcolati, diario e spese dello stesso periodo) e cosa succede a quello che
risponde — il report si salva, la proposta resta una proposta, e un guasto non
porta via il resto del giro settimanale.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from custode_core.dominio import abitudini as dom
from custode_core.dominio import diario as dom_diario
from custode_core.dominio import spese as dom_spese
from custode_router.compiti import Compito
from custode_router.errori import ProviderNonRaggiungibile
from custode_worker import abitudini as worker_abitudini

pytestmark = pytest.mark.integration


class RouterFinto:
    """Risponde il report che gli si dice, e registra cosa ha ricevuto."""

    def __init__(self, risposta: dict[str, Any] | None = None, errore: Exception | None = None):
        self.risposta = risposta or {"report": "Settimana solida."}
        self.errore = errore
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.risposta


LUNEDI = date(2026, 8, 31)


def _abitudine(
    conn: sqlite3.Connection, ora: datetime, nome: str, target: int = 3
) -> dom.Abitudine:
    return dom.crea(conn, nome=nome, target_settimanale=target, ora=ora)


def _esegui(
    conn: sqlite3.Connection,
    ora: datetime,
    router: RouterFinto,
    *,
    periodo: dom.Periodo = dom.Periodo.SETTIMANA,
    chiave: date = LUNEDI,
) -> worker_abitudini.Esito:
    return worker_abitudini.esegui(
        conn,
        ora,
        periodo=periodo,
        chiave=chiave,
        router=router,  # type: ignore[arg-type]
    )


# — cosa riceve il modello —


def test_senza_abitudini_non_si_chiama_nessuno(conn: sqlite3.Connection, ora: datetime) -> None:
    """Un report che dice «non segui niente» è una notifica sprecata."""
    router = RouterFinto()
    esito = _esegui(conn, ora, router)

    assert router.chiamate == []
    assert esito.messaggio is None
    assert esito.report_scritto is False


def test_i_numeri_arrivano_gia_calcolati(conn: sqlite3.Connection, ora: datetime) -> None:
    palestra = _abitudine(conn, ora, "Palestra", 3)
    for scarto in range(2):
        dom.segna(conn, palestra.id, giorno=LUNEDI + timedelta(days=scarto), fatto=True, ora=ora)

    router = RouterFinto()
    _esegui(conn, ora, router)

    prompt = router.chiamate[0]["utente"]
    assert "Palestra: obiettivo 3 volte a settimana, fatta 2 volte su 3.0 attese (67%" in prompt
    assert router.chiamate[0]["compito"] is Compito.REPORT_ABITUDINI


def test_il_prompt_incrocia_diario_e_spese(conn: sqlite3.Connection, ora: datetime) -> None:
    """È l'incrocio che §8.6 chiede: le abitudini da sole le dice già la pagina."""
    _abitudine(conn, ora, "Palestra")
    voce, _ = dom_diario.aggiungi_materiale(
        conn, giorno=LUNEDI, testo="Serata in biblioteca", ora=ora
    )
    dom_diario.approva(conn, voce.id, ora, testo="Serata in biblioteca.")
    dom_spese.registra(
        conn, centesimi=1200, descrizione="pranzo", ora=ora, giorno=LUNEDI, categoria="Alimentari"
    )

    router = RouterFinto()
    _esegui(conn, ora, router)

    prompt = router.chiamate[0]["utente"]
    assert "biblioteca" in prompt
    assert "12,00 €" in prompt and "Alimentari" in prompt


def test_il_settimanale_non_chiede_proposte(conn: sqlite3.Connection, ora: datetime) -> None:
    """Sette giorni non sono una tendenza: chiederla e scartarla sarebbe uno spreco."""
    _abitudine(conn, ora, "Palestra")
    router = RouterFinto()
    _esegui(conn, ora, router)
    assert "non proporre adeguamenti" in router.chiamate[0]["utente"]


# — cosa si fa della risposta —


def test_il_report_si_salva_e_diventa_messaggio(conn: sqlite3.Connection, ora: datetime) -> None:
    _abitudine(conn, ora, "Palestra")
    esito = _esegui(conn, ora, RouterFinto({"report": "Tre volte su tre."}))

    assert esito.report_scritto is True
    salvato = dom.report(conn, periodo=dom.Periodo.SETTIMANA, chiave=LUNEDI)
    assert salvato is not None and salvato.testo == "Tre volte su tre."
    assert esito.messaggio is not None
    assert "Tre volte su tre." in esito.messaggio.testo
    assert "Le tue abitudini" in esito.messaggio.testo


def test_rifare_il_job_non_ricosta_una_chiamata(conn: sqlite3.Connection, ora: datetime) -> None:
    """Un periodo chiuso non cambia: riscriverlo sarebbe pagare per lo stesso testo."""
    _abitudine(conn, ora, "Palestra")
    _esegui(conn, ora, RouterFinto({"report": "primo"}))

    router = RouterFinto({"report": "secondo"})
    esito = _esegui(conn, ora, router)

    assert router.chiamate == []
    assert esito.messaggio is not None and "primo" in esito.messaggio.testo


def test_se_claude_non_risponde_non_si_perde_il_mese(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _abitudine(conn, ora, "Palestra")
    esito = _esegui(conn, ora, RouterFinto(errore=ProviderNonRaggiungibile("giù")))

    assert esito.report_scritto is False
    assert esito.messaggio is None
    # L'errore torna a chi chiama, che non segna il job come fatto e riproverà.
    assert esito.errore is not None and "Claude" in esito.errore
    assert dom.report(conn, periodo=dom.Periodo.SETTIMANA, chiave=LUNEDI) is None


# — la proposta di adeguamento (§8.6) —


PROPOSTA = {
    "report": "Il mese",
    "proposta_abitudine": "Palestra",
    "proposta_target": 2,
    "proposta_motivazione": "sei a 2,1 di media da sei settimane",
}


def test_la_proposta_nasce_solo_dal_mensile(conn: sqlite3.Connection, ora: datetime) -> None:
    _abitudine(conn, ora, "Palestra", 3)

    esito = _esegui(conn, ora, RouterFinto(dict(PROPOSTA)))

    assert esito.proposta_creata is False
    assert dom.proposta_aperta(conn) is None


def test_il_mensile_mette_in_attesa_senza_cambiare_niente(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    abitudine = _abitudine(conn, ora, "Palestra", 3)

    esito = _esegui(
        conn,
        ora,
        RouterFinto(dict(PROPOSTA)),
        periodo=dom.Periodo.MESE,
        chiave=date(2026, 8, 1),
    )

    assert esito.proposta_creata is True
    aperta = dom.proposta_aperta(conn)
    assert aperta is not None and aperta.target_proposto == 2
    # Il target vero non si muove finché non premi «Accetta» (§8.1).
    assert dom.leggi(conn, abitudine.id).target_settimanale == 3


def test_dopo_un_no_non_si_ripropone_subito(conn: sqlite3.Connection, ora: datetime) -> None:
    """Ripetere la stessa domanda dopo un no è il modo di non farsi più leggere."""
    abitudine = _abitudine(conn, ora, "Palestra", 3)
    proposta = dom.proponi(conn, abitudine.id, target_proposto=2, motivazione="perché", ora=ora)
    dom.decidi(conn, proposta.id, accetta=False, ora=ora)

    esito = _esegui(
        conn, ora, RouterFinto(dict(PROPOSTA)), periodo=dom.Periodo.MESE, chiave=date(2026, 8, 1)
    )

    assert esito.proposta_creata is False
    assert dom.proposta_aperta(conn) is None


def test_una_proposta_su_un_abitudine_inventata_non_passa(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _abitudine(conn, ora, "Palestra", 3)
    risposta = dict(PROPOSTA, proposta_abitudine="Chitarra")

    esito = _esegui(
        conn, ora, RouterFinto(risposta), periodo=dom.Periodo.MESE, chiave=date(2026, 8, 1)
    )

    assert esito.proposta_creata is False
    assert dom.proposta_aperta(conn) is None


def test_l_intervallo_del_mese_arriva_alla_fine(conn: sqlite3.Connection, ora: datetime) -> None:
    """Agosto ha 31 giorni: il conto degli attesi deve usarli tutti."""
    _abitudine(conn, ora, "Palestra", 7)
    router = RouterFinto({"report": "x"})
    _esegui(conn, ora, router, periodo=dom.Periodo.MESE, chiave=date(2026, 8, 1))
    assert "su 31.0 attese" in router.chiamate[0]["utente"]
