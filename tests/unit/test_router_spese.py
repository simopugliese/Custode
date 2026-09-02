"""Categoria nuova e lettura degli scontrini (§6, §8.5).

Senza chiave non si può chiamare Claude davvero. Si verifica quello che conta
lo stesso: che i due compiti finiscano dove §6 dice, che l'immagine arrivi al
modello per la strada giusta, e che ogni modo in cui uno scontrino può essere
letto male produca un rifiuto comprensibile invece di un totale inventato nei
conti.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from custode_router import spese
from custode_router.compiti import CON_IMMAGINI, Compito, Provider, provider_per
from custode_router.errori import (
    CompitoNonSupportato,
    ProviderNonConfigurato,
    ProviderNonRaggiungibile,
    RispostaNonValida,
)
from custode_router.router import Router

OGGI = date(2026, 9, 2)

SCONTRINO_OK: dict[str, Any] = {
    "leggibile": True,
    "totale": 23.4,
    "luogo": "Coop",
    "data": "2026-08-30",
    "voci": ["Latte — 1,29", "Pane — 2,10"],
}


class RouterFinto:
    def __init__(self, risposta: dict[str, Any] | None = None, errore: Exception | None = None):
        self.risposta = risposta if risposta is not None else dict(SCONTRINO_OK)
        self.errore = errore
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, "immagine": None, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.risposta

    def chiedi_json_con_immagine(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.risposta


# — instradamento (§6) —————————————————————————————————


def test_creare_una_categoria_va_a_claude() -> None:
    # §6: «evitare categorie duplicate o incoerenti» chiede giudizio, e un
    # doppione creato oggi resta lì per sempre.
    assert provider_per(Compito.CATEGORIE_SPESA) is Provider.CLAUDE


def test_leggere_uno_scontrino_va_a_claude_ed_e_l_unico_compito_con_immagini() -> None:
    assert provider_per(Compito.LETTURA_SCONTRINO) is Provider.CLAUDE
    assert frozenset({Compito.LETTURA_SCONTRINO}) == CON_IMMAGINI


def test_uno_scontrino_non_si_puo_chiedere_senza_immagine() -> None:
    # Il tipo di errore è la differenza fra "manca l'immagine" e una risposta
    # inventata dal modello su niente.
    with pytest.raises(CompitoNonSupportato):
        Router().chiedi_json(
            Compito.LETTURA_SCONTRINO, sistema="s", utente="u", schema={"type": "object"}
        )


def test_un_compito_senza_immagini_non_passa_dalla_strada_con_immagini() -> None:
    with pytest.raises(CompitoNonSupportato):
        Router().chiedi_json_con_immagine(
            Compito.RIASSUNTO_DIARIO,
            sistema="s",
            utente="u",
            schema={"type": "object"},
            immagine=b"\xff\xd8",
        )


# — categoria —————————————————————————————————————————


def _categoria(router: RouterFinto, **extra: Any) -> str:
    argomenti: dict[str, Any] = {"descrizione": "spesa al super", "luogo": None, "esistenti": []}
    argomenti.update(extra)
    return spese.categoria_per(router, **argomenti)  # type: ignore[arg-type]


def test_le_categorie_gia_in_uso_arrivano_al_modello() -> None:
    # È l'unica cosa che gli permette di riusarle invece di inventarne una
    # simile: senza l'elenco, il doppione è inevitabile.
    router = RouterFinto({"categoria": "Alimentari", "esistente": True})
    _categoria(router, esistenti=["Alimentari", "Trasporti"])
    utente = router.chiamate[0]["utente"]
    assert "Alimentari" in utente and "Trasporti" in utente


def test_quando_non_c_e_ancora_niente_il_prompt_lo_dice() -> None:
    router = RouterFinto({"categoria": "Alimentari", "esistente": False})
    _categoria(router)
    assert "nessuna, è la prima" in router.chiamate[0]["utente"]


def test_il_luogo_entra_nel_prompt_solo_se_c_e() -> None:
    router = RouterFinto({"categoria": "Alimentari", "esistente": False})
    _categoria(router, luogo="Coop")
    assert "Coop" in router.chiamate[0]["utente"]

    senza = RouterFinto({"categoria": "Alimentari", "esistente": False})
    _categoria(senza)
    assert "Luogo:" not in senza.chiamate[0]["utente"]


def test_una_categoria_vuota_e_una_risposta_non_valida() -> None:
    router = RouterFinto({"categoria": "   ", "esistente": False})
    with pytest.raises(RispostaNonValida):
        _categoria(router)


def test_il_prompt_chiede_di_riusare_prima_di_creare() -> None:
    # Se questa regola sparisce dal prompt, le categorie si moltiplicano in
    # silenzio: la si tiene sotto test come si tiene uno schema.
    assert "riusa" in spese.SISTEMA_CATEGORIA.lower()


# — scontrino ——————————————————————————————————————————


def test_l_immagine_arriva_al_modello_col_suo_tipo() -> None:
    router = RouterFinto()
    spese.leggi_scontrino(router, immagine=b"\xff\xd8jpeg", oggi=OGGI, media_type="image/png")  # type: ignore[arg-type]
    chiamata = router.chiamate[0]
    assert chiamata["compito"] is Compito.LETTURA_SCONTRINO
    assert chiamata["immagine"] == b"\xff\xd8jpeg"
    assert chiamata["media_type"] == "image/png"


def test_uno_scontrino_letto_diventa_totale_luogo_data_e_voci() -> None:
    letto = spese.leggi_scontrino(RouterFinto(), immagine=b"foto", oggi=OGGI)  # type: ignore[arg-type]
    assert letto.centesimi == 2340
    assert letto.luogo == "Coop"
    assert letto.giorno == date(2026, 8, 30)
    assert letto.dettaglio == "Latte — 1,29\nPane — 2,10"


def test_senza_immagine_non_si_chiama_nemmeno_il_modello() -> None:
    router = RouterFinto()
    with pytest.raises(spese.LetturaNonRiuscita):
        spese.leggi_scontrino(router, immagine=b"", oggi=OGGI)  # type: ignore[arg-type]
    assert router.chiamate == []


def test_se_il_modello_dice_che_non_si_legge_non_si_registra_niente() -> None:
    dati = dict(SCONTRINO_OK, leggibile=False)
    with pytest.raises(spese.LetturaNonRiuscita) as errore:
        spese.leggi_risposta(dati, oggi=OGGI)
    # Il messaggio deve dire come rifare la foto, non solo che è fallita.
    assert "nitida" in str(errore.value)


@pytest.mark.parametrize("totale", ["23.40", None, True, [23.4]])
def test_un_totale_non_numerico_e_una_risposta_non_valida(totale: Any) -> None:
    # `True` compreso: in Python è un intero, e passerebbe un controllo
    # scritto male finendo nei conti come un centesimo.
    with pytest.raises(RispostaNonValida):
        spese.leggi_risposta(dict(SCONTRINO_OK, totale=totale), oggi=OGGI)


@pytest.mark.parametrize("totale", [0, 0.0, -12.5])
def test_un_totale_a_zero_o_negativo_non_diventa_una_spesa(totale: float) -> None:
    with pytest.raises(spese.LetturaNonRiuscita):
        spese.leggi_risposta(dict(SCONTRINO_OK, totale=totale), oggi=OGGI)


def test_una_data_illeggibile_non_fa_buttare_via_lo_scontrino() -> None:
    # Meglio una spesa datata oggi che nessuna spesa: il totale è la cosa che
    # conta, e la data si corregge guardando la foto.
    letto = spese.leggi_risposta(dict(SCONTRINO_OK, data="30/08/2026"), oggi=OGGI)
    assert letto.giorno is None
    assert letto.centesimi == 2340


def test_una_data_nel_futuro_non_viene_presa_per_buona() -> None:
    """Una spesa già pagata non può essere di domani: è una lettura sbagliata.

    Conta più di una pignoleria: ogni vista di Custode finisce a oggi, quindi
    una spesa datata in avanti sarebbe scritta sul disco e invisibile ovunque,
    per sempre, senza un errore da nessuna parte.
    """
    letto = spese.leggi_risposta(dict(SCONTRINO_OK, data="2026-09-20"), oggi=OGGI)
    assert letto.giorno is None  # chi salva userà oggi
    assert letto.centesimi == 2340


def test_la_data_di_oggi_e_del_passato_restano(  # una data valida non si tocca
) -> None:
    assert spese.leggi_risposta(dict(SCONTRINO_OK, data="2026-09-02"), oggi=OGGI).giorno == OGGI
    vecchio = spese.leggi_risposta(dict(SCONTRINO_OK, data="2026-08-28"), oggi=OGGI)
    assert vecchio.giorno == date(2026, 8, 28)


def test_le_voci_di_uno_scontrino_lunghissimo_si_fermano() -> None:
    letto = spese.leggi_risposta(
        dict(SCONTRINO_OK, voci=[f"riga {n}" for n in range(200)]), oggi=OGGI
    )
    assert len(letto.voci) == spese.MAX_VOCI


def test_le_voci_mancanti_non_sono_un_errore() -> None:
    letto = spese.leggi_risposta(dict(SCONTRINO_OK, voci=[]), oggi=OGGI)
    assert letto.voci == []
    assert letto.dettaglio == ""


def test_l_arrotondamento_del_totale_e_al_centesimo() -> None:
    assert spese.leggi_risposta(dict(SCONTRINO_OK, totale=8.15), oggi=OGGI).centesimi == 815


# — messaggi d'errore —————————————————————————————————


@pytest.mark.parametrize(
    ("errore", "atteso"),
    [
        (ProviderNonConfigurato("x"), "chiave"),
        (ProviderNonRaggiungibile("x"), "Riprova"),
        (RispostaNonValida("x"), "a parole"),
    ],
)
def test_ogni_guasto_dice_cosa_puoi_fare(errore: Exception, atteso: str) -> None:
    assert atteso in spese.messaggio_errore(errore)


def test_il_motivo_di_una_lettura_fallita_si_riporta_com_e() -> None:
    errore = spese.LetturaNonRiuscita("Il totale letto è zero: controlla la foto.")
    assert spese.messaggio_errore(errore) == str(errore)
