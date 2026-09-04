"""Il flusso del diario su Telegram: /diario, i tre bottoni, la riscrittura.

`risposte` è fatto di funzioni pure, quindi tutto il giro di §8.4 — raccolta,
proposta, approvazione o riscrittura o scarto — si esercita qui senza Telegram
e senza modelli, con un router finto al posto di Claude.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from custode_bot import azioni, risposte
from custode_core.dominio import diario as dom
from custode_router.errori import ProviderNonRaggiungibile


class RouterFinto:
    def __init__(self, risposta: dict[str, Any] | None = None, errore: Exception | None = None):
        self.risposta = risposta or {
            "riassunto": "Hai passato la mattina in biblioteca.",
            "tag": ["studio"],
        }
        self.errore = errore
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.risposta


def _dati_bottoni(risposta: risposte.Risposta) -> list[str]:
    return [b.dato for riga in risposta.bottoni for b in riga]


def _testi_bottoni(risposta: risposte.Risposta) -> list[str]:
    return [b.testo for riga in risposta.bottoni for b in riga]


def _proponi(conn: sqlite3.Connection, ora: datetime, testo: str = "in biblioteca") -> dom.Voce:
    """Porta la giornata fino alla bozza, come farebbe /diario."""
    dom.aggiungi_materiale(conn, giorno=ora.date(), testo=testo, ora=ora)
    risposte.diario_giorno(conn, ora, RouterFinto())  # type: ignore[arg-type]
    voce = dom.leggi_giorno(conn, ora.date())
    assert voce is not None
    return voce


# — /diario —


def test_senza_materiale_non_chiama_claude(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto()
    risposta = risposte.diario_giorno(conn, ora, router)  # type: ignore[arg-type]

    assert "non mi hai raccontato niente" in risposta.testo
    assert router.chiamate == []


def test_chiude_la_giornata_e_propone(conn: sqlite3.Connection, ora: datetime) -> None:
    dom.aggiungi_materiale(conn, giorno=ora.date(), testo="mattina in biblioteca", ora=ora)
    router = RouterFinto()

    risposta = risposte.diario_giorno(conn, ora, router)  # type: ignore[arg-type]

    assert "Hai passato la mattina in biblioteca." in risposta.testo
    # Le tre uscite di §8.4, tutte a un tap.
    assert _testi_bottoni(risposta) == ["✓ Approva", "✎ Modifica", "Scarta"]
    # E si vede che non è ancora nel diario.
    assert "solo se lo approvi" in risposta.testo

    voce = dom.leggi_giorno(conn, ora.date())
    assert voce is not None and voce.riassunto_approvato is None


def test_un_secondo_diario_non_richiama_claude(conn: sqlite3.Connection, ora: datetime) -> None:
    """La bozza c'è già: rigenerarla sarebbe spesa buttata (§1)."""
    dom.aggiungi_materiale(conn, giorno=ora.date(), testo="materiale", ora=ora)
    risposte.diario_giorno(conn, ora, RouterFinto())  # type: ignore[arg-type]

    secondo = RouterFinto()
    risposta = risposte.diario_giorno(conn, ora, secondo)  # type: ignore[arg-type]

    assert secondo.chiamate == []
    assert "Hai passato la mattina in biblioteca." in risposta.testo


def test_se_claude_non_risponde_il_materiale_resta(conn: sqlite3.Connection, ora: datetime) -> None:
    dom.aggiungi_materiale(conn, giorno=ora.date(), testo="mattina in biblioteca", ora=ora)
    router = RouterFinto(errore=ProviderNonRaggiungibile("giù"))

    risposta = risposte.diario_giorno(conn, ora, router)  # type: ignore[arg-type]

    assert "Riprova fra poco" in risposta.testo or "riprova fra poco" in risposta.testo
    voce = dom.leggi_giorno(conn, ora.date())
    assert voce is not None and voce.grezzo == "mattina in biblioteca"


def test_una_giornata_gia_nel_diario_si_rilegge(conn: sqlite3.Connection, ora: datetime) -> None:
    """E non si rigenera: sarebbe una chiamata a Claude per riscrivere una cosa
    già decisa, e riaprirebbe una giornata chiusa."""
    voce = _proponi(conn, ora)
    dom.approva(conn, voce.id, ora)

    router = RouterFinto()
    risposta = risposte.diario_giorno(conn, ora, router)  # type: ignore[arg-type]

    assert "già nel diario" in risposta.testo
    assert router.chiamate == []
    assert dom.leggi(conn, voce.id).stato is dom.Stato.APPROVATA


