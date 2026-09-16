"""La pagina Calendario (§8.10): `GET /api/calendario`, `PATCH /api/calendario/{id}`.

L'API vera su un database vero, come `test_home_calendario.py`. Il calendario è
collegato per quasi tutto il file — è lo stato in cui la pagina ha qualcosa da
dire; il caso scollegato ha i suoi test in fondo, perché è l'unico in cui la
pagina deve dire una cosa diversa invece di dire meno.

Il job non gira qui: gli eventi arrivano in archivio come ce li lascia lui, e i
tag come li lascia il tagging. Quello che si prova è cosa la pagina ne fa —
soprattutto le tre risposte a «cosa ha capito», che sono la ragione di questa
pagina: da guardare, proposto dall'IA, corretto da te.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import SettingsConfigDict

from custode_calendario.config import ImpostazioniCalendario
from custode_calendario.evento import Evento
from custode_core.db import connessione
from custode_core.dominio import calendario as dom
from custode_core.registro_job import SYNC_CALENDARIO, segna_eseguito

pytestmark = pytest.mark.integration

# Lunedì 31 agosto 2026, 08:41 — la stessa ora fissa delle altre fixture.
ORA_DI_TEST = datetime(2026, 8, 31, 8, 41)
OGGI = ORA_DI_TEST.date()


@pytest.fixture
def calendario() -> ImpostazioniCalendario:
    """Calendario collegato: è lo stato in cui la pagina mostra qualcosa."""

    class _Collegato(ImpostazioniCalendario):
        model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")

    return _Collegato(client_id="id", client_secret="segreto", refresh_token="refresh")


def _evento(
    identificativo: str,
    titolo: str,
    ora_inizio: int = 9,
    ore: int = 2,
    giorno: date = OGGI,
    **extra: Any,
) -> Evento:
    inizio = datetime.combine(giorno, time(ora_inizio, 0))
    return Evento(
        id=identificativo,
        titolo=titolo,
        inizio=inizio,
        fine=inizio + timedelta(hours=ore),
        **extra,
    )


def _sincronizza(db_path: Path, eventi: list[Evento]) -> None:
    """Quello che avrebbe lasciato il worker, scritto sul database."""
    with connessione(db_path) as conn:
        dom.sincronizza(
            conn,
            eventi,
            da=OGGI - timedelta(days=7),
            a=OGGI + timedelta(days=14),
            ora=ORA_DI_TEST,
        )
        segna_eseguito(conn, SYNC_CALENDARIO, ORA_DI_TEST, ORA_DI_TEST)


def _tagga(db_path: Path, serie: str, tipo: str, *, evento_id: int | None = None) -> None:
    """Quello che avrebbe lasciato il tagging: una proposta, non una conferma."""
    with connessione(db_path) as conn:
        dom.applica_tag(
            conn,
            dom.GruppoDaTaggare(
                fonte=dom.FONTE_GOOGLE, serie_id=serie, evento_id=evento_id, titolo=""
            ),
            tipo,
            ORA_DI_TEST,
        )


def _eventi(corpo: dict[str, Any]) -> list[dict[str, Any]]:
    return [evento for giorno in corpo["giorni"] for evento in giorno["eventi"]]


# — cosa si vede ————————————————————————————————————————


def test_la_settimana_mostra_tutti_e_sette_i_giorni(client: TestClient, db_path: Path) -> None:
    """Sette righe si leggono, e un giorno libero è un'informazione."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II")])

    corpo = client.get("/api/calendario?vista=settimana").json()

    assert len(corpo["giorni"]) == 7
    assert corpo["giorni"][0]["label"] == "Lun 31 agosto"
    assert corpo["giorni"][0]["isOggi"] is True
    assert corpo["giorni"][1]["notaVuoto"] == "Niente in programma."
    assert corpo["periodoLabel"] == "31 agosto – 6 settembre"


def test_il_mese_manda_solo_i_giorni_che_hanno_qualcosa(client: TestClient, db_path: Path) -> None:
    """Trenta righe «niente in programma» non direbbero niente."""
    _sincronizza(
        db_path,
        [
            _evento("g-1", "Analisi II"),
            _evento("g-2", "Palestra", 18, giorno=OGGI - timedelta(days=2)),
        ],
    )

    corpo = client.get("/api/calendario?vista=mese").json()

    # Il mese è quello corrente, come nel diario e nelle spese: il 2 settembre
    # non ci sta, ed è la ragione per cui esiste `orizzonteLabel`.
    assert [g["label"] for g in corpo["giorni"]] == ["Sab 29 agosto", "Lun 31 agosto"]
    assert corpo["periodoLabel"] == "agosto"


