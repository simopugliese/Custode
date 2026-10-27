"""Il listener: autentica, mette in coda, racconta com'è andata."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from custode_deploy import listener
from custode_deploy.firma import firma
from custode_deploy.listener import STATI_PER_CODICE, Servizio, esegui_comando

SEGRETO = "segreto-di-prova"
ADESSO = 1_800_000_000


class Esecutore:
    """Finge `deploy.sh`: ricorda come è stato chiamato e restituisce ciò che gli dici."""

    def __init__(self, codice: int = 0, messaggio: str = "Deploy ok: abc1234") -> None:
        self.codice = codice
        self.messaggio = messaggio
        self.chiamate: list[Sequence[str]] = []

    def __call__(self, comando: Sequence[str]) -> tuple[int, str]:
        self.chiamate.append(comando)
        return self.codice, self.messaggio


def _intestazioni(metodo: str, percorso: str, corpo: bytes = b"") -> dict[str, str]:
    return {
        "X-Custode-Timestamp": str(ADESSO),
        "X-Custode-Firma": firma(SEGRETO, ADESSO, metodo, percorso, corpo),
    }


def _servizio(esecutore: Esecutore) -> Servizio:
    # `in_background=False`: il deploy finto finisce prima che la chiamata torni.
    return Servizio(
        SEGRETO, ["bash", "deploy.sh"], esecutore=esecutore, ora=lambda: ADESSO, in_background=False
    )


def test_senza_firma_valida_non_parte_nulla() -> None:
    esecutore = Esecutore()
    servizio = _servizio(esecutore)
    codice, _ = servizio.gestisci("POST", "/deploy", {}, b"")
    assert codice == 401
    sbagliata = {"X-Custode-Timestamp": str(ADESSO), "X-Custode-Firma": "00" * 32}
    assert servizio.gestisci("POST", "/deploy", sbagliata, b"")[0] == 401
    assert esecutore.chiamate == []


def test_un_deploy_firmato_parte_e_si_racconta() -> None:
    esecutore = Esecutore()
    servizio = _servizio(esecutore)
    codice, risposta = servizio.gestisci("POST", "/deploy", _intestazioni("POST", "/deploy"), b"")
    assert codice == 202
    assert esecutore.chiamate == [["bash", "deploy.sh"]]

    percorso = f"/stato/{risposta['id']}"
    codice, stato = servizio.gestisci("GET", percorso, _intestazioni("GET", percorso), b"")
    assert codice == 200
    assert stato == {"stato": "ok", "messaggio": "Deploy ok: abc1234"}


def test_il_corpo_non_sceglie_cosa_installare() -> None:
    # Anche un corpo con un commit dentro: il comando lanciato resta lo stesso,
    # senza argomenti. Il commit lo decide deploy.sh da origin/main.
    esecutore = Esecutore()
    corpo = b'{"sha": "deadbeef", "comando": "rm -rf /"}'
    _servizio(esecutore).gestisci("POST", "/deploy", _intestazioni("POST", "/deploy", corpo), corpo)
    assert esecutore.chiamate == [["bash", "deploy.sh"]]


@pytest.mark.parametrize(("codice", "stato"), sorted(STATI_PER_CODICE.items()))
def test_ogni_exit_code_ha_il_suo_stato(codice: int, stato: str) -> None:
    servizio = _servizio(Esecutore(codice, "msg"))
    _, risposta = servizio.gestisci("POST", "/deploy", _intestazioni("POST", "/deploy"), b"")
    percorso = f"/stato/{risposta['id']}"
    assert (
        servizio.gestisci("GET", percorso, _intestazioni("GET", percorso), b"")[1]["stato"] == stato
    )


def test_un_exit_code_sconosciuto_e_un_fallimento() -> None:
    servizio = _servizio(Esecutore(1, "boom"))
    _, risposta = servizio.gestisci("POST", "/deploy", _intestazioni("POST", "/deploy"), b"")
    percorso = f"/stato/{risposta['id']}"
    assert servizio.gestisci("GET", percorso, _intestazioni("GET", percorso), b"")[1] == {
        "stato": "fallito",
        "messaggio": "boom",
    }


def test_uno_stato_sconosciuto_e_un_404_e_un_percorso_strano_pure() -> None:
    servizio = _servizio(Esecutore())
    percorso = "/stato/nonesiste"
    assert servizio.gestisci("GET", percorso, _intestazioni("GET", percorso), b"")[0] == 404
    assert servizio.gestisci("GET", "/altro", _intestazioni("GET", "/altro"), b"")[0] == 404


def test_senza_segreto_il_servizio_non_si_costruisce() -> None:
    with pytest.raises(ValueError, match="segreto"):
        Servizio("", ["bash", "deploy.sh"])


def test_i_nomi_degli_header_possono_arrivare_in_minuscolo() -> None:
    # Cloudflare (HTTP/2) li abbassa: se il listener cercasse solo la forma con
    # le maiuscole, ogni deploy vero verrebbe rifiutato come non firmato.
    esecutore = Esecutore()
    minuscoli = {nome.lower(): valore for nome, valore in _intestazioni("POST", "/deploy").items()}
    assert _servizio(esecutore).gestisci("POST", "/deploy", minuscoli, b"")[0] == 202


def test_il_comando_vero_scrive_nel_journal_e_restituisce_lultima_riga(
    capsys: pytest.CaptureFixture[str],
) -> None:
    codice, ultima = esegui_comando(["sh", "-c", "echo uno; echo due >&2; echo tre; exit 11"])
    assert (codice, ultima) == (11, "tre")
    # Stdout e stderr finiscono nello stesso flusso, riga per riga e col prefisso.
    fuori = capsys.readouterr().out.splitlines()
    assert fuori == ["[deploy] uno", "[deploy] due", "[deploy] tre"]


def test_un_comando_che_non_stampa_niente_ha_lultima_riga_vuota() -> None:
    assert esegui_comando(["true"]) == (0, "")


def test_un_comando_troppo_lento_viene_fermato(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(listener, "TIMEOUT_DEPLOY_SECONDI", 0.2)
    codice, messaggio = esegui_comando(["sleep", "5"])
    assert codice == 1
    assert "tempo massimo" in messaggio
