"""Il router e i due client, con trasporti finti al posto della rete.

Senza chiavi non si possono fare chiamate vere: quello che si può verificare —
e che conta — è che il compito scelga il provider giusto, che la richiesta abbia
la forma attesa, e che ogni modo di fallire produca l'errore giusto.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic_settings import SettingsConfigDict

from custode_router.claude import ClientClaude
from custode_router.compiti import Compito
from custode_router.config import ImpostazioniRouter
from custode_router.deepseek import ClientDeepSeek
from custode_router.errori import (
    CompitoNonSupportato,
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)
from custode_router.router import Router


class _Impostazioni(ImpostazioniRouter):
    """Ignora il `.env` dello sviluppatore: i test leggono solo ciò che passano."""

    model_config = SettingsConfigDict(env_prefix="ROUTER_", env_file=None, extra="ignore")


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"azione": {"type": "string"}},
    "required": ["azione"],
}


@pytest.fixture
def impostazioni() -> ImpostazioniRouter:
    return _Impostazioni(deepseek_api_key="ds-finta", anthropic_api_key="an-finta")


# — DeepSeek —


def _deepseek_che_risponde(
    contenuto: str, registro: list[httpx.Request] | None = None, stato: int = 200
) -> httpx.Client:
    def gestisci(richiesta: httpx.Request) -> httpx.Response:
        if registro is not None:
            registro.append(richiesta)
        if stato != 200:
            return httpx.Response(stato, json={"error": "no"})
        return httpx.Response(200, json={"choices": [{"message": {"content": contenuto}}]})

    return httpx.Client(transport=httpx.MockTransport(gestisci))


def test_deepseek_manda_la_richiesta_attesa(impostazioni: ImpostazioniRouter) -> None:
    registro: list[httpx.Request] = []
    client = ClientDeepSeek(impostazioni, _deepseek_che_risponde('{"azione": "nessuna"}', registro))

    assert client.chiedi_json(sistema="sei X", utente="ciao", schema=SCHEMA) == {
        "azione": "nessuna"
    }

    (richiesta,) = registro
    assert richiesta.url.path == "/chat/completions"
    assert richiesta.headers["authorization"] == "Bearer ds-finta"
    corpo = json.loads(richiesta.content)
    assert corpo["model"] == "deepseek-chat"
    assert corpo["response_format"] == {"type": "json_object"}
    # Un parser deve essere ripetibile.
    assert corpo["temperature"] == 0
    # Lo schema va nel prompt: DeepSeek garantisce JSON valido, non conforme.
    assert "azione" in corpo["messages"][0]["content"]
    assert corpo["messages"][1]["content"] == "ciao"


def test_deepseek_senza_chiave(impostazioni: ImpostazioniRouter) -> None:
    senza = _Impostazioni(deepseek_api_key="")
    with pytest.raises(ProviderNonConfigurato):
        ClientDeepSeek(senza).chiedi_json(sistema="x", utente="y", schema=SCHEMA)


def test_deepseek_in_errore(impostazioni: ImpostazioniRouter) -> None:
    client = ClientDeepSeek(impostazioni, _deepseek_che_risponde("", stato=500))
    with pytest.raises(ProviderNonRaggiungibile):
        client.chiedi_json(sistema="x", utente="y", schema=SCHEMA)


@pytest.mark.parametrize("contenuto", ["non json", "[1, 2]", '"stringa"'])
def test_deepseek_risposta_non_json(impostazioni: ImpostazioniRouter, contenuto: str) -> None:
    client = ClientDeepSeek(impostazioni, _deepseek_che_risponde(contenuto))
    with pytest.raises(RispostaNonValida):
        client.chiedi_json(sistema="x", utente="y", schema=SCHEMA)


# — Claude —


class _Blocco:
    def __init__(self, testo: str):
        self.type = "text"
        self.text = testo


class _Risposta:
    def __init__(self, testo: str, stop_reason: str = "end_turn"):
        self.content = [_Blocco(testo)]
        self.stop_reason = stop_reason


class _MessaggiFinti:
    def __init__(self, risposta: Any = None, errore: Exception | None = None):
        self._risposta = risposta
        self._errore = errore
        self.chiamate: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.chiamate.append(kwargs)
        if self._errore is not None:
            raise self._errore
        return self._risposta


class _ClientFinto:
    def __init__(self, messaggi: _MessaggiFinti):
        self.messages = messaggi


def test_claude_manda_la_richiesta_attesa(impostazioni: ImpostazioniRouter) -> None:
    messaggi = _MessaggiFinti(_Risposta('{"azione": "nessuna"}'))
    client = ClientClaude(impostazioni, _ClientFinto(messaggi))

    assert client.chiedi_json(sistema="sei X", utente="ciao", schema=SCHEMA) == {
        "azione": "nessuna"
    }

    (chiamata,) = messaggi.chiamate
    assert chiamata["model"] == "claude-opus-5"
    assert chiamata["system"] == "sei X"
    # Structured outputs: il formato lo garantisce l'API, non il prompt.
    assert chiamata["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert chiamata["output_config"]["effort"] == "high"


def test_claude_senza_chiave() -> None:
    senza = _Impostazioni(anthropic_api_key="")
    with pytest.raises(ProviderNonConfigurato):
        ClientClaude(senza).chiedi_json(sistema="x", utente="y", schema=SCHEMA)


def test_claude_che_rifiuta(impostazioni: ImpostazioniRouter) -> None:
    """Un rifiuto del modello non è un guasto di rete: riprovare non aiuterebbe."""
    messaggi = _MessaggiFinti(_Risposta("{}", stop_reason="refusal"))
    with pytest.raises(RispostaNonValida):
        ClientClaude(impostazioni, _ClientFinto(messaggi)).chiedi_json(
            sistema="x", utente="y", schema=SCHEMA
        )


def test_claude_in_errore(impostazioni: ImpostazioniRouter) -> None:
    messaggi = _MessaggiFinti(errore=RuntimeError("boom"))
    with pytest.raises(ProviderNonRaggiungibile):
        ClientClaude(impostazioni, _ClientFinto(messaggi)).chiedi_json(
            sistema="x", utente="y", schema=SCHEMA
        )


# — Router —


def test_il_router_manda_il_compito_al_provider_giusto(
    impostazioni: ImpostazioniRouter,
) -> None:
    deepseek = ClientDeepSeek(impostazioni, _deepseek_che_risponde('{"da": "deepseek"}'))
    claude = ClientClaude(impostazioni, _ClientFinto(_MessaggiFinti(_Risposta('{"da": "claude"}'))))
    router = Router(impostazioni, deepseek=deepseek, claude=claude)

    semplice = router.chiedi_json(Compito.CRUD_TASK, sistema="x", utente="y", schema=SCHEMA)
    difficile = router.chiedi_json(Compito.RIASSUNTO_DIARIO, sistema="x", utente="y", schema=SCHEMA)

    assert semplice == {"da": "deepseek"}
    assert difficile == {"da": "claude"}


def test_i_compiti_con_immagini_non_sono_ancora_supportati(
    impostazioni: ImpostazioniRouter,
) -> None:
    router = Router(impostazioni)
    with pytest.raises(CompitoNonSupportato):
        router.chiedi_json(Compito.LETTURA_SCONTRINO, sistema="x", utente="y", schema=SCHEMA)


def test_configurato_per_guarda_il_provider_del_compito() -> None:
    solo_deepseek = _Impostazioni(deepseek_api_key="ds", anthropic_api_key="")
    router = Router(solo_deepseek)
    assert router.configurato_per(Compito.CRUD_TASK) is True
    assert router.configurato_per(Compito.RIASSUNTO_DIARIO) is False