def test_un_evento_lungo_compare_in_ogni_giorno_che_occupa(
    client: TestClient, db_path: Path
) -> None:
    """Un viaggio partito venerdì è un impegno anche di sabato."""
    _sincronizza(db_path, [_evento("g-viaggio", "Viaggio a Roma", 7, ore=72)])

    corpo = client.get("/api/calendario?vista=settimana").json()

    giorni_con_viaggio = [g["label"] for g in corpo["giorni"] if g["eventi"]]
    assert len(giorni_con_viaggio) == 4
    # Nel giorno di mezzo l'ora d'inizio è di un altro giorno: non si mostra.
    assert corpo["giorni"][1]["eventi"][0]["ora"] == "—"
    assert corpo["giorni"][1]["eventi"][0]["meta"] == "in corso"


# — cosa ha capito ——————————————————————————————————————


def test_un_evento_che_nessuno_ha_guardato_lo_dice(client: TestClient, db_path: Path) -> None:
    """È il minuto fra il sync e il tagging — o tutto il tempo senza chiave."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II")])

    (evento,) = _eventi(client.get("/api/calendario?vista=settimana").json())

    assert evento["tipo"] == "altro"
    assert evento["statoTag"] == "da_guardare"
    assert evento["statoTagLabel"] == "da guardare"


def test_una_proposta_dell_ia_si_distingue_da_una_tua_correzione(
    client: TestClient, db_path: Path
) -> None:
    """La distinzione è tutto il senso della pagina: «altro» è anche un esito."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II", serie_id="serie-an")])
    _tagga(db_path, "serie-an", "altro")

    (evento,) = _eventi(client.get("/api/calendario?vista=settimana").json())
    assert evento["tipo"] == "altro"
    assert evento["statoTagLabel"] == "proposto dall'IA"

    client.patch(f"/api/calendario/{evento['id']}", json={"tipo": "lezione"})

    (dopo,) = _eventi(client.get("/api/calendario?vista=settimana").json())
    assert dopo["tipo"] == "lezione"
    assert dopo["tipoLabel"] == "Lezione"
    assert dopo["statoTagLabel"] == "corretto da te"


def test_gli_impegni_senza_tipo_si_contano_da_oggi_in_poi(
    client: TestClient, db_path: Path
) -> None:
    """Un impegno di marzo senza tipo non è una cosa da sbrigare.

    Lo stesso filtro della coda «da rivedere», e per la stessa ragione: un
    contatore che non scende mai è un contatore che si smette di guardare — e
    l'archivio del passato non si tagga per l'utente, si tagga per il motore
    di contesto, che è un'altra cosa e non ha una casella in cima alla pagina.
    """
    _sincronizza(
        db_path,
        [
            _evento("g-vecchio", "Analisi I", giorno=OGGI - timedelta(days=5)),
            _evento("g-nuovo", "Analisi II", giorno=OGGI + timedelta(days=3)),
        ],
    )

    corpo = client.get("/api/calendario?vista=settimana").json()

    assert corpo["stats"]["daGuardare"] == 1
    assert corpo["daGuardareLabel"] == (
        "1 impegno non ha ancora un tipo: Custode lo guarda al prossimo giro,"
        " entro cinque minuti."
    )


def test_la_frase_su_cosa_manca_concorda_col_numero(client: TestClient, db_path: Path) -> None:
    """«1 impegno … Custode li guarda» si legge come una frase generata.

    È quello che viene da sé mettendo insieme un `plurale()` e una coda scritta
    al plurale: il numero concorda e il pronome no.
    """
    _sincronizza(
        db_path,
        [
            _evento("g-1", "Ricevimento", giorno=OGGI + timedelta(days=1)),
            _evento("g-2", "Dentista", giorno=OGGI + timedelta(days=2)),
        ],
    )

    corpo = client.get("/api/calendario?vista=settimana").json()

    assert corpo["daGuardareLabel"] == (
        "2 impegni non hanno ancora un tipo: Custode li guarda al prossimo giro,"
        " entro cinque minuti."
    )


