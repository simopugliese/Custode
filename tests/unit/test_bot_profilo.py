"""Il canale passivo e il profilo su Telegram (§8.4).

Due cose distinte, provate qui insieme perché è così che si incontrano nella
chat: la domanda di chiarimento che si attacca a una risposta normale, e la
revisione settimanale con la rifusione che ne segue.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

import pytest

from custode_bot import azioni, risposte
from custode_core.dominio import profilo as dom
from custode_router.errori import ProviderNonRaggiungibile


class RouterFinto:
    """Risponde per compito: l'interprete e la rifusione hanno forme diverse."""

    def __init__(self, **per_compito: dict[str, Any]) -> None:
        self.per_compito = dict(per_compito)
        self.chiamate: list[dict[str, Any]] = []
        self.errore: Exception | None = None

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.per_compito.get(str(compito), {"azione": "nessuna"})


def _testi_bottoni(risposta: risposte.Risposta) -> list[str]:
    return [b.testo for riga in risposta.bottoni for b in riga]


def _dati_bottoni(risposta: risposte.Risposta) -> list[str]:
    return [b.dato for riga in risposta.bottoni for b in riga]


def _candidato(conn: sqlite3.Connection, ora: datetime, estratto: str) -> dom.Candidato:
    return dom.aggiungi_candidato(
        conn, messaggio_origine="un messaggio", estratto=estratto, ora=ora
    )


# — il segnale chiaro passa in silenzio —


