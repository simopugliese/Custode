"""Il comando di autorizzazione, dal clic al refresh token (§8.10).

È il pezzo che una persona lancia a mano e che io non posso provare contro
Google vero — servirebbero credenziali e un consenso umano. Quello che si può
provare, e che qui si prova, è tutto il resto: che l'indirizzo di consenso
chieda le cose giuste, che il codice arrivi, che uno stato sbagliato venga
rifiutato, e che lo scambio finale produca il token.
"""

from __future__ import annotations

import socket
import urllib.parse
import urllib.request
from collections.abc import Iterator

import pytest
from pydantic_settings import SettingsConfigDict

from custode_calendario.autorizza import (
    _Raccoglitore,
    indirizzo_consenso,
    principale,
    scambia_codice,
)
from custode_calendario.config import ImpostazioniCalendario
from custode_calendario.errori import CalendarioNonConfigurato, CalendarioNonRaggiungibile
from custode_calendario.google import SCOPE
from tests.integration.finto_google import FintoGoogle

pytestmark = pytest.mark.integration


class _Impostazioni(ImpostazioniCalendario):
    model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")


@pytest.fixture
def google() -> Iterator[FintoGoogle]:
    finto = FintoGoogle()
    try:
        yield finto
    finally:
        finto.chiudi()


@pytest.fixture
def impostazioni(google: FintoGoogle) -> ImpostazioniCalendario:
    return _Impostazioni(
        client_id="id-finto",
        client_secret="segreto-finto",
        url_token=f"{google.base}/token",
        url_autorizzazione=f"{google.base}/consenso",
        porta_autorizzazione=8766,
    )


# — l'indirizzo su cui la persona dà il permesso —


def test_l_indirizzo_chiede_sola_lettura(impostazioni: ImpostazioniCalendario) -> None:
    """Custode non scrive mai sul calendario, e lo scope lo rende impossibile."""
    parametri = _parametri(indirizzo_consenso(impostazioni, impronta="abc", stato="xyz"))
    assert parametri["scope"] == [SCOPE]
    assert parametri["scope"][0].endswith("calendar.readonly")


def test_l_indirizzo_chiede_un_permesso_duraturo(impostazioni: ImpostazioniCalendario) -> None:
    """Senza `access_type=offline` non arriva nessun refresh token.

    E senza `prompt=consent` non arriva alla **seconda** autorizzazione, il che
    sembrerebbe un guasto invece che una regola di Google.
    """
    parametri = _parametri(indirizzo_consenso(impostazioni, impronta="abc", stato="xyz"))
    assert parametri["access_type"] == ["offline"]
    assert parametri["prompt"] == ["consent"]


def test_l_indirizzo_usa_pkce(impostazioni: ImpostazioniCalendario) -> None:
    """Il client_secret di un'app installata non è davvero segreto."""
    parametri = _parametri(indirizzo_consenso(impostazioni, impronta="impronta", stato="xyz"))
    assert parametri["code_challenge"] == ["impronta"]
    assert parametri["code_challenge_method"] == ["S256"]


def test_l_indirizzo_torna_dove_aspettiamo(impostazioni: ImpostazioniCalendario) -> None:
    parametri = _parametri(indirizzo_consenso(impostazioni, impronta="abc", stato="xyz"))
    assert parametri["redirect_uri"] == ["http://localhost:8766"]


# — lo scambio finale —


def test_lo_scambio_produce_il_token(
    impostazioni: ImpostazioniCalendario, google: FintoGoogle
) -> None:
    token = scambia_codice(impostazioni, codice="codice-finto", verificatore="verif")

    assert token == "refresh-nuovo"
    (corpo,) = google.stato.richieste_token
    assert corpo["grant_type"] == ["authorization_code"]
    assert corpo["code"] == ["codice-finto"]
    # Il verificatore PKCE deve tornare indietro, o Google rifiuta.
    assert corpo["code_verifier"] == ["verif"]