def test_senza_la_chiave_del_modello_la_pagina_non_promette_un_attesa(
    client: TestClient, db_path: Path, modello: Any
) -> None:
    """«Li guarda entro cinque minuti» è vero solo se qualcuno li guarda.

    Senza `ROUTER_DEEPSEEK_API_KEY` il tagging è spento: quel numero non scende
    mai, e la frase resterebbe lì a promettere un'attesa che non finisce. Chi
    legge non ha modo di distinguere i due casi — l'unico che lo sa è il
    backend.
    """
    modello.compiti_accesi = False
    _sincronizza(db_path, [_evento("g-1", "Analisi II")])

    corpo = client.get("/api/calendario?vista=settimana").json()

    assert corpo["stats"]["daGuardare"] == 1
    assert corpo["daGuardareLabel"] is not None
    assert "ROUTER_DEEPSEEK_API_KEY" in corpo["daGuardareLabel"]
    assert "cinque minuti" not in corpo["daGuardareLabel"]


def test_senza_niente_da_guardare_la_frase_si_omette(client: TestClient, db_path: Path) -> None:
    """Campo assente ≠ campo vuoto (§5 del contratto)."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II", serie_id="serie-an")])
    _tagga(db_path, "serie-an", "lezione")

    corpo = client.get("/api/calendario?vista=settimana").json()

    assert corpo["stats"]["daGuardare"] == 0
    assert "daGuardareLabel" not in corpo


def test_i_tipi_arrivano_dal_backend(client: TestClient) -> None:
    """Il menu di correzione non se li scrive in casa (contratto, §Etichette).

    E all'inizio sono i quattro della migrazione 009, nell'ordine in cui li
    semina, con `altro` ultimo perché è il ripiego.
    """
    corpo = client.get("/api/calendario?vista=settimana").json()

    assert [(t["valore"], t["label"]) for t in corpo["tipi"]] == [
        ("lezione", "Lezione"),
        ("palestra", "Palestra"),
        ("viaggio", "Viaggio"),
        ("altro", "Altro"),
    ]
    # La descrizione è quella che legge il modello: esce anche di qui, perché è
    # da qui che si modifica.
    assert corpo["tipi"][0]["descrizione"].startswith("l'università")
    assert [t["diSistema"] for t in corpo["tipi"]] == [False, False, False, True]


# — da rivedere —————————————————————————————————————————


def test_da_rivedere_mostra_una_riga_per_serie(client: TestClient, db_path: Path) -> None:
    """Dodici occorrenze sarebbero dodici volte la stessa correzione."""
    _sincronizza(
        db_path,
        [
            _evento("g-1", "Analisi II", serie_id="serie-an"),
            _evento("g-2", "Analisi II", giorno=OGGI + timedelta(days=7), serie_id="serie-an"),
            _evento("g-3", "Dentista", 15, giorno=OGGI + timedelta(days=1)),
        ],
    )
    _tagga(db_path, "serie-an", "lezione")
    _tagga(db_path, "", "altro", evento_id=3)

    corpo = client.get("/api/calendario?vista=da_rivedere").json()

    assert [r["titolo"] for r in corpo["daRivedere"]] == ["Analisi II", "Dentista"]
    analisi, dentista = corpo["daRivedere"]
    assert analisi["quandoLabel"] == "oggi alle 09:00"
    assert analisi["occorrenzeLabel"] == "2 occorrenze in calendario"
    assert analisi["serie"] is True
    assert analisi["propostoLabel"] == "proposto oggi"
    # Un evento singolo non ha occorrenze da contare: il campo non c'è.
    assert "occorrenzeLabel" not in dentista
    assert dentista["serie"] is False


def test_da_rivedere_conta_gli_impegni_da_oggi_in_poi(client: TestClient, db_path: Path) -> None:
    """«Impegni nel periodo: 0» accanto a una coda piena si leggerebbe male.

    La vista non disegna giorni, ma un periodo ce l'ha: da oggi a dove arriva
    la finestra sincronizzata.
    """
    _sincronizza(
        db_path,
        [
            _evento("g-1", "Analisi II"),
            _evento("g-2", "Palestra", 18, giorno=OGGI + timedelta(days=3)),
            _evento("g-vecchio", "Lezione di ieri", giorno=OGGI - timedelta(days=1)),
        ],
    )
    _tagga(db_path, "", "lezione", evento_id=1)

    corpo = client.get("/api/calendario?vista=da_rivedere").json()

    # Ieri non conta: la vista parla di quello che deve ancora succedere.
    assert corpo["stats"]["eventiPeriodo"] == 2
    assert corpo["periodoLabel"] == "da oggi in poi"


def test_quello_che_hai_gia_corretto_esce_dalla_coda(client: TestClient, db_path: Path) -> None:
    _sincronizza(db_path, [_evento("g-1", "Analisi II", serie_id="serie-an")])
    _tagga(db_path, "serie-an", "lezione")
    (riga,) = client.get("/api/calendario?vista=da_rivedere").json()["daRivedere"]

    client.patch(f"/api/calendario/{riga['id']}", json={"tipo": "lezione"})

    corpo = client.get("/api/calendario?vista=da_rivedere").json()
    assert corpo["daRivedere"] == []
    assert corpo["notaVuoto"] == "Nessuna proposta da rivedere."


def test_confermare_lo_stesso_tipo_e_comunque_una_conferma(
    client: TestClient, db_path: Path
) -> None:
    """«Ha indovinato» è una risposta a «cosa ha capito», non un non-evento.

    Senza questo, l'unico modo di togliere dalla coda una proposta giusta
    sarebbe cambiarla in una sbagliata e poi rimetterla a posto.
    """
    _sincronizza(db_path, [_evento("g-1", "Analisi II", serie_id="serie-an")])
    _tagga(db_path, "serie-an", "lezione")
    (riga,) = client.get("/api/calendario?vista=da_rivedere").json()["daRivedere"]

    risposta = client.patch(f"/api/calendario/{riga['id']}", json={"tipo": "lezione"})

    assert risposta.json()["evento"]["statoTag"] == "corretto"
    assert client.get("/api/calendario?vista=da_rivedere").json()["daRivedere"] == []


def test_la_coda_non_dipende_dalla_vista(client: TestClient, db_path: Path) -> None:
    """Se «due da rivedere» sparisse guardando la settimana, non ci si arriverebbe."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II", giorno=OGGI + timedelta(days=10))])
    _tagga(db_path, "", "lezione", evento_id=1)

    corpo = client.get("/api/calendario?vista=settimana").json()

    # L'evento è fuori dalla settimana, ma la cosa da fare resta in cima.
    assert corpo["giorni"][0]["eventi"] == []
    assert corpo["stats"]["daRivedere"] == 1
    assert corpo["titolo"] == "1 proposta da rivedere."


