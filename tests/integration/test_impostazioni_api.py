"""La pagina Impostazioni (§8): `GET` e `PATCH /api/impostazioni`.

Tre cose si provano qui, e sono le tre ragioni per cui questo endpoint esiste
adesso e non dopo:

- il **budget** smette di essere una variabile d'ambiente, e il cambio si vede
  nella Home senza riavviare niente;
- `sistema.ultimoSyncCalendarioLabel` dice da quanto il calendario non si
  aggiorna — l'unico posto da cui si vede che il worker è fermo (§8.10);
- il **margine** di «sei probabilmente a casa» si salva, perché §8.10 lo vuole
  configurabile e chi lo leggerà arriva dopo.

E una quarta, che è la regola del contratto: quello che nessun modulo legge non
si manda affatto.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import SettingsConfigDict

from custode_bot.config import ImpostazioniBot
from custode_calendario.config import ImpostazioniCalendario
from custode_core.db import connessione
from custode_core.registro_job import BACKUP, SYNC_CALENDARIO, segna_eseguito

pytestmark = pytest.mark.integration

ORA_DI_TEST = datetime(2026, 8, 31, 8, 41)


def _get(client: TestClient) -> dict[str, Any]:
    risposta = client.get("/api/impostazioni")
    assert risposta.status_code == 200
    corpo: dict[str, Any] = risposta.json()
    return corpo


def _patch(client: TestClient, corpo: dict[str, Any]) -> Any:
    return client.patch("/api/impostazioni", json=corpo)


# — cosa c'è, e cosa non c'è —————————————————————————————


def test_la_pagina_manda_solo_quello_che_qualcuno_legge(client: TestClient) -> None:
    """Un interruttore che non interrompe niente è peggio di uno assente.

    Il contratto aveva questi campi da prima dei loro moduli: digest mattutino
    (§8.13), ora della voce di diario, ore di silenzio, le quattro approvazioni,
    il primo giorno della settimana. Nessuno è cablato a niente, quindi si
    omettono — è la regola già scritta in cima al contratto.
    """
    corpo = _get(client)

    assert set(corpo["orari"]) == {
        "riepilogoSettimanaleGiorno",
        "riepilogoSettimanaleOra",
        "checkInMinutiDopo",
    }
    assert "approvazioni" not in corpo
    assert "primaSettimana" not in corpo
    # Niente tetto mensile né soglia d'avviso: nessuna pagina li legge.
    assert set(corpo["budget"]) <= {"settimanale"}


def test_i_numeri_dei_dati_sono_veri(client: TestClient) -> None:
    corpo = _get(client)
    assert corpo["dati"]["vociDiario"] == 0
    assert corpo["dati"]["speseRegistrate"] == 0
    # `messaggiBot` non c'è: il bot non lascia traccia dei messaggi che non sono
    # materiale da diario, e contare quelli darebbe un numero che sembra una
    # risposta senza esserlo.
    assert "messaggiBot" not in corpo["dati"]


def test_le_connessioni_dicono_cosa_si_perde_quando_manca(client: TestClient) -> None:
    """«Telegram: non collegato» non aiuta nessuno; «senza, niente vocali» sì.

    La frase nomina la variabile che manca, non il suo valore: è la sola cosa
    che permette di rimettere in piedi la connessione senza cercare nei log del
    Pi, ed è anche il confine — il nome sì, il contenuto mai.
    """
    per_nome = {c["nome"]: c for c in _get(client)["connessioni"]}

    assert set(per_nome) == {"Telegram", "Google Calendar", "DeepSeek", "Claude"}
    assert per_nome["Telegram"]["stato"] == "non_collegato"
    assert per_nome["Google Calendar"]["stato"] == "non_collegato"
    assert "TELEGRAM_BOT_TOKEN" in per_nome["Telegram"]["dettaglio"]
    assert "CALENDARIO_CLIENT_ID" in per_nome["Google Calendar"]["dettaglio"]
    # Il modello finto dei test ha i compiti accesi: le due righe del router
    # seguono lui, non il `.env` della macchina.
    assert per_nome["DeepSeek"]["stato"] == "collegato"
    assert per_nome["Claude"]["stato"] == "collegato"


# — il `.env` come punto di partenza —————————————————————


class TestConBudgetNelEnv:
    """Un'installazione nata con `CUSTODE_BUDGET_SETTIMANALE` nel `.env`."""

    @pytest.fixture
    def budget(self) -> float:
        return 120.0

    def test_il_valore_del_env_si_vede_finche_non_scegli(self, client: TestClient) -> None:
        corpo = _get(client)
        assert corpo["budget"]["settimanale"] == 120.0
        assert "viene dal .env" in corpo["notaLabel"]

    def test_dal_primo_salvataggio_vince_quello_che_scegli(self, client: TestClient) -> None:
        _patch(client, {"budget": {"settimanale": 80}})

        corpo = _get(client)
        assert corpo["budget"]["settimanale"] == 80.0
        assert "budget" not in (corpo.get("notaLabel") or "")

    def test_svuotare_il_budget_non_riesuma_il_env(self, client: TestClient) -> None:
        """Altrimenti la pagina rifiuterebbe in silenzio quello che le hai chiesto."""
        risposta = _patch(client, {"budget": {"settimanale": None}})

        assert risposta.status_code == 200
        assert "settimanale" not in risposta.json()["budget"]
        assert "settimanale" not in _get(client)["budget"]

    def test_il_budget_cambia_la_home_senza_riavviare_niente(self, client: TestClient) -> None:
        """È la ragione per cui questo endpoint serviva adesso.

        La Home rilegge il budget ad ogni richiesta: fra la `PATCH` e il `GET`
        non è ripartito nessun container e nessun processo.
        """
        assert client.get("/api/home").json()["speseSettimana"]["budget"] == 120.0

        _patch(client, {"budget": {"settimanale": 250}})

        assert client.get("/api/home").json()["speseSettimana"]["budget"] == 250.0

    def test_togliere_il_budget_spegne_il_blocco_spese_della_home(self, client: TestClient) -> None:
        """§8.5: senza tetto la barra non si disegna, non si disegna a zero."""
        assert "speseSettimana" in client.get("/api/home").json()

        _patch(client, {"budget": {"settimanale": None}})

        assert "speseSettimana" not in client.get("/api/home").json()


