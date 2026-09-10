"""Il calendario di Google, contro un finto Google che risponde su HTTP vero.

Qui non c'è nessun client sostituito: c'è il `ClientGoogle` vero che parla con
un server vero, a cui si punta cambiandogli gli URL. Ciò che si verifica è
proprio quello che un finto in memoria non verificherebbe — la finestra chiesta
col fuso giusto, l'espansione delle ricorrenze, il seguito delle pagine, e
soprattutto la conversione degli orari, che è dove si sbaglia.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

import pytest
from pydantic_settings import SettingsConfigDict

from custode_calendario.config import ImpostazioniCalendario
from custode_calendario.errori import (
    AutorizzazioneNonValida,
    CalendarioNonConfigurato,
    CalendarioNonRaggiungibile,
)
from custode_calendario.google import ClientGoogle
from tests.integration.finto_google import FintoGoogle

pytestmark = pytest.mark.integration

# Il 10 settembre 2026 in Italia è ora legale: UTC+2. Gli orari dei test sono
# scritti in UTC apposta, così la conversione ha davvero qualcosa da fare.
DA = date(2026, 9, 10)
A = date(2026, 9, 12)


class _Impostazioni(ImpostazioniCalendario):
    """Ignora il `.env` dello sviluppatore."""

    model_config = SettingsConfigDict(env_prefix="CALENDARIO_", env_file=None, extra="ignore")


@pytest.fixture
def google() -> Iterator[FintoGoogle]:
    finto = FintoGoogle()
    try:
        yield finto
    finally:
        finto.chiudi()


@pytest.fixture
def client(google: FintoGoogle) -> ClientGoogle:
    impostazioni = _Impostazioni(
        client_id="id-finto",
        client_secret="segreto-finto",
        refresh_token="refresh-finto",
        url_token=f"{google.base}/token",
        url_api=f"{google.base}/calendar/v3",
    )
    return ClientGoogle(impostazioni, timezone="Europe/Rome")


# — il token —————————————————————————————————————————————


def test_il_token_si_rinnova_una_volta_sola(client: ClientGoogle, google: FintoGoogle) -> None:
    """Un access token vive un'ora: rinnovarlo ad ogni giro sarebbe una chiamata sprecata."""
    client.eventi(DA, A)
    client.eventi(DA, A)

    assert len(google.stato.richieste_token) == 1
    assert len(google.stato.richieste_eventi) == 2
    # E l'access token ottenuto viene davvero usato per chiedere gli eventi.
    assert google.stato.autorizzazioni_viste == ["Bearer access-nuovo"] * 2


def test_il_token_si_rinnova_quando_sta_per_scadere(
    client: ClientGoogle, google: FintoGoogle
) -> None:
    """Con un margine: scoprirlo con un 401 a metà sincronizzazione sarebbe peggio."""
    google.stato.durata_token = 30  # meno del margine di sicurezza
    client.eventi(DA, A)
    client.eventi(DA, A)
    assert len(google.stato.richieste_token) == 2


def test_il_rinnovo_manda_quello_che_google_vuole(
    client: ClientGoogle, google: FintoGoogle
) -> None:
    client.eventi(DA, A)
    (corpo,) = google.stato.richieste_token
    assert corpo["grant_type"] == ["refresh_token"]
    assert corpo["refresh_token"] == ["refresh-finto"]
    assert corpo["client_id"] == ["id-finto"]


def test_un_permesso_revocato_non_si_riprova(client: ClientGoogle, google: FintoGoogle) -> None:
    """`invalid_grant` non torna buono aspettando: va rifatta l'autorizzazione."""
    google.stato.errore_token = (400, {"error": "invalid_grant"})

    with pytest.raises(AutorizzazioneNonValida) as errore:
        client.eventi(DA, A)

    # Il messaggio nomina la causa più probabile e meno intuitiva.
    assert "Testing" in str(errore.value)
    assert "7 giorni" in str(errore.value)


def test_google_giu_e_un_errore_diverso(client: ClientGoogle, google: FintoGoogle) -> None:
    """Un guasto momentaneo si riprova; un permesso morto no. Non vanno confusi."""
    google.stato.errore_token = (503, {"error": "backend_error"})
    with pytest.raises(CalendarioNonRaggiungibile):
        client.eventi(DA, A)


def test_senza_credenziali_il_modulo_e_spento_non_rotto() -> None:
    client = ClientGoogle(_Impostazioni(), timezone="Europe/Rome")
    assert client.configurata() is False
    with pytest.raises(CalendarioNonConfigurato, match="CALENDARIO_CLIENT_ID"):
        client.eventi(DA, A)


def test_un_401_sugli_eventi_e_un_permesso_morto(client: ClientGoogle, google: FintoGoogle) -> None:
    google.stato.stato_eventi = 401
    with pytest.raises(AutorizzazioneNonValida):
        client.eventi(DA, A)


# — la finestra chiesta a Google ——————————————————————————


def test_la_finestra_porta_il_fuso_di_casa(client: ClientGoogle, google: FintoGoogle) -> None:
    """Una data nuda verrebbe letta in UTC, e in Italia sposta gli estremi di due ore.

    Senza il fuso, un evento delle 8 del primo giorno resterebbe fuori.
    """
    client.eventi(DA, A)
    (parametri,) = google.stato.richieste_eventi
    assert parametri["timeMin"] == ["2026-09-10T00:00:00+02:00"]
    # L'estremo destro è esclusivo, quindi è la mezzanotte del giorno DOPO:
    # il 12 va incluso per intero.
    assert parametri["timeMax"] == ["2026-09-13T00:00:00+02:00"]