# — la correzione ———————————————————————————————————————


def test_correggere_un_occorrenza_corregge_tutta_la_serie(
    client: TestClient, db_path: Path
) -> None:
    """Correggere il martedì e lasciare sbagliati gli altri martedì non regge."""
    _sincronizza(
        db_path,
        [
            _evento("g-1", "Analisi II", serie_id="serie-an"),
            _evento("g-2", "Analisi II", giorno=OGGI + timedelta(days=7), serie_id="serie-an"),
            _evento("g-3", "Analisi II", giorno=OGGI + timedelta(days=14), serie_id="serie-an"),
        ],
    )
    _tagga(db_path, "serie-an", "palestra")
    (riga,) = client.get("/api/calendario?vista=da_rivedere").json()["daRivedere"]

    risposta = client.patch(f"/api/calendario/{riga['id']}", json={"tipo": "lezione"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["occorrenze"] == 3
    assert corpo["label"] == "Corretto su 3 occorrenze della serie: lezione."
    assert corpo["evento"]["tipo"] == "lezione"

    del_mese = _eventi(client.get("/api/calendario?vista=mese").json())
    assert {e["tipo"] for e in del_mese} == {"lezione"}


def test_correggere_un_evento_singolo_non_parla_di_serie(client: TestClient, db_path: Path) -> None:
    _sincronizza(db_path, [_evento("g-1", "Dentista", 15)])

    (evento,) = _eventi(client.get("/api/calendario?vista=settimana").json())
    corpo = client.patch(f"/api/calendario/{evento['id']}", json={"tipo": "altro"}).json()

    assert corpo["occorrenze"] == 1
    assert corpo["label"] == "Corretto: altro."
    assert corpo["evento"]["serie"] is False


def test_correggere_un_evento_che_non_esiste_e_un_404(client: TestClient) -> None:
    risposta = client.patch("/api/calendario/999", json={"tipo": "lezione"})

    assert risposta.status_code == 404
    assert risposta.json()["detail"] == "Evento non trovato."


def test_un_tipo_inventato_non_entra_nel_database(client: TestClient, db_path: Path) -> None:
    """Le quattro caselle sono un vincolo dello schema, non una richiesta."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II")])
    (evento,) = _eventi(client.get("/api/calendario?vista=settimana").json())

    risposta = client.patch(f"/api/calendario/{evento['id']}", json={"tipo": "sport"})

    assert risposta.status_code == 422
    (dopo,) = _eventi(client.get("/api/calendario?vista=settimana").json())
    assert dopo["statoTag"] == "da_guardare"


# — i vuoti, che non si somigliano ——————————————————————


def test_collegato_ma_mai_sincronizzato_lo_dice(client: TestClient) -> None:
    """«Nessuna proposta da rivedere» a calendario appena collegato è falso."""
    corpo = client.get("/api/calendario?vista=da_rivedere").json()

    assert corpo["notaVuoto"] == "Non ho ancora sincronizzato nessun evento."


def test_sincronizzato_e_davvero_libero_dice_un_altra_cosa(
    client: TestClient, db_path: Path
) -> None:
    _sincronizza(db_path, [])

    corpo = client.get("/api/calendario?vista=settimana").json()

    assert corpo["notaVuoto"] == "Niente in programma."
    assert corpo["titolo"] == "Niente in programma."


def test_la_pagina_dice_fin_dove_arriva_il_calendario(client: TestClient, db_path: Path) -> None:
    """Un mese vuoto in fondo non vuol dire che quei giorni sono liberi."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II")])

    corpo = client.get("/api/calendario?vista=mese").json()

    assert corpo["orizzonteLabel"] == "Gli eventi arrivano fino al lun 14 settembre."


