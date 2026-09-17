"""Il giudizio di Claude su un pattern (§6, §8.10).

Il modello è finto: qui si verifica cosa gli arriva — i conti, in italiano — e
soprattutto come si rilegge quello che risponde. La parte delicata è la stessa
del tagging (una voce letta per posizione invece che per numero finisce sul
candidato sbagliato), più una che il tagging non aveva: qui una voce illeggibile
si **butta**, perché non esiste un ripiego sensato per un promemoria che nessuno
ha scritto.
"""

from __future__ import annotations

from typing import Any

import pytest

from custode_core.dominio import pattern as dom_pattern
from custode_core.dominio import regole as dom_regole
from custode_router import regole as router_regole
from custode_router.compiti import Compito
from custode_router.errori import RispostaNonValida


class RouterFinto:
    def __init__(self, risposta: dict[str, Any]) -> None:
        self.risposta = risposta
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        return self.risposta


SU_IMPEGNO = dom_pattern.Candidato(
    genere=dom_pattern.Genere.SU_IMPEGNO,
    soggetto="Creatina",
    occasioni=16,
    coperte=15,
    tipo_evento="palestra",
    altrove=2,
    giornate_altrove=40,
)

A_ORARIO = dom_pattern.Candidato(
    genere=dom_pattern.Genere.A_ORARIO,
    soggetto="Corsa",
    occasioni=24,
    coperte=22,
    ora="07:00",
    giorni=(1, 3, 5),
    nel_grappolo=20,
    segnate=22,
)


def _voce(n: int, **campi: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "n": n,
        "proponi": True,
        "confidenza": "alta",
        "messaggio": "prendi la creatina",
        "motivazione": "15 giornate con palestra su 16.",
    }
    base.update(campi)
    return base


# — quello che il modello riceve —


def test_il_compito_e_quello_di_sesto_paragrafo() -> None:
    router = RouterFinto({"proposte": [_voce(1, quando="dopo", minuti=0)]})

    router_regole.giudica(router, [SU_IMPEGNO])  # type: ignore[arg-type]

    assert router.chiamate[0]["compito"] is Compito.PROPOSTA_REGOLE


def test_i_conti_arrivano_al_modello_in_italiano() -> None:
    """Il modello deve poter scrivere una motivazione coi numeri dentro: se non
    li riceve, la motivazione diventa un'impressione."""
    prompt = router_regole.componi_prompt([SU_IMPEGNO, A_ORARIO])

    assert "1. " in prompt and "2. " in prompt
    assert "«Creatina»" in prompt and "«palestra»" in prompt
    assert "16 giornate" in prompt and "15 di quelle" in prompt
    assert "40 giornate senza" in prompt and "2 volte" in prompt
    # Il candidato a orario porta i suoi giorni detti a parole, non i numeri.
    assert "lunedì, mercoledì e venerdì" in prompt
    assert "07:00" in prompt


def test_su_elenco_vuoto_non_si_chiama_nessuno() -> None:
    """Il caso di quasi tutte le notti, ed è la ragione per cui la soglia sta in
    codice prima di qui."""
    router = RouterFinto({"proposte": []})

    assert router_regole.giudica(router, []) == []  # type: ignore[arg-type]
    assert router.chiamate == []


def test_oltre_il_tetto_i_candidati_non_entrano_nella_chiamata() -> None:
    molti = [SU_IMPEGNO] * (router_regole.MAX_CANDIDATI + 3)
    router = RouterFinto(
        {
            "proposte": [
                _voce(n, quando="dopo", minuti=0) for n in range(1, router_regole.MAX_CANDIDATI + 1)
            ]
        }
    )

    lette = router_regole.giudica(router, molti)  # type: ignore[arg-type]

    assert len(lette) == router_regole.MAX_CANDIDATI


# — come si rilegge quello che risponde —


def test_le_voci_si_rileggono_per_numero_non_per_posizione() -> None:
    """Un modello che risponde in ordine sparso non deve far finire la
    motivazione della corsa sulla creatina."""
    router = RouterFinto(
        {
            "proposte": [
                _voce(2, messaggio="esci a correre", motivazione="22 su 24."),
                _voce(1, quando="dopo", minuti=0),
            ]
        }
    )

    lette = router_regole.giudica(router, [SU_IMPEGNO, A_ORARIO])  # type: ignore[arg-type]

    assert [p.candidato.soggetto for p in lette] == ["Creatina", "Corsa"]
    assert lette[0].messaggio == "prendi la creatina"
    assert lette[1].messaggio == "esci a correre"


def test_il_modello_puo_dire_di_no_e_non_e_un_guasto() -> None:
    """È il lavoro per cui §6 lo chiama: il pattern regge nei numeri ma non vale
    un'interruzione."""
    router = RouterFinto(
        {"proposte": [_voce(1, proponi=False, quando="dopo", minuti=0, confidenza="bassa")]}
    )

    lette = router_regole.giudica(router, [SU_IMPEGNO])  # type: ignore[arg-type]

    assert len(lette) == 1
    assert lette[0].proponi is False
    assert lette[0].confidenza is dom_regole.Confidenza.BASSA


