"""La firma delle richieste di deploy: giusta passa, tutto il resto no."""

from __future__ import annotations

from custode_deploy.firma import TOLLERANZA_SECONDI, firma, verifica

SEGRETO = "segreto-di-prova"
ADESSO = 1_800_000_000


def _firmata(corpo: bytes = b"{}", metodo: str = "POST", percorso: str = "/deploy") -> str:
    return firma(SEGRETO, ADESSO, metodo, percorso, corpo)


def test_una_firma_giusta_passa() -> None:
    assert verifica(SEGRETO, str(ADESSO), _firmata(), "POST", "/deploy", b"{}", ADESSO)


def test_la_firma_non_dipende_dal_maiuscolo_del_metodo() -> None:
    assert firma(SEGRETO, ADESSO, "post", "/deploy", b"") == firma(
        SEGRETO, ADESSO, "POST", "/deploy", b""
    )


def test_un_altro_segreto_non_passa() -> None:
    assert not verifica("altro", str(ADESSO), _firmata(), "POST", "/deploy", b"{}", ADESSO)


def test_la_firma_di_una_richiesta_non_vale_per_unaltra() -> None:
    valida = _firmata()
    assert not verifica(SEGRETO, str(ADESSO), valida, "GET", "/deploy", b"{}", ADESSO)
    assert not verifica(SEGRETO, str(ADESSO), valida, "POST", "/stato/abc", b"{}", ADESSO)
    assert not verifica(SEGRETO, str(ADESSO), valida, "POST", "/deploy", b'{"x":1}', ADESSO)


def test_una_richiesta_vecchia_non_si_puo_rimandare() -> None:
    valida = _firmata()
    troppo_tardi = ADESSO + TOLLERANZA_SECONDI + 1
    assert not verifica(SEGRETO, str(ADESSO), valida, "POST", "/deploy", b"{}", troppo_tardi)
    # Anche una dal futuro: l'orologio della CI non può essere avanti di ore.
    troppo_presto = ADESSO - TOLLERANZA_SECONDI - 1
    assert not verifica(SEGRETO, str(ADESSO), valida, "POST", "/deploy", b"{}", troppo_presto)


def test_dentro_la_tolleranza_passa() -> None:
    valida = _firmata()
    quasi = ADESSO + TOLLERANZA_SECONDI
    assert verifica(SEGRETO, str(ADESSO), valida, "POST", "/deploy", b"{}", quasi)


def test_header_mancanti_o_storti_non_passano() -> None:
    valida = _firmata()
    assert not verifica(SEGRETO, None, valida, "POST", "/deploy", b"{}", ADESSO)
    assert not verifica(SEGRETO, str(ADESSO), None, "POST", "/deploy", b"{}", ADESSO)
    assert not verifica(SEGRETO, "non-un-numero", valida, "POST", "/deploy", b"{}", ADESSO)


def test_un_segreto_vuoto_non_firma_niente() -> None:
    # Con un segreto vuoto chiunque saprebbe calcolare la firma giusta.
    vuota = firma("", ADESSO, "POST", "/deploy", b"{}")
    assert not verifica("", str(ADESSO), vuota, "POST", "/deploy", b"{}", ADESSO)