class TestScollegato:
    """Il calendario non collegato: la pagina esiste e spiega cosa manca."""

    @pytest.fixture
    def calendario(self) -> ImpostazioniCalendario:
        class _Scollegato(ImpostazioniCalendario):
            model_config = SettingsConfigDict(
                env_prefix="CALENDARIO_", env_file=None, extra="ignore"
            )

        return _Scollegato()

    def test_la_nota_dice_cosa_manca(self, client: TestClient) -> None:
        corpo = client.get("/api/calendario?vista=settimana").json()

        assert corpo["titolo"] == "Il calendario non è collegato."
        assert "non è collegato" in corpo["notaVuoto"]
        assert corpo["giorni"] == []
        # Non c'è niente di cui dire l'orizzonte: non si sincronizza niente.
        assert "orizzonteLabel" not in corpo

    def test_gli_eventi_rimasti_in_archivio_non_si_mostrano(
        self, client: TestClient, db_path: Path
    ) -> None:
        """Dopo aver tolto le credenziali, l'archivio resta ma è fermo: mostrarlo
        come «i tuoi impegni» direbbe che il calendario funziona."""
        _sincronizza(db_path, [_evento("g-1", "Analisi II")])

        corpo = client.get("/api/calendario?vista=settimana").json()

        assert corpo["giorni"] == []
        # E nemmeno nei numeri: un conteggio senza righe sotto sarebbe solo una
        # domanda senza risposta.
        assert corpo["stats"]["eventiPeriodo"] == 0

    def test_i_tipi_restano_e_si_gestiscono_lo_stesso(self, client: TestClient) -> None:
        """Sono il contratto della pagina, non un dato del calendario.

        E sono anche l'unica cosa che si può ancora sistemare mentre le
        credenziali mancano: il giorno che lo ricolleghi, il tagging parte già
        con i tipi giusti.
        """
        corpo = client.get("/api/calendario?vista=settimana").json()
        assert [t["valore"] for t in corpo["tipi"]] == ["lezione", "palestra", "viaggio", "altro"]

        risposta = client.post(
            "/api/calendario/tipi", json={"nome": "Spesa", "descrizione": "il supermercato."}
        )
        assert risposta.status_code == 200
        assert risposta.json()["tipo"]["valore"] == "spesa"