def test_materiale_nuovo_su_una_giornata_chiusa_la_fa_riproporre(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    voce = _proponi(conn, ora)
    dom.approva(conn, voce.id, ora)

    dom.aggiungi_materiale(conn, giorno=ora.date(), testo="poi è successo altro", ora=ora)
    router = RouterFinto({"riassunto": "Versione integrata.", "tag": ["studio"]})
    risposta = risposte.diario_giorno(conn, ora, router)  # type: ignore[arg-type]

    assert "Versione integrata." in risposta.testo
    # La vecchia versione approvata è nel prompt: la nuova la integra, non
    # riparte da zero.
    assert "Hai passato la mattina in biblioteca." in router.chiamate[0]["utente"]


# — i bottoni —


def test_approva(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _proponi(conn, ora)

    risposta = risposte.esegui_azione(conn, ora, azioni.diario("approva", voce.id))

    assert "già nel diario" in risposta.testo
    assert risposta.bottoni == []  # non c'è più niente da decidere
    approvata = dom.leggi(conn, voce.id)
    assert approvata.riassunto_approvato == "Hai passato la mattina in biblioteca."


def test_scarta_non_lascia_niente(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _proponi(conn, ora, "sfogo")

    risposta = risposte.esegui_azione(conn, ora, azioni.diario("scarta", voce.id))

    assert "non resta" in risposta.testo
    assert dom.leggi_giorno(conn, ora.date()) is None


def test_il_bottone_di_una_voce_sparita_non_esplode(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Capita col messaggio vecchio in cronologia."""
    risposta = risposte.esegui_azione(conn, ora, azioni.diario("approva", 999))
    assert "non esiste più" in risposta.testo


def test_un_nome_di_azione_sconosciuto(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _proponi(conn, ora)
    risposta = risposte.esegui_azione(conn, ora, azioni.diario("boh", voce.id))
    assert "non è più valido" in risposta.testo


# — la riscrittura: il «modifichi» di §8.4 punto 5 —


def test_modifica_poi_riscrittura_verbatim(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _proponi(conn, ora)

    chiesta = risposte.esegui_azione(conn, ora, azioni.diario("modifica", voce.id))
    assert "parola per parola" in chiesta.testo

    # Il messaggio successivo *è* la voce: non passa dal modello, e infatti il
    # router finto non riceve nessuna chiamata.
    router = RouterFinto()
    risposta = risposte.messaggio_libero(
        conn,
        ora,
        "Mattina in biblioteca, pomeriggio buttato.",
        router,  # type: ignore[arg-type]
    )

    assert router.chiamate == []
    approvata = dom.leggi(conn, voce.id)
    assert approvata.riassunto_approvato == "Mattina in biblioteca, pomeriggio buttato."
    assert approvata.stato is dom.Stato.APPROVATA
    assert "già nel diario" in risposta.testo


def test_anche_un_vocale_puo_essere_la_riscrittura(conn: sqlite3.Connection, ora: datetime) -> None:
    """§8.1: dettare e scrivere devono essere la stessa cosa."""
    voce = _proponi(conn, ora)
    risposte.esegui_azione(conn, ora, azioni.diario("modifica", voce.id))

    risposte.messaggio_libero(conn, ora, "Detto a voce.", RouterFinto(), da_vocale=True)  # type: ignore[arg-type]

    assert dom.leggi(conn, voce.id).riassunto_approvato == "Detto a voce."


def test_lasciare_la_bozza_torna_indietro(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _proponi(conn, ora)
    risposte.esegui_azione(conn, ora, azioni.diario("modifica", voce.id))

    risposta = risposte.esegui_azione(conn, ora, azioni.diario("annmod", voce.id))

    assert "Hai passato la mattina in biblioteca." in risposta.testo
    assert _testi_bottoni(risposta) == ["✓ Approva", "✎ Modifica", "Scarta"]
    assert dom.in_modifica(conn) is None


def test_in_attesa_di_riscrittura_diario_lo_ricorda(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    voce = _proponi(conn, ora)
    risposte.esegui_azione(conn, ora, azioni.diario("modifica", voce.id))

    risposta = risposte.diario_giorno(conn, ora, RouterFinto())  # type: ignore[arg-type]
    assert "parola per parola" in risposta.testo


def test_un_messaggio_vuoto_non_diventa_il_diario(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = _proponi(conn, ora)
    risposte.esegui_azione(conn, ora, azioni.diario("modifica", voce.id))

    risposte.messaggio_libero(conn, ora, "   ", RouterFinto())  # type: ignore[arg-type]

    assert dom.leggi(conn, voce.id).riassunto_approvato is None


# — annotazione dal linguaggio libero, con l'Annulla di §8.1 —


def test_una_frase_raccontata_finisce_nel_diario_con_annulla(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    router = RouterFinto({"azione": "annota_diario", "titolo": "giornata pesante"})

    risposta = risposte.messaggio_libero(conn, ora, "che giornata pesante", router)  # type: ignore[arg-type]

    assert "Annotato nel diario" in risposta.testo
    assert _testi_bottoni(risposta) == ["Annulla"]

    voce = dom.leggi_giorno(conn, ora.date())
    assert voce is not None and voce.grezzo == "giornata pesante"


def test_annullare_l_annotazione(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto({"azione": "annota_diario", "titolo": "giornata pesante"})
    risposta = risposte.messaggio_libero(conn, ora, "che giornata pesante", router)  # type: ignore[arg-type]
    (dato,) = _dati_bottoni(risposta)

    annullata = risposte.esegui_azione(conn, ora, dato)

    assert "Tolto dal diario" in annullata.testo
    assert dom.leggi_giorno(conn, ora.date()) is None


def test_un_vocale_raccontato_conta_come_vocale(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto({"azione": "annota_diario", "titolo": "giornata pesante"})

    risposte.messaggio_libero(conn, ora, "che giornata", router, da_vocale=True)  # type: ignore[arg-type]

    voce = dom.leggi_giorno(conn, ora.date())
    assert voce is not None
    assert (voce.n_vocali, voce.n_messaggi) == (1, 0)


def test_l_aiuto_racconta_il_diario() -> None:
    testo = risposte.aiuto()
    assert "/diario" in testo.testo
    assert "solo se lo approvi" in testo.testo


@pytest.mark.parametrize("nome", ["approva", "modifica", "scarta", "annmod"])
def test_i_callback_data_stanno_nel_limite_di_telegram(nome: str) -> None:
    assert len(azioni.diario(nome, 999999).encode()) <= 64


# — chiudere una giornata raccontata in ritardo (§8.4) —


@pytest.mark.parametrize(
    ("argomento", "scarto"),
    [("", 0), ("oggi", 0), ("ieri", 1), ("l'altro ieri", 2), ("IERI", 1)],
)
def test_leggi_giorno_comando_relativo(argomento: str, scarto: int) -> None:
    oggi = date(2026, 8, 31)
    assert risposte.leggi_giorno_comando(argomento, oggi) == oggi - timedelta(days=scarto)


def test_leggi_giorno_comando_accetta_le_forme_che_il_bot_stampa() -> None:
    """«2 set» è come il bot stesso scrive le date: deve poterla rileggere."""
    oggi = date(2026, 9, 10)
    assert risposte.leggi_giorno_comando("2 set", oggi) == date(2026, 9, 2)
    assert risposte.leggi_giorno_comando("2026-09-02", oggi) == date(2026, 9, 2)
    # Un giorno di questo mese non ancora arrivato si legge come quello dell'anno prima.
    assert risposte.leggi_giorno_comando("20 set", oggi) == date(2025, 9, 20)


@pytest.mark.parametrize("argomento", ["domani", "2026-13-45", "settimana scorsa", "32 set"])
def test_un_giorno_che_non_si_capisce_vale_none(argomento: str) -> None:
    assert risposte.leggi_giorno_comando(argomento, date(2026, 8, 31)) is None


def test_chiudere_ieri_riassume_ieri(conn: sqlite3.Connection, ora: datetime) -> None:
    ieri = ora.date() - timedelta(days=1)
    dom.aggiungi_materiale(conn, giorno=ieri, testo="Studiato tutto il giorno", ora=ora)
    router = RouterFinto({"riassunto": "Giornata di studio.", "tag": ["studio"]})

    risposta = risposte.diario_giorno(conn, ora, router, giorno=ieri)  # type: ignore[arg-type]

    voce = dom.leggi_giorno(conn, ieri)
    assert voce is not None and voce.riassunto_proposto == "Giornata di studio."
    assert "Giornata di studio." in risposta.testo


def test_il_bottone_chiude_il_giorno_che_dice(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il tap fa esattamente quello che farebbe `/diario ieri`."""
    ieri = ora.date() - timedelta(days=1)
    dom.aggiungi_materiale(conn, giorno=ieri, testo="Studiato", ora=ora)
    router = RouterFinto({"riassunto": "Studio.", "tag": []})

    risposte.esegui_azione(conn, ora, azioni.diario_giorno(ieri), router)  # type: ignore[arg-type]

    voce = dom.leggi_giorno(conn, ieri)
    assert voce is not None and voce.riassunto_proposto == "Studio."


def test_chiudere_un_giorno_vuoto_lo_dice_col_suo_nome(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    ieri = ora.date() - timedelta(days=1)
    router = RouterFinto({"riassunto": "x", "tag": []})
    risposta = risposte.diario_giorno(conn, ora, router, giorno=ieri)  # type: ignore[arg-type]
    assert "Dom 30 agosto" in risposta.testo
    assert router.chiamate == []