def test_il_bot_scollegato_dice_cosa_manca(client: TestClient) -> None:
    assert "TELEGRAM_BOT_TOKEN" in _get(client)["botStatoLabel"]


def test_senza_budget_da_nessuna_parte_il_campo_e_assente(client: TestClient) -> None:
    corpo = _get(client)
    assert "settimanale" not in corpo["budget"]
    assert "non hai ancora cambiato niente" in corpo["notaLabel"].lower()


# — le modifiche —————————————————————————————————————


def test_una_patch_tocca_solo_quello_che_le_mandi(client: TestClient) -> None:
    """Un campo che non arriva è un campo che non volevi toccare.

    È la ragione per cui si guarda `model_fields_set` e non il valore: se
    l'assenza si confondesse con `null`, cambiare un orario cancellerebbe il
    budget.
    """
    _patch(client, {"budget": {"settimanale": 90}})

    _patch(client, {"orari": {"checkInMinutiDopo": 25}})

    corpo = _get(client)
    assert corpo["budget"]["settimanale"] == 90.0
    assert corpo["orari"]["checkInMinutiDopo"] == 25


def test_la_patch_risponde_con_la_pagina_intera(client: TestClient) -> None:
    risposta = _patch(client, {"orari": {"riepilogoSettimanaleGiorno": "lunedi"}})

    assert risposta.status_code == 200
    assert risposta.json()["orari"]["riepilogoSettimanaleGiorno"] == "lunedi"
    assert "sistema" in risposta.json()


def test_un_orario_si_normalizza_salvandolo(client: TestClient) -> None:
    risposta = _patch(client, {"orari": {"riepilogoSettimanaleOra": "9:5"}})
    assert risposta.json()["orari"]["riepilogoSettimanaleOra"] == "09:05"


@pytest.mark.parametrize(
    "corpo",
    [
        {"orari": {"riepilogoSettimanaleGiorno": "sabato"}},
        {"orari": {"riepilogoSettimanaleOra": "25:00"}},
        {"orari": {"checkInMinutiDopo": 5000}},
        {"budget": {"settimanale": -3}},
    ],
)
def test_un_valore_assurdo_risponde_422_e_dice_perche(
    client: TestClient, corpo: dict[str, Any]
) -> None:
    risposta = _patch(client, corpo)

    assert risposta.status_code == 422
    assert risposta.json()["detail"]


