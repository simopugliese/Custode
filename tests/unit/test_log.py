"""I segreti non devono finire nei log (§9).

Il caso vero da cui nasce questo modulo: Telegram mette il token del bot
*nell'URL*, httpx logga ogni URL a livello INFO, e il token finiva in ogni riga
di `docker compose logs bot` — cioè nel primo posto da cui si copia-incolla
quando si chiede aiuto.

I token qui dentro sono inventati ma hanno la **forma** di quelli veri: è la
forma che il filtro riconosce, e provarlo con `"segreto"` non proverebbe niente.
"""

from __future__ import annotations

import logging

import pytest

from custode_core.log import FORMATO, NASCOSTO, FormattatoreSenzaSegreti, nascondi_segreti

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
    return FormattatoreSenzaSegreti(FORMATO).format(record)


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
