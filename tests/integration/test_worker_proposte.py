"""Il job che ti propone una regola (§6, §8.10).

Il rilevatore prova *quali* pattern reggono, e lo fa senza database. Il router
prova come si rilegge la risposta del modello, e lo fa senza rete. Qui si prova
quello che né l'uno né l'altro possono sapere: che le **quattro valvole** siano
in fila nell'ordine giusto e che il costo caschi dalla parte giusta — cioè che
il modello non venga chiamato quando la coda è piena, quando non c'è nessun
candidato, o quando quel pattern l'avevi già scartato.

E soprattutto: che una proposta scritta qui sia **la stessa regola** che il
motore di §8.10 saprebbe far scattare il giorno che la approvi. È il punto di
tutta la scelta di non aggiungere un quarto trigger, e senza questo test resta
un'affermazione nel commento di una migrazione.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from custode_bot.risposte import Risposta
from custode_core.db import connessione
from custode_core.dominio import pattern as dom_pattern
from custode_core.dominio import regole as dom
from custode_core.migrazioni import migra
from custode_router.errori import ProviderNonRaggiungibile
from custode_worker import proposte as job

pytestmark = pytest.mark.integration

# Un lunedì mattina: il job gira la sera, ma l'ora del giro non conta qui —
# conta la finestra di storico, che finisce ieri.
ORA = datetime(2026, 9, 14, 21, 0)


class TelegramFinto:
    def __init__(self, errore: Exception | None = None) -> None:
        self.errore = errore
        self.mandati: list[Risposta] = []

    def manda(self, risposta: Risposta) -> None:
        if self.errore is not None:
            raise self.errore
        self.mandati.append(risposta)


class RouterFinto:
    """Un router che risponde quello che gli si dice, e conta le chiamate.

    Le chiamate contate sono il punto di metà di questi test: le valvole
    esistono per non pagarne nemmeno una quando non serve.
    """

    def __init__(self, risposta: dict[str, Any] | None = None, errore: Exception | None = None):
        self.risposta = risposta or {"proposte": []}
        self.errore = errore
        self.chiamate = 0
        self.configurato = True

    def configurato_per(self, _compito: Any) -> bool:
        return self.configurato

    def chiedi_json(self, _compito: Any, **_kwargs: Any) -> dict[str, Any]:
        self.chiamate += 1
        if self.errore is not None:
            raise self.errore
        return self.risposta


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    with connessione(db_path) as aperta:
        migra(aperta)
        yield aperta


def _storico_palestra(conn: sqlite3.Connection) -> None:
    """Otto settimane di «creatina nei giorni di palestra», scritte davvero.

    Le righe passano dalle tabelle vere e non da un finto in memoria: è ciò che
    fa esercitare a questo test anche le due letture di `pattern`, comprese le
    esclusioni (eventi di giornata, tipo `altro`, tipi archiviati) che una
    finzione salterebbe.
    """
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
    conn.executemany(
        "INSERT INTO habit_logs (habit_id, data, fatto, creato_il) VALUES (1, ?, 1, ?)",
        [(g.isoformat(), datetime.combine(g, time(20, 0)).isoformat()) for g in giorni],
    )


def _risposta(**campi: Any) -> dict[str, Any]:
    voce: dict[str, Any] = {
        "n": 1,
        "proponi": True,
        "confidenza": "alta",
        "messaggio": "prendi la creatina",
        "motivazione": "15 giornate con palestra su 16, e quasi mai negli altri giorni.",
        "quando": "dopo",
        "minuti": 0,
    }
    voce.update(campi)
    return {"proposte": [voce]}


# — il giro che funziona —


def test_scrive_la_proposta_e_te_la_manda(conn: sqlite3.Connection) -> None:
    _storico_palestra(conn)
    router = RouterFinto(_risposta())
    telegram = TelegramFinto()

    esito = job.esegui(conn, ORA, router=router, telegram=telegram)  # type: ignore[arg-type]

    assert esito.proposta is not None
    scritta = dom.per_id(conn, esito.proposta.id)
    assert scritta.stato is dom.Stato.PROPOSTA
    assert scritta.origine is dom.Origine.IA
    assert scritta.trigger is dom.Trigger.DOPO_EVENTO
    assert scritta.tipo_evento == "palestra"
    assert scritta.messaggio == "prendi la creatina"
    assert scritta.confidenza is dom.Confidenza.ALTA
    assert scritta.motivazione is not None

    assert len(telegram.mandati) == 1
    assert "prendi la creatina" in telegram.mandati[0].testo
    # I bottoni ci sono: senza, l'unico posto per rispondere sarebbe una pagina
    # che oggi si apre solo dal Pi.
    assert [b.testo for riga in telegram.mandati[0].bottoni for b in riga] == [
        "✅ Approva",
        "Scarta",
    ]


def test_una_proposta_approvata_e_una_regola_che_scatta_davvero(conn: sqlite3.Connection) -> None:
    """Il punto di tutta la scelta di non aggiungere un quarto trigger.

    La proposta nasce con un trigger concreto, quindi il valutatore già scritto
    e già provato la fa scattare il giorno che la approvi — senza un secondo
    valutatore da costruire. Qui si verifica sul serio, con `dovute()`.
    """
    _storico_palestra(conn)
    job.esegui(conn, ORA, router=RouterFinto(_risposta()), telegram=TelegramFinto())  # type: ignore[arg-type]
    proposta = dom.in_attesa(conn)[0]

    # Finché è una proposta, non scatta: `dovute()` guarda solo le attive.
    fine_palestra = datetime(2026, 9, 15, 19, 30)
    evento = dom.EventoInCalendario(
        id=1, tipo="palestra", inizio=fine_palestra - timedelta(minutes=90), fine=fine_palestra
    )
    assert dom.dovute([proposta], fine_palestra, eventi=[evento]) == []

    approvata = dom.imposta_stato(conn, proposta.id, dom.Stato.ATTIVA)
    scatti = dom.dovute([approvata], fine_palestra, eventi=[evento])

    assert len(scatti) == 1
    assert scatti[0].regola.messaggio == "prendi la creatina"


def test_un_invio_fallito_non_butta_via_la_proposta(conn: sqlite3.Connection) -> None:
    """La riga resta e la pagina la mostra: a saltare è solo l'annuncio.

    Riproporla domani vorrebbe dire due righe uguali in coda per un guasto di
    rete di trenta secondi — il verso opposto al promemoria, che invece si perde
    apposta.
    """
    from custode_worker.telegram import InvioNonRiuscito

    _storico_palestra(conn)
    telegram = TelegramFinto(InvioNonRiuscito("niente rete"))

    esito = job.esegui(conn, ORA, router=RouterFinto(_risposta()), telegram=telegram)  # type: ignore[arg-type]

    assert esito.proposta is not None
    assert len(dom.in_attesa(conn)) == 1


# — le valvole, in ordine di quanto costano —


def test_senza_chiave_il_modulo_e_spento_non_rotto(conn: sqlite3.Connection) -> None:
    _storico_palestra(conn)
    router = RouterFinto()
    router.configurato = False

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert esito.spento is True
    assert router.chiamate == 0


def test_le_proposte_scadono_anche_a_modulo_spento(conn: sqlite3.Connection) -> None:
    """La scadenza viene prima di tutto: non ha bisogno di nessun modello, e
    lasciare marcire una coda perché manca una chiave sarebbe il peggio dei due
    mondi."""
    dom.crea_a_orario(
        conn,
        ora="19:00",
        messaggio="prendi la creatina",
        creata_il=ORA - timedelta(days=dom.GIORNI_SCADENZA_PROPOSTA + 1),
        origine=dom.Origine.IA,
        stato=dom.Stato.PROPOSTA,
        confidenza=dom.Confidenza.MEDIA,
        motivazione="un pattern di due mesi fa.",
    )
    router = RouterFinto()
    router.configurato = False

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert esito.scadute == 1
    assert dom.in_attesa(conn) == []


def test_con_la_coda_piena_non_si_chiama_nessuno(conn: sqlite3.Connection) -> None:
    """La valvola: se non decidi, Custode smette di chiedere invece di accumulare."""
    _storico_palestra(conn)
    for n in range(dom.MAX_PROPOSTE_IN_ATTESA):
        dom.crea_a_orario(
            conn,
            ora=f"{8 + n:02d}:00",
            messaggio=f"una cosa numero {n}",
            creata_il=ORA,
            origine=dom.Origine.IA,
            stato=dom.Stato.PROPOSTA,
            confidenza=dom.Confidenza.MEDIA,
            motivazione="perché sì.",
        )
    router = RouterFinto(_risposta())

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert router.chiamate == 0
    assert esito.proposta is None
    assert esito.in_coda == dom.MAX_PROPOSTE_IN_ATTESA


def test_senza_storico_non_si_chiama_nessuno(conn: sqlite3.Connection) -> None:
    """Il caso di quasi tutte le notti, ed è la ragione per cui la soglia sta in
    codice prima della chiamata."""
    router = RouterFinto(_risposta())

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert router.chiamate == 0
    assert esito.candidati == 0


def test_un_pattern_gia_scartato_non_costa_una_chiamata(conn: sqlite3.Connection) -> None:
    """§8.10 promette che una scartata non si riproponga, e mantenerlo **prima**
    della chiamata è anche ciò che la rende gratis."""
    _storico_palestra(conn)
    scartata = dom.crea_da_evento(
        conn,
        trigger=dom.Trigger.PRIMA_EVENTO,
        tipo_evento="palestra",
        minuti=45,
        messaggio="prendi la creatina",
        creata_il=ORA - timedelta(days=3),
    )
    dom.imposta_stato(conn, scartata.id, dom.Stato.SCARTATA)
    router = RouterFinto(_risposta())

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert router.chiamate == 0
    assert esito.gia_visti == 1
    assert esito.proposta is None


def test_il_modello_puo_non_proporre_niente(conn: sqlite3.Connection) -> None:
    _storico_palestra(conn)
    router = RouterFinto(_risposta(proponi=False, confidenza="bassa"))

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert router.chiamate == 1
    assert esito.proposta is None
    assert esito.scartate_dal_modello == 1
    assert dom.in_attesa(conn) == []


def test_un_messaggio_che_somiglia_a_una_regola_che_hai_gia_non_si_scrive(
    conn: sqlite3.Connection,
) -> None:
    """Il secondo controllo, dopo la chiamata.

    Il candidato era nuovo — l'abitudine si chiama «Creatina» e la regola che
    hai parla di «integratore» — ma il messaggio che Claude ha scritto dice la
    stessa cosa di quella. Senza questo controllo ti arriverebbe una proposta
    per una regola che hai già attiva.
    """
    _storico_palestra(conn)
    dom.crea_da_evento(
        conn,
        trigger=dom.Trigger.DOPO_EVENTO,
        tipo_evento="palestra",
        minuti=0,
        messaggio="bevi lo shaker di proteine",
        creata_il=ORA - timedelta(days=3),
    )
    router = RouterFinto(_risposta(messaggio="bevi lo shaker di proteine"))

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert router.chiamate == 1
    assert esito.proposta is None
    assert dom.in_attesa(conn) == []


def test_un_guasto_del_modello_torna_nell_esito(conn: sqlite3.Connection) -> None:
    """Non solleva: un'eccezione che sfugge fermerebbe anche i job che vengono
    dopo nello stesso giro, e una proposta non è più importante del backup."""
    _storico_palestra(conn)
    router = RouterFinto(errore=ProviderNonRaggiungibile("Claude non risponde"))

    esito = job.esegui(conn, ORA, router=router, telegram=TelegramFinto())  # type: ignore[arg-type]

    assert esito.errore is not None
    assert esito.proposta is None


# — la finestra di storico —


def test_la_finestra_non_conta_la_giornata_in_corso(conn: sqlite3.Connection) -> None:
    """A mezzanotte e mezza non hai ancora segnato niente: contare oggi
    abbasserebbe ogni copertura di una giornata mancata che non è mancata."""
    da, a = dom_pattern.finestra(ORA.date())

    assert a == ORA.date() - timedelta(days=1)
    assert da == date(2026, 7, 20)