def test_prima_o_dopo_lo_sceglie_il_modello() -> None:
    router = RouterFinto(
        {
            "proposte": [
                _voce(1, quando="prima", minuti=30, messaggio="metti il portatile nello zaino")
            ]
        }
    )

    lette = router_regole.giudica(router, [SU_IMPEGNO])  # type: ignore[arg-type]

    assert lette[0].trigger is dom_regole.Trigger.PRIMA_EVENTO
    assert lette[0].minuti == 30


def test_un_candidato_a_orario_resta_a_orario_qualunque_cosa_risponda() -> None:
    """La forma della regola l'ha decisa il rilevatore: il modello non la cambia."""
    router = RouterFinto({"proposte": [_voce(1, quando="prima", minuti=45)]})

    lette = router_regole.giudica(router, [A_ORARIO])  # type: ignore[arg-type]

    assert lette[0].trigger is dom_regole.Trigger.ORARIO
    assert lette[0].minuti == 0


def test_i_campi_assenti_ripiegano_su_appena_finisce() -> None:
    """Un modello che si dimentica il campo non deve costare la proposta: «appena
    finisce» è la lettura più innocua di un aggancio a un impegno."""
    router = RouterFinto({"proposte": [_voce(1)]})

    lette = router_regole.giudica(router, [SU_IMPEGNO])  # type: ignore[arg-type]

    assert lette[0].trigger is dom_regole.Trigger.DOPO_EVENTO
    assert lette[0].minuti == 0


def test_un_anticipo_fuori_scala_butta_la_voce() -> None:
    """Troncarlo a un giorno farebbe approvare una regola diversa da quella
    proposta: un anticipo di tre giorni non è una svista da correggere in
    silenzio."""
    router = RouterFinto(
        {
            "proposte": [
                _voce(1, quando="prima", minuti=dom_regole.MAX_MINUTI + 1),
                _voce(2, messaggio="esci a correre", motivazione="22 su 24."),
            ]
        }
    )

    lette = router_regole.giudica(router, [SU_IMPEGNO, A_ORARIO])  # type: ignore[arg-type]

    assert [p.candidato.soggetto for p in lette] == ["Corsa"]


def test_un_messaggio_troppo_lungo_butta_la_voce() -> None:
    lungo = "x" * (dom_regole.MAX_CARATTERI_MESSAGGIO + 1)
    router = RouterFinto(
        {
            "proposte": [
                _voce(1, messaggio=lungo, quando="dopo", minuti=0),
                _voce(2, messaggio="esci a correre", motivazione="22 su 24."),
            ]
        }
    )

    lette = router_regole.giudica(router, [SU_IMPEGNO, A_ORARIO])  # type: ignore[arg-type]

    assert [p.candidato.soggetto for p in lette] == ["Corsa"]


def test_una_proposta_senza_il_perche_si_butta() -> None:
    router = RouterFinto(
        {
            "proposte": [
                _voce(1, motivazione="   ", quando="dopo", minuti=0),
                _voce(2, messaggio="esci a correre", motivazione="22 su 24."),
            ]
        }
    )

    lette = router_regole.giudica(router, [SU_IMPEGNO, A_ORARIO])  # type: ignore[arg-type]

    assert [p.candidato.soggetto for p in lette] == ["Corsa"]


def test_una_confidenza_inventata_butta_la_voce() -> None:
    router = RouterFinto(
        {
            "proposte": [
                _voce(1, confidenza="altissima", quando="dopo", minuti=0),
                _voce(2, messaggio="esci a correre", motivazione="22 su 24."),
            ]
        }
    )

    lette = router_regole.giudica(router, [SU_IMPEGNO, A_ORARIO])  # type: ignore[arg-type]

    assert [p.candidato.soggetto for p in lette] == ["Corsa"]


def test_una_voce_saltata_resta_una_voce_saltata() -> None:
    router = RouterFinto({"proposte": [_voce(2, messaggio="esci a correre")]})

    lette = router_regole.giudica(router, [SU_IMPEGNO, A_ORARIO])  # type: ignore[arg-type]

    assert [p.candidato.soggetto for p in lette] == ["Corsa"]


def test_niente_di_leggibile_e_un_guasto_non_una_risposta() -> None:
    """Va distinto da «nessuna proposta», o il worker segnerebbe la notte come
    fatta e non riproverebbe."""
    router = RouterFinto({"proposte": [{"boh": 1}]})

    with pytest.raises(RispostaNonValida):
        router_regole.giudica(router, [SU_IMPEGNO])  # type: ignore[arg-type]


def test_una_risposta_senza_elenco_e_un_guasto() -> None:
    router = RouterFinto({"altro": []})

    with pytest.raises(RispostaNonValida):
        router_regole.giudica(router, [SU_IMPEGNO])  # type: ignore[arg-type]
