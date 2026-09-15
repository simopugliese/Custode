"""I segreti non devono finire nei log (§9).

Il caso vero da cui nasce questo modulo: Telegram mette il token del bot
*nell'URL*, httpx logga ogni URL a livello INFO, e il token finiva in ogni riga
di `docker compose logs bot` — cioè nel primo posto da cui si copia-incolla
quando si chiede aiuto.

I token qui dentro sono inventati ma hanno la **forma** di quelli veri: è la
forma che il filtro riconosce, e provarlo con `"segreto"` non proverebbe niente.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from custode_core.log import (
    FORMATO,
    NASCOSTO,
    FormattatoreSenzaSegreti,
    configura,
    nascondi_segreti,
)

TOKEN_TELEGRAM = "1234567890:AAF-abcdefghijklmnopqrstuvwxyz012345678"
CHIAVE_API = "sk-abcdef0123456789abcdef0123456789"
REFRESH_GOOGLE = "1//0gabcdefghijklmnopqrstuvwxyz-ABCDEFGHIJ"
CLIENT_SECRET = "GOCSPX-abcdefghij0123456789"


@pytest.mark.parametrize("segreto", [TOKEN_TELEGRAM, CHIAVE_API, REFRESH_GOOGLE, CLIENT_SECRET])
def test_un_segreto_non_passa(segreto: str) -> None:
    assert segreto not in nascondi_segreti(f"roba prima {segreto} roba dopo")


def test_l_url_di_telegram_resta_leggibile_senza_il_token() -> None:
    """La riga serve a vedere se il bot parla con Telegram: si toglie il
    segreto, non la riga."""
    vera = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/getUpdates"
    riga = nascondi_segreti(f'HTTP Request: POST {vera} "HTTP/1.1 200 OK"')

    assert TOKEN_TELEGRAM not in riga
    pulita = f"https://api.telegram.org/bot{NASCOSTO}/getUpdates"
    assert riga == f'HTTP Request: POST {pulita} "HTTP/1.1 200 OK"'


@pytest.mark.parametrize(
    "dentro_un_url",
    [
        # Com'è: è la forma che stampa `httpx`.
        f"/bot{TOKEN_TELEGRAM}/getUpdates",
        # Percent-encoded: è la forma che stampa l'access log di uvicorn, che
        # riporta il *request target* grezzo. I due punti diventano %3A, e un
        # filtro che cercasse solo quelli veri lascerebbe passare proprio la
        # riga del processo esposto alla rete.
        f"/bot{TOKEN_TELEGRAM.replace(':', '%3A')}/getUpdates",
        f"?refresh={REFRESH_GOOGLE.replace('/', '%2F')}",
    ],
)
def test_un_segreto_non_passa_nemmeno_percent_encoded(dentro_un_url: str) -> None:
    pulita = nascondi_segreti(f'"GET {dentro_un_url} HTTP/1.1" 200 OK')

    assert NASCOSTO in pulita
    for pezzo in ("AAF-abcdefghijklmnopqrstuvwxyz012345678", "0gabcdefghijklmnopqrstuvwxyz"):
        assert pezzo not in pulita


def test_quello_che_non_e_un_segreto_resta_com_e() -> None:
    """Un filtro che cancella «una stringa lunga a caso» renderebbe i log
    inutili invece che sicuri: gli id di Google e i percorsi devono restare."""
    riga = (
        "calendario: 7 eventi, serie 4k3m1p9qvv8h5s7t9u1v3w5x7y_20260914T070000Z,"
        " db /data/custode.db, fascia 2026-09-14T10:00"
    )

    assert nascondi_segreti(riga) == riga


def test_anche_un_orario_con_i_due_punti_resta_com_e() -> None:
    """Il token è «cifre : stringa lunga», e un orario gli somiglia da lontano."""
    assert nascondi_segreti("riepilogo delle 21:00 del 2026-09-14") == (
        "riepilogo delle 21:00 del 2026-09-14"
    )


# — il formattatore, che è ciò che gira davvero —


def _formatta(record: logging.LogRecord) -> str:
    return FormattatoreSenzaSegreti(logging.Formatter(FORMATO)).format(record)


def _record(messaggio: str, *args: object, exc_info: object = None) -> logging.LogRecord:
    return logging.LogRecord(
        name="custode.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=messaggio,
        args=args or None,
        exc_info=exc_info,  # type: ignore[arg-type]
    )


def test_il_segreto_non_passa_nemmeno_dagli_argomenti() -> None:
    """httpx logga l'URL come **argomento**, non dentro il messaggio: un filtro
    che guardasse solo `msg` non prenderebbe niente."""
    riga = _formatta(_record("HTTP Request: %s", f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/x"))

    assert TOKEN_TELEGRAM not in riga
    assert NASCOSTO in riga


def test_il_segreto_non_passa_nemmeno_da_un_traceback() -> None:
    """È il posto meno sorvegliato: un URL con dentro un token ci finisce da
    solo, dentro il messaggio dell'eccezione."""
    try:
        raise RuntimeError(f"connessione fallita a https://api.telegram.org/bot{TOKEN_TELEGRAM}/x")
    except RuntimeError as errore:
        record = _record("errore non gestito", exc_info=(type(errore), errore, None))

    riga = _formatta(record)

    assert TOKEN_TELEGRAM not in riga
    assert NASCOSTO in riga