# — i tipi, adesso che li decidi tu (pezzo 6) ————————————


def _tipi(client: TestClient) -> list[dict[str, Any]]:
    return list(client.get("/api/calendario?vista=settimana").json()["tipi"])


def _tipo(client: TestClient, slug: str) -> dict[str, Any]:
    return next(t for t in _tipi(client) if t["valore"] == slug)


def test_un_tipo_nuovo_compare_subito_nel_menu(client: TestClient) -> None:
    """Creato da qui, usabile da qui: nessun riavvio, nessun deploy."""
    risposta = client.post(
        "/api/calendario/tipi",
        json={"nome": "Spesa", "descrizione": "il supermercato, non le uscite di denaro."},
    )

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["tipo"]["valore"] == "spesa"
    assert corpo["tipo"]["label"] == "Spesa"
    assert corpo["tipo"]["eliminabile"] is True
    assert "cinque minuti" in corpo["label"]
    assert [t["valore"] for t in _tipi(client)] == [
        "lezione",
        "palestra",
        "viaggio",
        "spesa",
        "altro",
    ]


def test_un_tipo_senza_descrizione_viene_rifiutato(client: TestClient) -> None:
    """È la riga che legge il modello: senza, la classificazione peggiora."""
    risposta = client.post("/api/calendario/tipi", json={"nome": "Spesa", "descrizione": "  "})

    assert risposta.status_code == 422
    assert "descrizione" in risposta.json()["detail"]


def test_un_nome_gia_usato_non_apre_un_doppione(client: TestClient) -> None:
    risposta = client.post(
        "/api/calendario/tipi", json={"nome": "palestra", "descrizione": "altro sport."}
    )

    assert risposta.status_code == 422
    assert "Palestra" in risposta.json()["detail"]


def test_rinominare_un_tipo_non_tocca_gli_eventi(client: TestClient, db_path: Path) -> None:
    """Il punto dello slug: gli impegni non portano scritta l'etichetta.

    Dopo la rinomina la pagina mostra il nome nuovo su un evento che nessuno ha
    riscritto — `tipo` è ancora `palestra`, ed è ciò che permette di rinominare
    senza toccare mille righe.
    """
    _sincronizza(db_path, [_evento("g-1", "Palestra", ora_inizio=18)])
    _tagga(db_path, "", "palestra", evento_id=1)

    risposta = client.patch("/api/calendario/tipi/palestra", json={"nome": "Allenamento"})

    assert risposta.status_code == 200
    assert "Nessun impegno è cambiato" in risposta.json()["label"]

    (evento,) = _eventi(client.get("/api/calendario?vista=settimana").json())
    assert evento["tipo"] == "palestra"
    assert evento["tipoLabel"] == "Allenamento"


def test_archiviare_un_tipo_lo_toglie_dal_menu_e_lo_lascia_sugli_eventi(
    client: TestClient, db_path: Path
) -> None:
    """Un impegno di ieri non cambia significato perché oggi hai cambiato idea."""
    _sincronizza(db_path, [_evento("g-1", "Palestra", ora_inizio=18)])
    _tagga(db_path, "", "palestra", evento_id=1)

    risposta = client.patch("/api/calendario/tipi/palestra", json={"attivo": False})

    assert risposta.status_code == 200
    assert "non comparirà più nel menu" in risposta.json()["label"]

    tipo = _tipo(client, "palestra")
    assert tipo["attivo"] is False
    assert "Archiviato" in tipo["notaLabel"]
    # L'etichetta si vede ancora: il menu la offre solo perché l'evento ce l'ha.
    (evento,) = _eventi(client.get("/api/calendario?vista=settimana").json())
    assert evento["tipoLabel"] == "Palestra"


def test_altro_non_si_archivia_e_la_pagina_lo_dice_prima(client: TestClient) -> None:
    """Il bottone non c'è, e `notaLabel` spiega perché invece di lasciarlo nudo."""
    assert _tipo(client, "altro")["diSistema"] is True
    assert "si rinomina, non si archivia" in _tipo(client, "altro")["notaLabel"]

    risposta = client.patch("/api/calendario/tipi/altro", json={"attivo": False})
    assert risposta.status_code == 409