def test_senza_refresh_token_lo_dice_e_spiega(
    impostazioni: ImpostazioniCalendario, google: FintoGoogle
) -> None:
    """Succede se hai già autorizzato: Google manda solo l'access token."""
    google.stato.errore_token = (200, {"access_token": "solo-questo"})

    with pytest.raises(CalendarioNonRaggiungibile, match="refresh token"):
        scambia_codice(impostazioni, codice="c", verificatore="v")


def test_un_rifiuto_di_google_non_passa_per_riuscito(
    impostazioni: ImpostazioniCalendario, google: FintoGoogle
) -> None:
    google.stato.errore_token = (400, {"error": "invalid_grant"})
    with pytest.raises(CalendarioNonRaggiungibile):
        scambia_codice(impostazioni, codice="c", verificatore="v")


# — il giro completo, col browser finto —


def test_il_giro_completo_stampa_la_riga_da_incollare(
    impostazioni: ImpostazioniCalendario,
    google: FintoGoogle,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dal comando lanciato alla riga per il .env, senza saltare passaggi.

    Al posto della persona che clicca c'è una finta apertura del browser che
    chiama il reindirizzamento come farebbe Google.
    """
    monkeypatch.setattr(
        "custode_calendario.autorizza.get_impostazioni_calendario", lambda: impostazioni
    )

    def finto_browser(indirizzo: str) -> bool:
        parametri = _parametri(indirizzo)
        ritorno = (
            f"{parametri['redirect_uri'][0]}"
            f"?code=codice-dal-browser&state={parametri['state'][0]}"
        )
        urllib.request.urlopen(ritorno, timeout=5).read()
        return True

    monkeypatch.setattr("custode_calendario.autorizza.webbrowser.open", finto_browser)

    assert principale() == 0

    stampato = capsys.readouterr().out
    assert "CALENDARIO_REFRESH_TOKEN=refresh-nuovo" in stampato
    # E l'avviso che costa una settimana a chi non lo legge.
    assert "Testing" in stampato and "7 giorni" in stampato


def test_un_codice_con_lo_stato_sbagliato_viene_rifiutato(
    impostazioni: ImpostazioniCalendario,
    google: FintoGoogle,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un'altra pagina aperta nel browser non deve poter infilare un codice suo."""
    monkeypatch.setattr(
        "custode_calendario.autorizza.get_impostazioni_calendario", lambda: impostazioni
    )

    def browser_bugiardo(indirizzo: str) -> bool:
        parametri = _parametri(indirizzo)
        ritorno = f"{parametri['redirect_uri'][0]}?code=codice-altrui&state=stato-inventato"
        urllib.request.urlopen(ritorno, timeout=5).read()
        return True

    monkeypatch.setattr("custode_calendario.autorizza.webbrowser.open", browser_bugiardo)

    assert principale() == 1
    assert _Raccoglitore.codice == ""
    assert "CALENDARIO_REFRESH_TOKEN" not in capsys.readouterr().out


def test_senza_credenziali_dice_cosa_creare(monkeypatch: pytest.MonkeyPatch) -> None:
    """Il messaggio deve dire dove andare, non solo che manca qualcosa."""
    monkeypatch.setattr("custode_calendario.autorizza.get_impostazioni_calendario", _Impostazioni)
    with pytest.raises(CalendarioNonConfigurato, match="Desktop app"):
        principale()


def _parametri(indirizzo: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlparse(indirizzo).query)


def test_una_porta_occupata_lo_dice_invece_di_esplodere(
    impostazioni: ImpostazioniCalendario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il comando aspetta cinque minuti, e chi lo rilancia trovava un traceback.

    Succede sul serio: sembra che non stia succedendo niente, si rilancia, e il
    primo è ancora lì in ascolto.
    """
    monkeypatch.setattr(
        "custode_calendario.autorizza.get_impostazioni_calendario", lambda: impostazioni
    )
    occupata = socket.socket()
    occupata.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupata.bind((impostazioni.ascolta_su, impostazioni.porta_autorizzazione))
    occupata.listen(1)
    try:
        with pytest.raises(CalendarioNonRaggiungibile, match="occupata"):
            principale()
    finally:
        occupata.close()
