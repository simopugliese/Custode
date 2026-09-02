"""Le spese su Telegram: la foto di uno scontrino, /spese, conferma e scarto (§8.5).

`risposte` è fatto di funzioni pure: tutto il giro si esercita senza Telegram e
senza Claude, con un router finto che risponde quello che gli si dice.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from custode_bot import azioni, risposte
from custode_core.dominio import spese as dom
from custode_router.errori import ProviderNonRaggiungibile

SCONTRINO: dict[str, Any] = {
    "leggibile": True,
    "totale": 23.4,
    "luogo": "Coop",
    "data": "2026-08-30",
    "voci": ["Latte — 1,29", "Pane — 2,10"],
}


class RouterFinto:
    """Risponde con la lettura dello scontrino e con la categoria, a turno."""

    def __init__(
        self,
        scontrino: dict[str, Any] | None = None,
        categoria: str = "Alimentari",
        errore: Exception | None = None,
    ):
        self.scontrino = scontrino if scontrino is not None else dict(SCONTRINO)
        self.categoria = categoria
        self.errore = errore
        self.chiamate: list[Any] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append(compito)
        if self.errore is not None:
            raise self.errore
        return {"categoria": self.categoria, "esistente": False}

    def chiedi_json_con_immagine(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append(compito)
        if self.errore is not None:
            raise self.errore
        return self.scontrino


def _dati_bottoni(risposta: risposte.Risposta) -> list[str]:
    return [b.dato for riga in risposta.bottoni for b in riga]


def _scontrino(conn: sqlite3.Connection, ora: datetime, router: Any = None) -> risposte.Risposta:
    return risposte.scontrino(conn, ora, b"\xff\xd8foto", router or RouterFinto())  # type: ignore[arg-type]


# — la foto ————————————————————————————————————————————


def test_una_foto_diventa_una_spesa_che_aspetta_conferma(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    risposta = _scontrino(conn, ora)

    # Fuori dai conti finché non dici di sì: §8.5 lo chiede proprio perché il
    # modello ha letto dei numeri da un'immagine.
    assert dom.elenco(conn) == []
    (spesa,) = dom.in_attesa(conn)
    assert spesa.centesimi == 2340
    assert spesa.luogo == "Coop"
    assert spesa.giorno == date(2026, 8, 30)
    assert spesa.fonte is dom.Fonte.SCONTRINO
    assert "23,40 €" in risposta.testo
    assert "Entra nei conti solo se confermi" in risposta.testo


def test_i_bottoni_sono_conferma_e_scarta(conn: sqlite3.Connection, ora: datetime) -> None:
    risposta = _scontrino(conn, ora)
    (spesa,) = dom.in_attesa(conn)
    assert _dati_bottoni(risposta) == [
        azioni.spesa("conferma", spesa.id),
        azioni.spesa("scarta", spesa.id),
    ]


def test_le_voci_lette_restano_attaccate_alla_spesa(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    # §8.5 fa entrare nei conti solo il totale, ma il dettaglio non si butta:
    # è l'unica cosa che resta della foto, che non viene conservata.
    _scontrino(conn, ora)
    (spesa,) = dom.in_attesa(conn)
    assert spesa.scontrino_raw == "Latte — 1,29\nPane — 2,10"


def test_la_categoria_arriva_dal_modello_dopo_il_salvataggio(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    risposta = _scontrino(conn, ora, RouterFinto(categoria="Alimentari"))
    (spesa,) = dom.in_attesa(conn)
    assert spesa.categoria == "Alimentari"
    assert "Alimentari" in risposta.testo


def test_se_la_categoria_non_arriva_lo_scontrino_letto_non_va_perso(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    # È il motivo per cui la categoria si chiede *dopo* aver scritto la spesa.
    class SoloLettura(RouterFinto):
        def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
            raise ProviderNonRaggiungibile("Claude non risponde")

    risposta = _scontrino(conn, ora, SoloLettura())
    (spesa,) = dom.in_attesa(conn)
    assert spesa.centesimi == 2340
    assert spesa.categoria is None
    assert "23,40 €" in risposta.testo


def test_una_foto_illeggibile_non_lascia_niente_nel_database(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    risposta = _scontrino(conn, ora, RouterFinto(scontrino=dict(SCONTRINO, leggibile=False)))
    assert dom.in_attesa(conn) == []
    assert "nitida" in risposta.testo


def test_se_claude_non_risponde_lo_dice_e_propone_di_scriverla(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    risposta = _scontrino(conn, ora, RouterFinto(errore=ProviderNonRaggiungibile("giù")))
    assert dom.in_attesa(conn) == []
    assert "Riprova" in risposta.testo


def test_uno_scontrino_senza_data_finisce_a_oggi(conn: sqlite3.Connection, ora: datetime) -> None:
    _scontrino(conn, ora, RouterFinto(scontrino=dict(SCONTRINO, data="")))
    (spesa,) = dom.in_attesa(conn)
    assert spesa.giorno == ora.date()


# — conferma e scarto ——————————————————————————————————


def test_confermare_fa_entrare_la_spesa_nei_conti(conn: sqlite3.Connection, ora: datetime) -> None:
    _scontrino(conn, ora)
    (spesa,) = dom.in_attesa(conn)

    risposta = risposte.esegui_azione(conn, ora, azioni.spesa("conferma", spesa.id), RouterFinto())  # type: ignore[arg-type]

    assert dom.in_attesa(conn) == []
    assert dom.totale(dom.elenco(conn)) == 2340
    assert "Nei conti" in risposta.testo


def test_scartare_butta_lo_scontrino_senza_lasciare_tracce(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _scontrino(conn, ora)
    (spesa,) = dom.in_attesa(conn)

    risposta = risposte.esegui_azione(conn, ora, azioni.spesa("scarta", spesa.id), RouterFinto())  # type: ignore[arg-type]

    assert dom.in_attesa(conn) == []
    assert dom.elenco(conn) == []
    assert "non è entrato nei conti" in risposta.testo


def test_un_bottone_di_uno_scontrino_gia_smaltito_non_esplode(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _scontrino(conn, ora)
    (spesa,) = dom.in_attesa(conn)
    dato = azioni.spesa("conferma", spesa.id)
    risposte.esegui_azione(conn, ora, dato, RouterFinto())  # type: ignore[arg-type]

    # Secondo tap sullo stesso messaggio: già confermata, niente da fare.
    risposta = risposte.esegui_azione(conn, ora, dato, RouterFinto())  # type: ignore[arg-type]
    assert "non è più valido" in risposta.testo


# — /spese —————————————————————————————————————————————


def _registra(conn: sqlite3.Connection, ora: datetime, **extra: Any) -> dom.Spesa:
    campi: dict[str, Any] = {"centesimi": 800, "descrizione": "colazione"}
    campi.update(extra)
    return dom.registra(conn, ora=ora, **campi)


def test_spese_senza_niente_dice_come_si_registra(conn: sqlite3.Connection, ora: datetime) -> None:
    risposta = risposte.elenco_spese(conn, ora)
    assert "Non hai ancora registrato spese" in risposta.testo
    assert "scontrino" in risposta.testo


def test_spese_mostra_totale_categorie_e_ultime(conn: sqlite3.Connection, ora: datetime) -> None:
    _registra(conn, ora, centesimi=3000, descrizione="spesa", categoria="Alimentari")
    _registra(conn, ora, centesimi=800, descrizione="colazione", categoria="Bar")

    risposta = risposte.elenco_spese(conn, ora)
    assert "38,00 €" in risposta.testo
    assert "Alimentari — 30,00 €" in risposta.testo
    assert "colazione" in risposta.testo


def test_spese_guarda_il_mese_corrente_non_tutto_l_archivio(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _registra(conn, ora, centesimi=5000, descrizione="vecchia", giorno=date(2026, 7, 15))
    _registra(conn, ora, centesimi=800, descrizione="colazione")

    risposta = risposte.elenco_spese(conn, ora)
    assert "8,00 €" in risposta.testo
    assert "vecchia" not in risposta.testo


def test_uno_scontrino_in_attesa_si_ripresenta_in_spese(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    # Senza questo, una foto mandata e mai confermata resterebbe invisibile
    # dopo che il messaggio è scorso via nella chat.
    _scontrino(conn, ora)
    (spesa,) = dom.in_attesa(conn)

    risposta = risposte.elenco_spese(conn, ora)
    assert "in attesa di conferma" in risposta.testo
    assert azioni.spesa("conferma", spesa.id) in _dati_bottoni(risposta)


def test_spese_e_nell_aiuto() -> None:
    assert "/spese" in risposte.aiuto().testo