def test_un_tipo_che_nessuno_usa_si_cancella(client: TestClient) -> None:
    client.post("/api/calendario/tipi", json={"nome": "Spesa", "descrizione": "il supermercato."})

    assert client.delete("/api/calendario/tipi/spesa").status_code == 204
    assert "spesa" not in [t["valore"] for t in _tipi(client)]


def test_un_tipo_in_uso_non_si_cancella_e_la_risposta_dice_cosa_fare(
    client: TestClient, db_path: Path
) -> None:
    """Un no senza alternativa è un vicolo cieco."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II"), _evento("g-2", "Analisi III", 14)])
    _tagga(db_path, "", "lezione", evento_id=1)
    _tagga(db_path, "", "lezione", evento_id=2)

    risposta = client.delete("/api/calendario/tipi/lezione")

    assert risposta.status_code == 409
    assert risposta.json()["detail"] == ("2 impegni lo usano: archivialo invece di cancellarlo.")
    assert _tipo(client, "lezione")["eliminabile"] is False


def test_riprendere_un_tipo_archiviato_invece_di_duplicarlo(
    client: TestClient, db_path: Path
) -> None:
    """`palestra` e `palestra_2` spaccherebbero in due gli impegni già taggati."""
    _sincronizza(db_path, [_evento("g-1", "Palestra", ora_inizio=18)])
    _tagga(db_path, "", "palestra", evento_id=1)
    client.patch("/api/calendario/tipi/palestra", json={"attivo": False})

    risposta = client.post(
        "/api/calendario/tipi", json={"nome": "Palestra", "descrizione": "allenamento e corsa."}
    )

    assert risposta.status_code == 200
    assert "Ripreso" in risposta.json()["label"]
    assert len([t for t in _tipi(client) if t["valore"].startswith("palestra")]) == 1
    (evento,) = _eventi(client.get("/api/calendario?vista=settimana").json())
    assert evento["tipo"] == "palestra"


def test_correggere_un_evento_con_un_tipo_tuo(client: TestClient, db_path: Path) -> None:
    """Il giro intero, dal contratto: creo un tipo e lo metto su un impegno."""
    _sincronizza(db_path, [_evento("g-1", "Carrefour", ora_inizio=17)])
    client.post("/api/calendario/tipi", json={"nome": "Spesa", "descrizione": "il supermercato."})

    risposta = client.patch("/api/calendario/1", json={"tipo": "spesa"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["evento"]["tipo"] == "spesa"
    assert corpo["evento"]["statoTag"] == "corretto"
    assert corpo["label"] == "Corretto: spesa."


def test_correggere_con_un_tipo_che_non_esiste(client: TestClient, db_path: Path) -> None:
    """422 e non 404: il 404 parlerebbe dell'evento nell'URL, che esiste."""
    _sincronizza(db_path, [_evento("g-1", "Analisi II")])

    risposta = client.patch("/api/calendario/1", json={"tipo": "inventato"})

    assert risposta.status_code == 422
    assert "inventato" in risposta.json()["detail"]


def test_un_tipo_che_non_esiste_da_404(client: TestClient) -> None:
    assert client.patch("/api/calendario/tipi/inventato", json={"nome": "X"}).status_code == 404
    assert client.delete("/api/calendario/tipi/inventato").status_code == 404


def test_la_nota_di_un_tipo_dice_sempre_quanti_impegni_lo_usano(
    client: TestClient, db_path: Path
) -> None:
    """Un numero nudo in un angolo non dice di cosa è il conto, e uno «0» meno.

    La riga c'è sempre, anche per un tipo che non usa nessuno: lì è la frase che
    spiega perché quel tipo, unico fra tutti, ha il bottone «Elimina».
    """
    _sincronizza(db_path, [_evento("g-1", "Analisi II")])
    _tagga(db_path, "", "lezione", evento_id=1)
    client.post("/api/calendario/tipi", json={"nome": "Spesa", "descrizione": "il supermercato."})

    assert _tipo(client, "lezione")["notaLabel"] == (
        "1 impegno lo usa: si archivia, non si cancella."
    )
    assert _tipo(client, "spesa")["notaLabel"] == (
        "Non lo usa nessun impegno: si può ancora cancellare."
    )
    assert _tipo(client, "palestra")["notaLabel"] == (
        "Non lo usa nessun impegno: si può ancora cancellare."
    )
