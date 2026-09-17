"""Le auto-proposte dallo storico alla pagina, con l'SDK vero (§6, §8.10).

Gli altri test del modulo sostituiscono il router: qui no. Il `Router` è quello
di produzione, `ClientClaude` è quello di produzione, l'SDK `anthropic` è quello
vero e parla HTTP con `finto_anthropic` — la stessa idea di `finto_google`, e
per la stessa ragione. Quello che si prova qui non lo prova nient'altro:

- che il compito finisca davvero su **Claude** e non su DeepSeek, cioè che la
  riga di §6 sia cablata e non solo scritta;
- **cosa** arriva al modello: il modello configurato, lo schema JSON in
  `output_config`, e i numeri del pattern dentro al messaggio — se i conti non
  ci arrivassero, la motivazione che leggi in pagina sarebbe un'impressione;
- che una risposta vera risalga tutta la catena fino a una riga in tabella e a
  un messaggio su Telegram.

Non serve nessuna chiave: `ROUTER_ANTHROPIC_API_KEY` è una stringa qualunque,
perché a controllarla sarebbe il server vero e qui il server è finto.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pytest

from custode_bot.risposte import Risposta
from custode_core.db import connessione
from custode_core.dominio import pattern as dom_pattern
from custode_core.dominio import regole as dom
from custode_core.migrazioni import migra
from custode_router import Router
from custode_router.config import ImpostazioniRouter
from custode_worker import proposte as job
from tests.integration.finto_anthropic import FintoAnthropic

pytestmark = pytest.mark.integration

ORA = datetime(2026, 9, 14, 21, 0)


class TelegramFinto:
    def __init__(self) -> None:
        self.mandati: list[Risposta] = []

    def manda(self, risposta: Risposta) -> None:
        self.mandati.append(risposta)


@pytest.fixture
def finto() -> Iterator[FintoAnthropic]:
    server = FintoAnthropic()
    yield server
    server.chiudi()


@pytest.fixture
def router(finto: FintoAnthropic, monkeypatch: pytest.MonkeyPatch) -> Router:
    """Il `Router` di produzione, con l'SDK puntato al finto server.

    `ANTHROPIC_BASE_URL` la legge l'SDK e non il progetto: non c'è quindi niente
    da cambiare in `custode_router.config` per deviarlo, ed è la ragione per cui
    questo test sta esercitando il client vero e non una sua variante.
    """
    monkeypatch.setenv("ANTHROPIC_BASE_URL", finto.base)
    return Router(ImpostazioniRouter(anthropic_api_key="non-serve-che-sia-vera"))


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    with connessione(db_path) as aperta:
        migra(aperta)
        yield aperta


def _storico(conn: sqlite3.Connection) -> int:
    """Otto settimane di «creatina nei giorni di palestra». Ritorna le occasioni."""
    conn.execute(
        "INSERT INTO habits (id, nome, frequenza_target_settimanale, attivo, creato_il)"
        " VALUES (1, 'Creatina', 2, 1, '2026-07-01T08:00:00')"
    )
    da, a = dom_pattern.finestra(ORA.date())
    giorni = [g for g in dom_pattern.giorni_fra(da, a) if g.isoweekday() in (2, 4)]
    conn.executemany(
        "INSERT INTO calendar_events (fonte, id_esterno, titolo, inizio, fine,"
        " tutto_il_giorno, luogo, serie_id, tipo, sincronizzato_il)"
        " VALUES ('google', ?, 'Palestra', ?, ?, 0, '', 'serie-pal', 'palestra',"
        " '2026-09-14T08:00:00')",
        [
            (
                f"ev{i}",
                datetime.combine(g, time(18, 0)).isoformat(),
                datetime.combine(g, time(19, 30)).isoformat(),
            )
            for i, g in enumerate(giorni)
        ],
    )
    # Una saltata: un pattern vero non è mai perfetto, e il numero che il
    # modello riceve deve essere quello vero.
    conn.executemany(
        "INSERT INTO habit_logs (habit_id, data, fatto, creato_il) VALUES (1, ?, 1, ?)",
        [(g.isoformat(), datetime.combine(g, time(20, 0)).isoformat()) for g in giorni[:-1]],
    )
    return len(giorni)


RISPOSTA: dict[str, Any] = {
    "proposte": [
        {
            "n": 1,
            "proponi": True,
            "confidenza": "alta",
            "messaggio": "prendi la creatina",
            "motivazione": "In 15 delle 16 giornate con palestra l'hai segnata.",
            "quando": "dopo",
            "minuti": 0,
        }
    ]
}


def test_dallo_storico_alla_riga_in_tabella(
    conn: sqlite3.Connection, router: Router, finto: FintoAnthropic
) -> None:
    occasioni = _storico(conn)
    finto.stato.risposta = RISPOSTA
    telegram = TelegramFinto()

    esito = job.esegui(conn, ORA, router=router, telegram=telegram)

    assert esito.errore is None
    assert esito.proposta is not None
    scritta = dom.per_id(conn, esito.proposta.id)
    assert scritta.stato is dom.Stato.PROPOSTA
    assert scritta.origine is dom.Origine.IA
    assert scritta.trigger is dom.Trigger.DOPO_EVENTO
    assert scritta.tipo_evento == "palestra"
    assert scritta.confidenza is dom.Confidenza.ALTA
    assert len(telegram.mandati) == 1

    # — cosa è arrivato al modello —
    assert len(finto.stato.richieste) == 1
    richiesta = finto.stato.richieste[0]
    # §6 manda questo compito a Claude: se finisse su DeepSeek, questo server
    # non riceverebbe niente e la riga della tabella sarebbe solo scritta.
    assert richiesta["model"] == "claude-opus-5"
    # Lo schema è quello dello structured output, non una richiesta nel prompt.
    assert richiesta["output_config"]["format"]["type"] == "json_schema"
    assert "proposte" in richiesta["output_config"]["format"]["schema"]["properties"]
    # E i conti veri, senza i quali la motivazione sarebbe un'impressione.
    domanda = richiesta["messages"][0]["content"]
    assert f"{occasioni} giornate" in domanda
    assert f"{occasioni - 1} di quelle" in domanda
    assert "«Creatina»" in domanda and "«palestra»" in domanda


def test_una_risposta_non_in_json_non_scrive_niente(
    conn: sqlite3.Connection, router: Router, finto: FintoAnthropic
) -> None:
    """Il caso che nessun router finto può produrre: il modello parla in
    italiano invece che in JSON. Deve tornare come errore dell'esito, non come
    eccezione che ferma i job che vengono dopo nello stesso giro."""
    _storico(conn)
    finto.stato.testo_grezzo = "Mi sembra una buona idea, sì."

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())

    assert esito.errore is not None
    assert dom.in_attesa(conn) == []


def test_un_rifiuto_del_modello_non_e_un_guasto_di_rete(
    conn: sqlite3.Connection, router: Router, finto: FintoAnthropic
) -> None:
    """`stop_reason: refusal` è una decisione, non una rete che non va: se i due
    si confondessero, il worker riproverebbe all'infinito."""
    _storico(conn)
    finto.stato.stop_reason = "refusal"

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())

    assert esito.errore is not None
    assert "rifiutato" in esito.errore


def test_claude_giu_lascia_lo_storico_dov_era(
    conn: sqlite3.Connection, router: Router, finto: FintoAnthropic
) -> None:
    """Non si segna niente: il pattern c'è ancora domani, al contrario di un
    promemoria, che passata la sua finestra è perso."""
    _storico(conn)
    finto.stato.stato = 500

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())

    assert esito.errore is not None
    assert esito.candidati == 1
    assert dom.in_attesa(conn) == []