def test_un_segnale_chiaro_non_interrompe_la_conversazione(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    router = RouterFinto(
        parsing_lista_spesa={
            "azione": "aggiungi_task",
            "titolo": "Finire il sito",
            "segnale": "chiaro",
            "segnale_estratto": "Preferisce il backend al frontend",
        }
    )

    risposta = risposte.messaggio_libero(conn, ora, "devo finire il sito", router)  # type: ignore[arg-type]

    # La risposta è quella dell'azione, e basta: nessuna domanda.
    assert "Segnato: Finire il sito" in risposta.testo
    assert _testi_bottoni(risposta) == ["Annulla"]
    # Ma il segnale è stato messo da parte.
    candidati = dom.da_rivedere(conn)
    assert [c.estratto for c in candidati] == ["Preferisce il backend al frontend"]


def test_nessun_segnale_non_lascia_niente(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto(parsing_lista_spesa={"azione": "nessuna", "segnale": "nessuno"})

    risposte.messaggio_libero(conn, ora, "ciao", router)  # type: ignore[arg-type]

    assert dom.da_rivedere(conn) == []


def test_un_segnale_senza_estratto_non_diventa_un_candidato(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Sul profilo si sbaglia per difetto: meglio perderne uno che inventarlo."""
    router = RouterFinto(
        parsing_lista_spesa={"azione": "nessuna", "segnale": "chiaro", "segnale_estratto": "  "}
    )

    risposte.messaggio_libero(conn, ora, "boh", router)  # type: ignore[arg-type]

    assert dom.da_rivedere(conn) == []


# — il segnale ambiguo chiede, lì per lì —


def test_un_segnale_ambiguo_fa_la_domanda_nello_stesso_messaggio(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    router = RouterFinto(
        parsing_lista_spesa={
            "azione": "annota_diario",
            "titolo": "che palle il frontend",
            "segnale": "ambiguo",
            "segnale_estratto": "Non sopporta il frontend",
            "segnale_domanda": "È una cosa che vale sempre o era la giornata?",
        }
    )

    risposta = risposte.messaggio_libero(conn, ora, "che palle il frontend", router)  # type: ignore[arg-type]

    # Una notifica sola: prima cosa ha fatto, poi la parentesi.
    assert "Annotato nel diario" in risposta.testo
    assert "È una cosa che vale sempre o era la giornata?" in risposta.testo
    assert _testi_bottoni(risposta) == ["Annulla", "Sono fatto così", "Era il momento"]


def test_rispondere_si_lo_tiene(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto(
        parsing_lista_spesa={
            "azione": "nessuna",
            "segnale": "ambiguo",
            "segnale_estratto": "Non sopporta il frontend",
            "segnale_domanda": "Vale sempre?",
        }
    )
    risposta = risposte.messaggio_libero(conn, ora, "che palle", router)  # type: ignore[arg-type]
    si = [d for d in _dati_bottoni(risposta) if ":si:" in d][0]

    esito = risposte.esegui_azione(conn, ora, si)

    assert "Non sopporta il frontend" in esito.testo
    (candidato,) = dom.da_rivedere(conn)
    assert candidato.stato is dom.Stato.CHIARITO


def test_rispondere_no_lo_butta(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto(
        parsing_lista_spesa={
            "azione": "nessuna",
            "segnale": "ambiguo",
            "segnale_estratto": "Non sopporta il frontend",
            "segnale_domanda": "Vale sempre?",
        }
    )
    risposta = risposte.messaggio_libero(conn, ora, "che palle", router)  # type: ignore[arg-type]
    no = [d for d in _dati_bottoni(risposta) if ":no:" in d][0]

    esito = risposte.esegui_azione(conn, ora, no)

    assert "lascio perdere" in esito.testo
    assert dom.da_rivedere(conn) == []


def test_una_domanda_alla_volta(conn: sqlite3.Connection, ora: datetime) -> None:
    """Due domande sospese in chat sono peggio di un candidato da guardare dopo."""
    router = RouterFinto(
        parsing_lista_spesa={
            "azione": "nessuna",
            "segnale": "ambiguo",
            "segnale_estratto": "Non sopporta il frontend",
            "segnale_domanda": "Vale sempre?",
        }
    )
    risposte.messaggio_libero(conn, ora, "primo", router)  # type: ignore[arg-type]

    seconda = risposte.messaggio_libero(conn, ora, "secondo", router)  # type: ignore[arg-type]

    assert "Vale sempre?" not in seconda.testo
    assert _testi_bottoni(seconda) == []
    # Il secondo segnale non si perde: è in coda per la revisione.
    assert len(dom.da_rivedere(conn)) == 2


# — /profilo —


def test_profilo_vuoto(conn: sqlite3.Connection) -> None:
    risposta = risposte.profilo(conn)
    assert "Non ho ancora un profilo" in risposta.testo


def test_profilo_con_versione_e_segnali_in_attesa(conn: sqlite3.Connection, ora: datetime) -> None:
    dom.salva_versione(conn, testo="Preferisce il backend.", ora=ora, candidati=[])
    _candidato(conn, ora, "Studia meglio la mattina")

    risposta = risposte.profilo(conn)

    assert "versione 1" in risposta.testo
    assert "Preferisce il backend." in risposta.testo
    assert "1 segnale nuovo in attesa" in risposta.testo


# — revisione settimanale e rifusione —


def test_la_revisione_elenca_i_candidati_con_un_tap_per_buttarli(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _candidato(conn, ora, "Preferisce il backend")
    _candidato(conn, ora, "Odia tutto")

    risposta = risposte.revisione_settimanale(conn)

    assert "2 segnali raccolti" in risposta.testo
    assert "Preferisce il backend" in risposta.testo
    assert _testi_bottoni(risposta)[-1] == "Aggiorna il profilo"


def test_scartare_ridisegna_la_revisione(conn: sqlite3.Connection, ora: datetime) -> None:
    _candidato(conn, ora, "Preferisce il backend")
    buttato = _candidato(conn, ora, "Odia tutto")

    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("scarta", buttato.id))

    assert "1 segnale raccolto" in risposta.testo
    assert "Odia tutto" not in risposta.testo


def test_rifondere_scrive_una_versione_nuova_e_lascia_tornare_indietro(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    dom.salva_versione(conn, testo="Vecchia versione.", ora=ora, candidati=[])
    _candidato(conn, ora, "Preferisce il backend")
    router = RouterFinto(
        rifusione_profilo={
            "profilo": "Preferisce il backend e studia la mattina.",
            "cambiamenti": ["aggiunta la preferenza per il backend"],
        }
    )

    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("rifondi"), router)  # type: ignore[arg-type]

    assert "versione 2" in risposta.testo
    assert "Preferisce il backend e studia la mattina." in risposta.testo
    assert "aggiunta la preferenza per il backend" in risposta.testo
    assert _testi_bottoni(risposta) == ["Torna alla precedente"]
    assert dom.testo_corrente(conn) == "Preferisce il backend e studia la mattina."


def test_la_prima_versione_non_ha_dove_tornare(conn: sqlite3.Connection, ora: datetime) -> None:
    _candidato(conn, ora, "Preferisce il backend")
    router = RouterFinto(rifusione_profilo={"profilo": "Prima.", "cambiamenti": []})

    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("rifondi"), router)  # type: ignore[arg-type]

    assert _testi_bottoni(risposta) == []


def test_tornare_indietro(conn: sqlite3.Connection, ora: datetime) -> None:
    dom.salva_versione(conn, testo="Vecchia.", ora=ora, candidati=[])
    candidato = _candidato(conn, ora, "Preferisce il backend")
    router = RouterFinto(rifusione_profilo={"profilo": "Nuova.", "cambiamenti": []})
    risposte.esegui_azione(conn, ora, azioni.profilo("rifondi"), router)  # type: ignore[arg-type]

    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("indietro"))

    assert "Vecchia." in risposta.testo
    assert "tornano in attesa" in risposta.testo
    assert dom.leggi_candidato(conn, candidato.id).versione_profilo is None


def test_annullare_l_unica_versione_lo_dice_chiaramente(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """`torna_indietro` risponde None in due casi diversi: qui si distinguono."""
    candidato = _candidato(conn, ora, "Preferisce il backend")
    router = RouterFinto(rifusione_profilo={"profilo": "Prima.", "cambiamenti": []})
    risposte.esegui_azione(conn, ora, azioni.profilo("rifondi"), router)  # type: ignore[arg-type]

    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("indietro"))

    assert "il profilo è di nuovo vuoto" in risposta.testo
    assert dom.corrente(conn) is None
    assert [c.id for c in dom.approvati(conn)] == [candidato.id]


def test_annullare_senza_nessun_profilo(conn: sqlite3.Connection, ora: datetime) -> None:
    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("indietro"))
    assert "Non c'è nessun profilo da annullare" in risposta.testo


def test_se_claude_non_risponde_i_segnali_non_si_perdono(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    candidato = _candidato(conn, ora, "Preferisce il backend")
    router = RouterFinto()
    router.errore = ProviderNonRaggiungibile("giù")

    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("rifondi"), router)  # type: ignore[arg-type]

    # (l'apostrofo esce come entità HTML: è l'escape che tutto il modulo applica)
    assert "aspettano la prossima settimana" in risposta.testo
    assert dom.corrente(conn) is None
    assert [c.id for c in dom.approvati(conn)] == [candidato.id]


def test_rifondere_senza_candidati(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto()
    risposta = risposte.esegui_azione(conn, ora, azioni.profilo("rifondi"), router)  # type: ignore[arg-type]
    assert "Non è rimasto niente" in risposta.testo
    assert router.chiamate == []


def test_l_aiuto_nomina_il_profilo() -> None:
    assert "/profilo" in risposte.aiuto().testo


@pytest.mark.parametrize(
    ("nome", "argomento"), [("si", 999999), ("no", 999999), ("scarta", 999999), ("indietro", "")]
)
def test_i_callback_data_stanno_nel_limite(nome: str, argomento: object) -> None:
    assert len(azioni.profilo(nome, argomento).encode()) <= 64  # type: ignore[arg-type]