def test_le_ricorrenze_arrivano_espanse(client: ClientGoogle, google: FintoGoogle) -> None:
    """«Lezione ogni martedì» deve diventare occorrenze con un istante ciascuna.

    Senza, «prima della prossima lezione» non avrebbe nessun momento a cui
    riferirsi: ci sarebbe un evento solo con dentro una regola di ripetizione.
    """
    client.eventi(DA, A)
    (parametri,) = google.stato.richieste_eventi
    assert parametri["singleEvents"] == ["true"]
    assert parametri["orderBy"] == ["startTime"]


def test_le_pagine_si_seguono_tutte(client: ClientGoogle, google: FintoGoogle) -> None:
    """Fermarsi alla prima pagina perderebbe eventi senza dirlo a nessuno."""
    google.stato.pagine = [
        [_evento("uno", "2026-09-10T08:00:00Z")],
        [_evento("due", "2026-09-11T08:00:00Z")],
        [_evento("tre", "2026-09-12T08:00:00Z")],
    ]

    eventi = client.eventi(DA, A)

    assert [e.id for e in eventi] == ["uno", "due", "tre"]
    assert len(google.stato.richieste_eventi) == 3


# — la conversione degli orari ————————————————————————————


def test_un_orario_utc_diventa_ora_locale_senza_fuso(
    client: ClientGoogle, google: FintoGoogle
) -> None:
    """Il progetto lavora con datetime naive in ora locale (`formato.adesso`).

    Lasciarli con fuso farebbe esplodere ogni confronto con «adesso», cioè
    esattamente ciò che fa una regola di contesto.
    """
    google.stato.eventi = [_evento("x", "2026-09-10T07:30:00Z", "2026-09-10T09:00:00Z")]

    (evento,) = client.eventi(DA, A)

    assert evento.inizio == datetime(2026, 9, 10, 9, 30)
    assert evento.fine == datetime(2026, 9, 10, 11, 0)
    assert evento.inizio.tzinfo is None
    assert evento.tutto_il_giorno is False


def test_un_evento_di_giornata_non_dura_un_giorno_in_piu(
    client: ClientGoogle, google: FintoGoogle
) -> None:
    """Google manda la fine **esclusiva**: un evento di un giorno finisce il giorno dopo."""
    google.stato.eventi = [
        {
            "id": "viaggio",
            "summary": "Ferie",
            "start": {"date": "2026-09-10"},
            "end": {"date": "2026-09-12"},
        }
    ]

    (evento,) = client.eventi(DA, A)

    assert evento.tutto_il_giorno is True
    assert evento.inizio.date() == date(2026, 9, 10)
    # L'11, non il 12: altrimenti «sei impegnato» durerebbe un giorno in più.
    assert evento.fine.date() == date(2026, 9, 11)


def test_una_ricorrenza_porta_l_id_della_serie(client: ClientGoogle, google: FintoGoogle) -> None:
    """Serve al passo dopo: il tipo si decide per la serie, non ogni martedì."""
    voce = _evento("occorrenza-1", "2026-09-10T07:00:00Z")
    voce["recurringEventId"] = "serie-analisi"

    google.stato.eventi = [voce]
    (evento,) = client.eventi(DA, A)

    assert evento.serie_id == "serie-analisi"


def test_un_evento_disdetto_non_entra(client: ClientGoogle, google: FintoGoogle) -> None:
    """Una lezione disdetta non deve far scattare le regole di una lezione."""
    disdetta = _evento("disdetta", "2026-09-10T07:00:00Z")
    disdetta["status"] = "cancelled"

    google.stato.eventi = [disdetta, _evento("vera", "2026-09-10T09:00:00Z")]

    assert [e.id for e in client.eventi(DA, A)] == ["vera"]


def test_un_evento_senza_titolo_ha_comunque_una_parola(
    client: ClientGoogle, google: FintoGoogle
) -> None:
    """Su Google è normale; una stringa vuota in mezzo a un messaggio no."""
    senza = _evento("muto", "2026-09-10T07:00:00Z")
    del senza["summary"]

    google.stato.eventi = [senza]

    assert client.eventi(DA, A)[0].titolo == "(senza titolo)"


def test_un_evento_impossibile_viene_scartato(client: ClientGoogle, google: FintoGoogle) -> None:
    """Una durata negativa manderebbe in confusione ogni conto fatto a valle."""
    google.stato.eventi = [_evento("storto", "2026-09-10T10:00:00Z", "2026-09-10T08:00:00Z")]
    assert client.eventi(DA, A) == []


def test_gli_eventi_tornano_in_ordine(client: ClientGoogle, google: FintoGoogle) -> None:
    google.stato.eventi = [
        _evento("tardi", "2026-09-11T15:00:00Z"),
        _evento("presto", "2026-09-10T06:00:00Z"),
    ]
    assert [e.id for e in client.eventi(DA, A)] == ["presto", "tardi"]


def test_il_luogo_arriva_quando_c_e(client: ClientGoogle, google: FintoGoogle) -> None:
    voce = _evento("con-luogo", "2026-09-10T07:00:00Z")
    voce["location"] = "Aula 3, via Roma"

    google.stato.eventi = [voce]

    assert client.eventi(DA, A)[0].luogo == "Aula 3, via Roma"


def _evento(identificativo: str, inizio: str, fine: str | None = None) -> dict[str, object]:
    return {
        "id": identificativo,
        "summary": f"Evento {identificativo}",
        "status": "confirmed",
        "start": {"dateTime": inizio},
        "end": {"dateTime": fine or inizio},
    }