def test_un_valore_rifiutato_non_lascia_niente_a_meta(client: TestClient) -> None:
    """La `PATCH` di due campi, il secondo storto: il primo non deve restare.

    È lo stesso ragionamento delle migrazioni — o tutto o niente — e qui vale
    perché la connessione dell'API è in autocommit: senza una transazione
    esplicita il giorno si salverebbe e l'ora no, lasciando il riepilogo a
    un'ora che non hai scelto.
    """
    _patch(client, {"orari": {"riepilogoSettimanaleGiorno": "lunedi"}})

    risposta = _patch(
        client,
        {"orari": {"riepilogoSettimanaleGiorno": "domenica", "riepilogoSettimanaleOra": "99:99"}},
    )

    assert risposta.status_code == 422
    assert _get(client)["orari"]["riepilogoSettimanaleGiorno"] == "lunedi"


# — il worker fermo ————————————————————————————————————


def test_senza_sync_il_calendario_dice_mai(client: TestClient) -> None:
    assert _get(client)["sistema"]["ultimoSyncCalendarioLabel"] == "mai"
    assert _get(client)["dati"]["ultimoBackupLabel"] == "mai"


def test_un_worker_fermo_da_giorni_si_vede_da_qui(client: TestClient, db_path: Path) -> None:
    """Il caso che §8.10 lascia scoperto.

    La pagina Calendario direbbe «niente in programma», che rispetto
    all'archivio è pure vero: solo che l'archivio è di tre giorni fa.
    """
    with connessione(db_path) as conn:
        tre_giorni_fa = ORA_DI_TEST - timedelta(days=3)
        segna_eseguito(conn, SYNC_CALENDARIO, tre_giorni_fa, tre_giorni_fa)

    assert _get(client)["sistema"]["ultimoSyncCalendarioLabel"] == "3 giorni fa"


def test_un_worker_vivo_si_vede_in_minuti(client: TestClient, db_path: Path) -> None:
    with connessione(db_path) as conn:
        poco_fa = ORA_DI_TEST - timedelta(minutes=4)
        segna_eseguito(conn, SYNC_CALENDARIO, poco_fa, poco_fa)
        segna_eseguito(
            conn, BACKUP, ORA_DI_TEST - timedelta(hours=6), ORA_DI_TEST - timedelta(hours=6)
        )

    corpo = _get(client)
    assert corpo["sistema"]["ultimoSyncCalendarioLabel"] == "4 minuti fa"
    assert corpo["dati"]["ultimoBackupLabel"] == "oggi alle 02:41"


class TestTuttoCollegato:
    """Con credenziali vere in mano: è l'unico stato in cui si può provare che
    non escono."""

    SEGRETI = (
        "segretissimo-client",
        "segretissimo-secret",
        "segretissimo-refresh",
        "999:segretissimo-bot",
    )

    @pytest.fixture
    def calendario(self) -> ImpostazioniCalendario:
        class _Collegato(ImpostazioniCalendario):
            model_config = SettingsConfigDict(
                env_prefix="CALENDARIO_", env_file=None, extra="ignore"
            )

        return _Collegato(
            client_id="segretissimo-client",
            client_secret="segretissimo-secret",
            refresh_token="segretissimo-refresh",
        )

    @pytest.fixture
    def bot(self) -> ImpostazioniBot:
        class _Collegato(ImpostazioniBot):
            model_config = SettingsConfigDict(env_prefix="TELEGRAM_", env_file=None, extra="ignore")

        return _Collegato(bot_token="999:segretissimo-bot", allowed_user_id=42)

    def test_una_connessione_collegata_lo_dice(self, client: TestClient) -> None:
        per_nome = {c["nome"]: c for c in _get(client)["connessioni"]}
        assert per_nome["Google Calendar"]["stato"] == "collegato"
        assert per_nome["Telegram"]["stato"] == "collegato"
        assert "spento" not in per_nome["Google Calendar"]["dettaglio"]

    def test_nessun_segreto_esce_dalla_risposta(self, client: TestClient) -> None:
        """§9: le credenziali stanno nel `.env`, e da qui si vede solo se ci sono.

        Si guardano i **valori**, non i nomi delle variabili: quelli la pagina
        li dice apposta, ed è la differenza fra «dimmi cosa configurare» e
        «dimmi la chiave».
        """
        testo = client.get("/api/impostazioni").text

        for segreto in self.SEGRETI:
            assert segreto not in testo

    def test_il_bot_dice_che_e_configurato_non_che_e_vivo(self, client: TestClient) -> None:
        """Vivo non si sa: il bot non lascia una traccia periodica come il worker."""
        assert "configurato" in _get(client)["botStatoLabel"]
        assert "42" not in _get(client)["botStatoLabel"]
