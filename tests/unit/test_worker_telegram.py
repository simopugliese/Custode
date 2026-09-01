"""L'invio su Telegram del worker, con un trasporto finto al posto della rete.

Non serve un token per verificare ciò che conta: che la richiesta abbia la
forma che Telegram si aspetta, che i bottoni arrivino come `inline_keyboard`, e
che un guasto di rete diventi un errore riconoscibile invece di passare
inosservato.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from custode_bot.risposte import Bottone, Risposta
from custode_worker.telegram import ClientTelegram, InvioNonRiuscito

TOKEN = "123456:FINTO"
CHAT = 424242


def _client(gestore: Any) -> ClientTelegram:
    trasporto = httpx.MockTransport(gestore)
    return ClientTelegram(TOKEN, CHAT, client=httpx.Client(transport=trasporto))


def test_manda_un_messaggio_semplice() -> None:
    viste: list[httpx.Request] = []

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        viste.append(richiesta)
        return httpx.Response(200, json={"ok": True})

    _client(gestore).manda(Risposta(testo="<b>Ciao</b>"))

    (richiesta,) = viste
    assert richiesta.url.path == f"/bot{TOKEN}/sendMessage"
    corpo = json.loads(richiesta.content)
    assert corpo["chat_id"] == CHAT
    assert corpo["text"] == "<b>Ciao</b>"
    # Il testo del worker usa HTML come quello del bot: senza, i tag si vedrebbero.
    assert corpo["parse_mode"] == "HTML"
    assert "reply_markup" not in corpo


def test_i_bottoni_diventano_una_inline_keyboard() -> None:
    viste: list[httpx.Request] = []

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        viste.append(richiesta)
        return httpx.Response(200, json={"ok": True})

    _client(gestore).manda(
        Risposta(
            testo="Scegli",
            bottoni=[
                [Bottone("✕ uno", "p:scarta:1:t"), Bottone("✕ due", "p:scarta:2:t")],
                [Bottone("Aggiorna il profilo", "p:rifondi::t")],
            ],
        )
    )

    corpo = json.loads(viste[0].content)
    # Telegram vuole `reply_markup` come stringa JSON, non come oggetto annidato.
    tastiera = json.loads(corpo["reply_markup"])["inline_keyboard"]
    assert [[b["text"] for b in riga] for riga in tastiera] == [
        ["✕ uno", "✕ due"],
        ["Aggiorna il profilo"],
    ]
    assert tastiera[1][0]["callback_data"] == "p:rifondi::t"


def test_un_errore_http_diventa_invio_non_riuscito() -> None:
    """Il worker deve poterlo distinguere per non segnare il job come fatto."""

    def gestore(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    with pytest.raises(InvioNonRiuscito):
        _client(gestore).manda(Risposta(testo="x"))


def test_una_rete_giu_diventa_invio_non_riuscito() -> None:
    def gestore(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("niente rete")

    with pytest.raises(InvioNonRiuscito):
        _client(gestore).manda(Risposta(testo="x"))


@pytest.mark.parametrize(("token", "chat"), [("", CHAT), (TOKEN, 0)])
def test_senza_destinatario_non_si_prova_nemmeno(token: str, chat: int) -> None:
    cliente = ClientTelegram(token, chat)
    assert cliente.configurato() is False
    with pytest.raises(InvioNonRiuscito):
        cliente.manda(Risposta(testo="x"))