# — i gestori che non passano dalla radice (uvicorn) —


@pytest.fixture
def logging_pulito() -> Iterator[None]:
    """Rimette i log com'erano: `configura` tocca lo stato globale del processo."""
    radice = logging.getLogger()
    prima = (list(radice.handlers), radice.level)
    nomi_prima = set(logging.root.manager.loggerDict)
    try:
        yield
    finally:
        radice.handlers, radice.level = list(prima[0]), prima[1]
        for nome in set(logging.root.manager.loggerDict) - nomi_prima:
            del logging.root.manager.loggerDict[nome]


def _come_uvicorn(nome: str) -> tuple[logging.Logger, io.StringIO]:
    """Un logger fatto come quelli di uvicorn: gestore suo, e `propagate=False`.

    È la forma che conta, non il nome: `propagate=False` vuol dire che di quel
    logger non arriva niente alla radice, quindi un formattatore messo lì non
    lo vedrebbe mai.
    """
    dove = io.StringIO()
    logger = logging.getLogger(nome)
    logger.handlers = [logging.StreamHandler(dove)]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, dove


def test_il_segreto_non_passa_nemmeno_dai_log_di_uvicorn(logging_pulito: None) -> None:
    """Sotto uvicorn l'access log ha gestori suoi e non passa dalla radice.

    È il processo esposto alla rete: se un segreto finisce in un suo traceback
    esce in chiaro, e un formattatore messo solo sulla radice non lo vedrebbe.
    """
    logger, dove = _come_uvicorn("uvicorn.access")

    configura("INFO")
    logger.info("GET /api/roba?token=%s", TOKEN_TELEGRAM)

    assert TOKEN_TELEGRAM not in dove.getvalue()
    assert NASCOSTO in dove.getvalue()


def test_il_formato_di_chi_ne_ha_uno_suo_resta_il_suo(logging_pulito: None) -> None:
    """L'access log di uvicorn sa di `client_addr` e `request_line`.

    Sostituirgli il formattatore col formato di Custode nasconderebbe i segreti
    buttando via la riga: resterebbe un access log senza dentro l'accesso.
    """
    logger, dove = _come_uvicorn("uvicorn.access")
    logger.handlers[0].setFormatter(logging.Formatter("ACCESSO %(message)s"))

    configura("INFO")
    logger.info("GET /api/home 200")

    assert dove.getvalue().strip() == "ACCESSO GET /api/home 200"


def test_configurare_due_volte_non_impila_formattatori(logging_pulito: None) -> None:
    """`crea_app` si chiama più volte in un processo solo: nei test, sempre."""
    logger, _ = _come_uvicorn("uvicorn.access")

    configura("INFO")
    uno = logger.handlers[0].formatter
    configura("INFO")

    assert logger.handlers[0].formatter is uno
