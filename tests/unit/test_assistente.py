"""Dal testo libero all'azione: la parte che decide cosa succede davvero.

Il modello è sostituito da un router finto che restituisce l'intenzione voluta:
qui si verifica ciò che sta *sotto* il modello — che un'intenzione diventi
l'azione giusta sul database, e che un'intenzione storta non combini danni.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from custode_core.dominio import abitudini as dom_abitudini
from custode_core.dominio import diario as dom_diario
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import profilo as dom_profilo
from custode_core.dominio import regole as dom_regole
from custode_core.dominio import spese as dom_spese
from custode_core.dominio import task as dom_task
from custode_router import assistente
from custode_router.assistente import Azione
from custode_router.compiti import Compito
from custode_router.errori import ProviderNonConfigurato, ProviderNonRaggiungibile


class RouterFinto:
    """Al posto del modello: risponde ciò che gli si dice, e registra il prompt."""

    def __init__(self, risposta: dict[str, Any] | None = None, errore: Exception | None = None):
        self.risposta = risposta or {"azione": "nessuna"}
        self.errore = errore
        self.chiamate: list[dict[str, Any]] = []

    def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
        self.chiamate.append({"compito": compito, **kwargs})
        if self.errore is not None:
            raise self.errore
        return self.risposta


CAMPI_MESSAGGIO = frozenset({"segnale", "segnale_estratto", "segnale_domanda"})


def _forma_modello(*piatte: dict[str, Any]) -> dict[str, Any]:
    """Da uno o più dizionari piatti alla forma che il modello risponde davvero.

    I test descrivono una azione come un dizionario solo — che è come si legge
    meglio — e qui viene messa nella lista `azioni`, mentre i campi che
    riguardano il messaggio intero (il segnale per il profilo) restano fuori.
    Così i test dicono cosa conta e passano comunque dallo schema vero.
    """
    azioni = [{k: v for k, v in p.items() if k not in CAMPI_MESSAGGIO} for p in piatte]
    messaggio = {k: v for p in piatte for k, v in p.items() if k in CAMPI_MESSAGGIO}
    return {"azioni": azioni, **messaggio}


def _esegui_tutte(
    conn: sqlite3.Connection, ora: datetime, testo: str, *risposte: dict[str, Any]
) -> list[assistente.Esito]:
    router = RouterFinto(_forma_modello(*risposte))
    return assistente.interpreta_ed_esegui(conn, ora, testo, router)  # type: ignore[arg-type]


def _esegui(
    conn: sqlite3.Connection, ora: datetime, testo: str, risposta: dict[str, Any]
) -> assistente.Esito:
    """Il caso di gran lunga più comune: il messaggio chiede una cosa sola."""
    esiti = _esegui_tutte(conn, ora, testo, risposta)
    assert len(esiti) == 1, f"attesa una sola azione, arrivate {len(esiti)}"
    return esiti[0]


# — il contesto passato al modello —


def test_il_prompt_contiene_quello_che_esiste_gia(conn: sqlite3.Connection, ora: datetime) -> None:
    """Senza l'elenco, «ho fatto la bolletta» non potrebbe agganciare nulla."""
    dom_task.crea(conn, titolo="Pagare la bolletta", ora=ora)
    dom_lista.aggiungi(conn, nome="latte", ora=ora, reparto="Latticini")

    router = RouterFinto()
    assistente.interpreta(conn, ora, "ciao", router)  # type: ignore[arg-type]

    (chiamata,) = router.chiamate
    assert "Pagare la bolletta" in chiamata["utente"]
    assert "latte" in chiamata["utente"]
    assert "Latticini" in chiamata["utente"]
    assert ora.date().isoformat() in chiamata["utente"]
    assert "ciao" in chiamata["utente"]


# — le azioni —


def test_aggiungi_task(conn: sqlite3.Connection, ora: datetime) -> None:
    esito = _esegui(
        conn,
        ora,
        "ricordami di chiamare l'officina domani",
        {"azione": "aggiungi_task", "titolo": "Chiamare l'officina", "scadenza": "2026-09-01"},
    )
    creati = dom_task.elenco(conn)
    assert [t.titolo for t in creati] == ["Chiamare l'officina"]
    assert creati[0].scadenza == date(2026, 9, 1)
    assert creati[0].origine == "telegram"
    assert esito.azione is Azione.AGGIUNGI_TASK
    assert "domani" in esito.testo


def test_aggiungi_task_senza_titolo_non_crea_niente(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    esito = _esegui(conn, ora, "boh", {"azione": "aggiungi_task", "titolo": ""})
    assert dom_task.elenco(conn) == []
    assert not esito.ha_cambiato_qualcosa


def test_una_scadenza_malformata_non_perde_il_task(conn: sqlite3.Connection, ora: datetime) -> None:
    # Meglio un task senza scadenza che nessun task.
    esito = _esegui(
        conn,
        ora,
        "x",
        {"azione": "aggiungi_task", "titolo": "Cosa", "scadenza": "prossima settimana"},
    )
    assert esito.azione is Azione.AGGIUNGI_TASK
    assert dom_task.elenco(conn)[0].scadenza is None


def test_completa_task(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="Pagare la bolletta", ora=ora)
    esito = _esegui(
        conn,
        ora,
        "fatto la bolletta",
        {"azione": "completa_task", "riferimento": "Pagare la bolletta"},
    )
    assert dom_task.leggi(conn, task.id).fatto is True
    assert esito.task_id == task.id


def test_completa_task_con_riferimento_abbreviato(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="Pagare la bolletta della luce", ora=ora)
    _esegui(conn, ora, "x", {"azione": "completa_task", "riferimento": "bolletta"})
    assert dom_task.leggi(conn, task.id).fatto is True


def test_un_riferimento_ambiguo_non_chiude_niente(conn: sqlite3.Connection, ora: datetime) -> None:
    """Fra due task che combaciano si preferisce non fare nulla che indovinare."""
    primo = dom_task.crea(conn, titolo="Pagare la bolletta della luce", ora=ora)
    secondo = dom_task.crea(conn, titolo="Pagare la bolletta del gas", ora=ora)

    esito = _esegui(conn, ora, "x", {"azione": "completa_task", "riferimento": "bolletta"})

    assert dom_task.leggi(conn, primo.id).fatto is False
    assert dom_task.leggi(conn, secondo.id).fatto is False
    assert not esito.ha_cambiato_qualcosa
    assert "Non ho trovato" in esito.testo


def test_un_riferimento_inventato_non_chiude_niente(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    dom_task.crea(conn, titolo="Pagare la bolletta", ora=ora)
    esito = _esegui(
        conn, ora, "x", {"azione": "completa_task", "riferimento": "portare fuori il cane"}
    )
    assert dom_task.elenco(conn, fatto=True) == []
    assert not esito.ha_cambiato_qualcosa


def test_rinvia_task(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="Dentista", ora=ora, scadenza=ora.date())
    esito = _esegui(
        conn,
        ora,
        "rimanda il dentista di tre giorni",
        {"azione": "rinvia_task", "riferimento": "Dentista", "giorni": 3},
    )
    aggiornato = dom_task.leggi(conn, task.id)
    assert aggiornato.scadenza == ora.date() + timedelta(days=3)
    assert aggiornato.rinvii == 1
    assert esito.giorni == 3


def test_aggiungi_voce_spesa(conn: sqlite3.Connection, ora: datetime) -> None:
    esito = _esegui(
        conn,
        ora,
        "sto finendo il latte",
        {
            "azione": "aggiungi_voce_spesa",
            "titolo": "latte",
            "quantita": "1 L",
            "reparto": "Latticini",
        },
    )
    (voce,) = dom_lista.elenco(conn)
    assert (voce.nome, voce.quantita, voce.reparto) == ("latte", "1 L", "Latticini")
    assert esito.voce_id == voce.id


def test_aggiungere_due_volte_lo_dice(conn: sqlite3.Connection, ora: datetime) -> None:
    payload = {"azione": "aggiungi_voce_spesa", "titolo": "latte"}
    _esegui(conn, ora, "x", payload)
    esito = _esegui(conn, ora, "x", payload)
    assert "era già in lista" in esito.testo
    assert len(dom_lista.elenco(conn)) == 1


# — spese (§8.5): la frase con dentro una cifra —


def test_registra_spesa(conn: sqlite3.Connection, ora: datetime) -> None:
    dom_spese.assicura_categoria(conn, "Bar", ora)
    esito = _esegui(
        conn,
        ora,
        "ho pagato 8€ la colazione da Bar Rossi",
        {
            "azione": "registra_spesa",
            "titolo": "colazione",
            "importo": 8,
            "luogo": "Bar Rossi",
            "categoria": "Bar",
        },
    )
    (spesa,) = dom_spese.elenco(conn)
    assert (spesa.centesimi, spesa.descrizione, spesa.luogo) == (800, "colazione", "Bar Rossi")
    # Da testo entra subito nei conti: la conferma §8.5 la chiede lo scontrino.
    assert spesa.stato is dom_spese.Stato.CONFERMATA
    assert esito.spesa_id == spesa.id
    assert "8,00 €" in esito.testo


# — la data di una spesa detta a parole (§8.5) —


def test_una_spesa_detta_per_ieri_finisce_a_ieri(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il bug osservato sul Pi: «ieri ho pagato 17 euro» finiva a oggi, in silenzio."""
    ieri = ora.date() - timedelta(days=1)
    esito = _esegui(
        conn,
        ora,
        "Ieri ho pagato 17 euro la spesa xyz",
        {
            "azione": "registra_spesa",
            "titolo": "spesa xyz",
            "importo": 17,
            "data": ieri.isoformat(),
        },
    )
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.giorno == ieri
    # E lo dice: una spesa datata altrove non compare fra quelle di oggi, e
    # senza dirlo sembrerebbe non essere stata registrata affatto.
    assert "di ieri" in esito.testo


def test_senza_data_la_spesa_e_di_oggi(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il caso normale non cambia, e la conferma non ripete «di oggi»."""
    esito = _esegui(
        conn,
        ora,
        "ho pagato 8€ la colazione",
        {"azione": "registra_spesa", "titolo": "colazione", "importo": 8},
    )
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.giorno == ora.date()
    assert "oggi" not in esito.testo


def test_una_spesa_datata_nel_futuro_torna_a_oggi(conn: sqlite3.Connection, ora: datetime) -> None:
    """§8.5: ogni vista finisce a oggi, quindi una spesa in avanti sparirebbe per sempre."""
    _esegui(
        conn,
        ora,
        "x",
        {
            "azione": "registra_spesa",
            "titolo": "benzina",
            "importo": 40,
            "data": (ora.date() + timedelta(days=3)).isoformat(),
        },
    )
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.giorno == ora.date()


@pytest.mark.parametrize("grezza", ["", "ieri", "03/09/2026", "2026-13-45", "non lo so"])
def test_una_data_illeggibile_non_perde_la_spesa(
    conn: sqlite3.Connection, ora: datetime, grezza: str
) -> None:
    """Come per la scadenza di un task: si perde la data, mai il movimento."""
    _esegui(
        conn,
        ora,
        "x",
        {"azione": "registra_spesa", "titolo": "birra", "importo": 4.5, "data": grezza},
    )
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.giorno == ora.date()


def test_una_data_con_l_orario_attaccato_vale_lo_stesso(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    ieri = ora.date() - timedelta(days=1)
    _esegui(
        conn,
        ora,
        "x",
        {
            "azione": "registra_spesa",
            "titolo": "cena",
            "importo": 25,
            "data": f"{ieri.isoformat()}T21:30",
        },
    )
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.giorno == ieri


def test_una_spesa_vecchia_dice_la_data_per_esteso(conn: sqlite3.Connection, ora: datetime) -> None:
    """Sul passato non c'è tetto: se il modello sbaglia l'anno, la conferma lo mostra."""
    esito = _esegui(
        conn,
        ora,
        "x",
        {"azione": "registra_spesa", "titolo": "palestra", "importo": 40, "data": "2025-09-02"},
    )
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.giorno == date(2025, 9, 2)
    assert "del 2 set 2025" in esito.testo


def test_lo_schema_ha_un_posto_per_la_data(conn: sqlite3.Connection, ora: datetime) -> None:
    """La causa del bug era qui: senza il campo, «ieri» non aveva dove finire."""
    assert "data" in assistente.SCHEMA_AZIONE["properties"]


def test_il_contesto_dice_anche_che_giorno_della_settimana_e(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """«sabato scorso» si risolve solo sapendo che oggi è lunedì."""
    router = RouterFinto()
    assistente.interpreta(conn, ora, "x", router)  # type: ignore[arg-type]
    assert "lunedì" in router.chiamate[0]["utente"]


# — la giornata raccontata in ritardo (§8.4) —


def test_ti_racconto_la_giornata_di_ieri_finisce_su_ieri(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Il bug osservato sul Pi: «ti racconto la giornata di ieri» annotava a oggi."""
    ieri = ora.date() - timedelta(days=1)
    esito = _esegui(
        conn,
        ora,
        "Ti racconto la giornata di ieri: ho studiato tutto il pomeriggio",
        {
            "azione": "annota_diario",
            "titolo": "Ho studiato tutto il pomeriggio",
            "data": ieri.isoformat(),
        },
    )

    assert dom_diario.leggi_giorno(conn, ora.date()) is None
    voce = dom_diario.leggi_giorno(conn, ieri)
    assert voce is not None and voce.grezzo == "Ho studiato tutto il pomeriggio"
    assert "di ieri" in esito.testo
    # Il bot ne ha bisogno per offrire «Chiudi la giornata di ieri».
    assert esito.giorno == ieri


def test_senza_data_il_racconto_e_di_oggi(conn: sqlite3.Connection, ora: datetime) -> None:
    esito = _esegui(
        conn, ora, "giornata pesante", {"azione": "annota_diario", "titolo": "Giornata pesante"}
    )
    assert dom_diario.leggi_giorno(conn, ora.date()) is not None
    assert "di oggi" in esito.testo


def test_annotare_su_un_giorno_gia_approvato_non_cancella_l_approvato(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Aggiungere qualcosa in ritardo non deve buttare via ciò che avevi confermato."""
    ieri = ora.date() - timedelta(days=1)
    voce, _ = dom_diario.aggiungi_materiale(conn, giorno=ieri, testo="Prima parte", ora=ora)
    dom_diario.approva(conn, voce.id, ora, testo="Giornata tranquilla.")

    _esegui(
        conn,
        ora,
        "mi ero dimenticato: ieri sera sono anche andato in palestra",
        {
            "azione": "annota_diario",
            "titolo": "Sono andato in palestra",
            "data": ieri.isoformat(),
        },
    )

    aggiornata = dom_diario.leggi_giorno(conn, ieri)
    assert aggiornata is not None
    # L'approvazione precedente resta leggibile finché non ne approvi una nuova,
    # ma la giornata torna aperta perché la bozza non comprende la frase nuova.
    assert aggiornata.riassunto_approvato == "Giornata tranquilla."
    assert aggiornata.stato is dom_diario.Stato.IN_RACCOLTA
    assert "palestra" in aggiornata.grezzo


def test_un_racconto_datato_nel_futuro_torna_a_oggi(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Una giornata che non è ancora successa non si può raccontare."""
    _esegui(
        conn,
        ora,
        "x",
        {
            "azione": "annota_diario",
            "titolo": "Qualcosa",
            "data": (ora.date() + timedelta(days=2)).isoformat(),
        },
    )
    assert dom_diario.leggi_giorno(conn, ora.date()) is not None


# — abitudini da testo libero (§8.6) —


def _abitudini(conn: sqlite3.Connection, ora: datetime) -> dict[str, int]:
    return {
        nome: dom_abitudini.crea(conn, nome=nome, target_settimanale=3, ora=ora).id
        for nome in ("Palestra", "Lettura", "Meditazione")
    }


def test_una_frase_segna_piu_abitudini_insieme(conn: sqlite3.Connection, ora: datetime) -> None:
    """«ho fatto x,y ma non z» è UN gesto: tre log, una risposta, un «Annulla»."""
    ids = _abitudini(conn, ora)
    esito = _esegui(
        conn,
        ora,
        "oggi palestra e lettura, ma niente meditazione",
        {
            "azione": "segna_abitudini",
            "abitudini_fatte": ["Palestra", "Lettura"],
            "abitudini_non_fatte": ["Meditazione"],
        },
    )

    assert dom_abitudini.segnata(conn, ids["Palestra"], ora.date()) is True
    assert dom_abitudini.segnata(conn, ids["Lettura"], ora.date()) is True
    assert dom_abitudini.segnata(conn, ids["Meditazione"], ora.date()) is False
    assert "Palestra, Lettura" in esito.testo
    assert "Meditazione" in esito.testo


def test_le_abitudini_segnate_si_annullano_con_un_tap(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    ids = _abitudini(conn, ora)
    esito = _esegui(
        conn,
        ora,
        "palestra e lettura",
        {"azione": "segna_abitudini", "abitudini_fatte": ["Palestra", "Lettura"]},
    )
    assert esito.identificatore is not None

    testo = assistente.annulla(conn, ora, esito.azione, identificatore=esito.identificatore)

    assert "Palestra" in testo and "Lettura" in testo
    # Annullare riporta al silenzio, non scrive «non fatto».
    assert dom_abitudini.segnata(conn, ids["Palestra"], ora.date()) is None
    assert dom_abitudini.segnata(conn, ids["Lettura"], ora.date()) is None


def test_un_nome_che_non_segui_viene_detto_non_creato(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Creare un'abitudine è una decisione: non la si prende al posto suo."""
    _abitudini(conn, ora)
    esito = _esegui(
        conn,
        ora,
        "palestra e chitarra",
        {"azione": "segna_abitudini", "abitudini_fatte": ["Palestra", "Chitarra"]},
    )

    assert "«Chitarra»" in esito.testo
    assert [a.nome for a in dom_abitudini.elenco(conn, solo_attive=False)] == [
        "Palestra",
        "Lettura",
        "Meditazione",
    ]


def test_solo_nomi_sconosciuti_non_segna_niente(conn: sqlite3.Connection, ora: datetime) -> None:
    _abitudini(conn, ora)
    esito = _esegui(
        conn, ora, "ho fatto scherma", {"azione": "segna_abitudini", "abitudini_fatte": ["Scherma"]}
    )
    assert "Non seguo" in esito.testo
    assert esito.identificatore is None
    assert dom_abitudini.log_del_periodo(conn, da=ora.date(), a=ora.date()) == {}


def test_un_abitudine_disattivata_non_si_riaccende_di_nascosto(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    ids = _abitudini(conn, ora)
    dom_abitudini.modifica(conn, ids["Lettura"], attiva=False)

    esito = _esegui(
        conn, ora, "lettura", {"azione": "segna_abitudini", "abitudini_fatte": ["Lettura"]}
    )

    assert "Non seguo" in esito.testo
    assert dom_abitudini.segnata(conn, ids["Lettura"], ora.date()) is None


def test_segnare_per_ieri(conn: sqlite3.Connection, ora: datetime) -> None:
    """Lo stesso campo `data` delle spese: «ieri ho fatto palestra» va a ieri."""
    ids = _abitudini(conn, ora)
    ieri = ora.date() - timedelta(days=1)
    esito = _esegui(
        conn,
        ora,
        "ieri ho fatto palestra",
        {
            "azione": "segna_abitudini",
            "abitudini_fatte": ["Palestra"],
            "data": ieri.isoformat(),
        },
    )
    assert dom_abitudini.segnata(conn, ids["Palestra"], ieri) is True
    assert "di ieri" in esito.testo


def test_fatto_e_non_fatto_insieme_vince_il_non_fatto(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """«tutto tranne la meditazione»: l'eccezione è più specifica del generico."""
    ids = _abitudini(conn, ora)
    _esegui(
        conn,
        ora,
        "ho fatto tutto tranne la meditazione",
        {
            "azione": "segna_abitudini",
            "abitudini_fatte": ["Palestra", "Meditazione"],
            "abitudini_non_fatte": ["Meditazione"],
        },
    )
    assert dom_abitudini.segnata(conn, ids["Meditazione"], ora.date()) is False
    assert dom_abitudini.segnata(conn, ids["Palestra"], ora.date()) is True


def test_il_contesto_elenca_le_abitudini_col_target(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Senza l'elenco il modello non può agganciare nessun nome (§6)."""
    _abitudini(conn, ora)
    router = RouterFinto()
    assistente.interpreta(conn, ora, "x", router)  # type: ignore[arg-type]
    assert "Palestra (3/settimana)" in router.chiamate[0]["utente"]


# — la categoria: chi la decide, e quando (§6) —


def _registra_e_categorizza(
    conn: sqlite3.Connection, ora: datetime, intenzione: dict[str, Any], categoria_claude: str
) -> tuple[assistente.Esito, RouterFinto]:
    """Il giro vero: interpretazione (DeepSeek) + eventuale categoria (Claude)."""

    class Due(RouterFinto):
        def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
            self.chiamate.append({"compito": compito, **kwargs})
            if compito is Compito.CATEGORIE_SPESA:
                return {"categoria": categoria_claude, "esistente": False}
            return _forma_modello(intenzione)

    router = Due()
    (esito,) = assistente.interpreta_ed_esegui(conn, ora, "x", router)  # type: ignore[arg-type]
    return esito, router


def _compiti(router: RouterFinto) -> list[Any]:
    return [c["compito"] for c in router.chiamate]


def test_il_nome_del_negozio_non_diventa_una_categoria(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Il caso vero: «150 euro da bricoman per la vernice» → «Bricoman».

    Lo schema chiede già a DeepSeek di non inventare categorie, ma è una
    descrizione, non un vincolo. §6 assegna la *creazione* a Claude proprio
    perché un doppione creato oggi resta lì per sempre: qui si verifica che una
    categoria proposta e inesistente venga scartata, e che a decidere sia Claude.
    """
    esito, router = _registra_e_categorizza(
        conn,
        ora,
        {
            "azione": "registra_spesa",
            "titolo": "vernice per la stanza",
            "importo": 150,
            "luogo": "Bricoman",
            "categoria": "Bricoman",
        },
        categoria_claude="Casa",
    )

    (spesa,) = dom_spese.elenco(conn)
    assert spesa.categoria == "Casa"
    assert [c.nome for c in dom_spese.categorie(conn)] == ["Casa"]
    # Il negozio non è perso: sta nel suo campo, dove serve.
    assert spesa.luogo == "Bricoman"
    assert "Casa" in esito.testo
    assert Compito.CATEGORIE_SPESA in _compiti(router)


def test_una_categoria_che_esiste_gia_non_ricosta_una_chiamata(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    # §6: *assegnare* a una categoria esistente è classificazione semplice e
    # viaggia già nella chiamata che interpreta il messaggio.
    dom_spese.assicura_categoria(conn, "Alimentari", ora)
    esito, router = _registra_e_categorizza(
        conn,
        ora,
        {
            "azione": "registra_spesa",
            "titolo": "spesa",
            "importo": 40,
            "categoria": "alimentari",  # minuscolo: è la stessa categoria
        },
        categoria_claude="NON DEVE SERVIRE",
    )

    (spesa,) = dom_spese.elenco(conn)
    assert spesa.categoria == "Alimentari"
    assert "Alimentari" in esito.testo
    assert Compito.CATEGORIE_SPESA not in _compiti(router)


def test_senza_categoria_dall_interprete_decide_claude(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    esito, router = _registra_e_categorizza(
        conn,
        ora,
        {"azione": "registra_spesa", "titolo": "benzina", "importo": 60, "categoria": ""},
        categoria_claude="Trasporti",
    )
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.categoria == "Trasporti"
    assert Compito.CATEGORIE_SPESA in _compiti(router)


def test_la_categoria_si_dice_una_volta_sola(conn: sqlite3.Connection, ora: datetime) -> None:
    # `_registra_spesa` non la scrive più: la aggiunge un punto solo, dopo aver
    # sentito Claude. Senza questo comparirebbe due volte nella stessa frase.
    dom_spese.assicura_categoria(conn, "Bar", ora)
    esito, _ = _registra_e_categorizza(
        conn,
        ora,
        {"azione": "registra_spesa", "titolo": "colazione", "importo": 8, "categoria": "Bar"},
        categoria_claude="Bar",
    )
    assert esito.testo.count("Bar") == 1


def test_se_claude_non_risponde_la_spesa_da_testo_resta_comunque(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Un guasto del modello non deve costare la spesa appena detta."""

    class SoloInterprete(RouterFinto):
        def chiedi_json(self, compito: Any, **kwargs: Any) -> dict[str, Any]:
            self.chiamate.append({"compito": compito, **kwargs})
            if compito is Compito.CATEGORIE_SPESA:
                raise ProviderNonRaggiungibile("Claude non risponde")
            return _forma_modello({"azione": "registra_spesa", "titolo": "birra", "importo": 4.5})

    (esito,) = assistente.interpreta_ed_esegui(conn, ora, "x", SoloInterprete())  # type: ignore[arg-type]

    (spesa,) = dom_spese.elenco(conn)
    assert spesa.centesimi == 450
    assert spesa.categoria is None
    assert "4,50 €" in esito.testo


def test_una_spesa_registrata_si_annulla_col_bottone(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    esito = _esegui(conn, ora, "x", {"azione": "registra_spesa", "titolo": "birra", "importo": 4.5})
    assert esito.identificatore == esito.spesa_id
    assert esito.spesa_id is not None

    testo = assistente.annulla(conn, ora, Azione.REGISTRA_SPESA, identificatore=esito.spesa_id)
    assert dom_spese.elenco(conn) == []
    assert "4,50 €" in testo


@pytest.mark.parametrize("importo", [0, -3, None, "otto", True])
def test_senza_un_importo_valido_non_nasce_nessuna_spesa(
    conn: sqlite3.Connection, ora: datetime, importo: Any
) -> None:
    # `True` compreso: è un `int` in Python, e senza escluderlo diventerebbe
    # una spesa da un centesimo.
    esito = _esegui(
        conn, ora, "x", {"azione": "registra_spesa", "titolo": "qualcosa", "importo": importo}
    )
    assert dom_spese.elenco(conn) == []
    assert "quanto hai speso" in esito.testo


def test_gli_spiccioli_non_si_perdono_nel_passaggio_a_centesimi(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    _esegui(conn, ora, "x", {"azione": "registra_spesa", "titolo": "caffè", "importo": 8.15})
    (spesa,) = dom_spese.elenco(conn)
    assert spesa.centesimi == 815


def test_una_spesa_senza_categoria_la_chiede_a_claude_a_parte(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    # Seconda chiamata, e solo a Claude: succede quando nessuna categoria
    # esistente calzava (§6).
    esito = _esegui(
        conn, ora, "x", {"azione": "registra_spesa", "titolo": "spesa al super", "importo": 40}
    )
    assert esito.spesa_id is not None
    router = RouterFinto({"categoria": "Alimentari", "esistente": False})

    nome = assistente.categorizza_se_serve(conn, ora, esito.spesa_id, router)  # type: ignore[arg-type]

    assert nome == "Alimentari"
    assert dom_spese.leggi(conn, esito.spesa_id).categoria == "Alimentari"
    assert router.chiamate[0]["compito"].value == "categorie_spesa"


def test_una_spesa_gia_categorizzata_non_ricosta_una_chiamata(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    # La categoria deve **esistere** perché l'interprete possa assegnarla: è la
    # regola di §6, e senza questa riga la spesa nascerebbe senza categoria e il
    # test verificherebbe un'altra cosa.
    dom_spese.assicura_categoria(conn, "Alimentari", ora)
    esito = _esegui(
        conn,
        ora,
        "x",
        {"azione": "registra_spesa", "titolo": "spesa", "importo": 40, "categoria": "Alimentari"},
    )
    assert esito.spesa_id is not None
    router = RouterFinto()

    assert assistente.categorizza_se_serve(conn, ora, esito.spesa_id, router) == "Alimentari"  # type: ignore[arg-type]
    assert router.chiamate == []


def test_se_claude_non_risponde_la_spesa_resta_senza_categoria(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    esito = _esegui(conn, ora, "x", {"azione": "registra_spesa", "titolo": "spesa", "importo": 40})
    assert esito.spesa_id is not None
    router = RouterFinto(errore=ProviderNonRaggiungibile("giù"))

    assert assistente.categorizza_se_serve(conn, ora, esito.spesa_id, router) is None  # type: ignore[arg-type]
    # La spesa resta nei conti: si sistema dopo dalla dashboard.
    assert dom_spese.leggi(conn, esito.spesa_id).categoria is None


def test_segna_voce_presa(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = dom_lista.aggiungi(conn, nome="mele", ora=ora)
    _esegui(conn, ora, "ho preso le mele", {"azione": "segna_voce_presa", "riferimento": "mele"})
    assert dom_lista.leggi(conn, voce.id).preso is True


def test_azione_nessuna_non_tocca_niente(conn: sqlite3.Connection, ora: datetime) -> None:
    dom_task.crea(conn, titolo="Qualcosa", ora=ora)
    esito = _esegui(conn, ora, "ciao come va", {"azione": "nessuna"})
    assert not esito.ha_cambiato_qualcosa
    assert dom_task.elenco(conn, fatto=True) == []


@pytest.mark.parametrize("payload", [{}, {"azione": "cancella_tutto"}, {"azione": None}])
def test_un_azione_inventata_dal_modello_non_fa_niente(
    conn: sqlite3.Connection, ora: datetime, payload: dict[str, Any]
) -> None:
    """Il modello non tocca il database: al massimo chiede una cosa non prevista."""
    dom_task.crea(conn, titolo="Qualcosa", ora=ora)
    esito = _esegui(conn, ora, "x", payload)
    assert not esito.ha_cambiato_qualcosa
    assert len(dom_task.elenco(conn)) == 1


def test_messaggio_vuoto(conn: sqlite3.Connection, ora: datetime) -> None:
    esito = _esegui(conn, ora, "   ", {"azione": "aggiungi_task", "titolo": "x"})
    assert not esito.ha_cambiato_qualcosa
    assert dom_task.elenco(conn) == []


# — errori del router, tradotti in frasi comprensibili —


def test_senza_chiave_lo_dice(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto(errore=ProviderNonConfigurato("manca la chiave"))
    (esito,) = assistente.interpreta_ed_esegui(conn, ora, "ciao", router)  # type: ignore[arg-type]
    assert "non è ancora configurato" in esito.testo
    assert not esito.ha_cambiato_qualcosa


def test_provider_giu_invita_a_riprovare(conn: sqlite3.Connection, ora: datetime) -> None:
    router = RouterFinto(errore=ProviderNonRaggiungibile("timeout"))
    (esito,) = assistente.interpreta_ed_esegui(conn, ora, "ciao", router)  # type: ignore[arg-type]
    assert "Riprova" in esito.testo


# — annullamento —


def test_annulla_una_regola_la_cancella_invece_di_scartarla(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Scartare è una decisione che resta e che la pagina mostra; qui si sta
    disfacendo un gesto di trenta secondi fa che il modello ha capito male, e
    una regola nata per errore non deve finire fra le scelte che non hai fatto.
    """
    esito = _esegui(
        conn,
        ora,
        "x",
        {
            "azione": "crea_regola",
            "titolo": "prendi la creatina",
            "regola_trigger": "orario",
            "regola_ora": "19:00",
        },
    )
    assert esito.regola_id is not None
    # L'id della regola è ciò che il bottone porta con sé.
    assert esito.identificatore == esito.regola_id

    testo = assistente.annulla(conn, ora, Azione.CREA_REGOLA, identificatore=esito.regola_id)

    assert dom_regole.elenco(conn) == []
    assert "prendi la creatina" in testo


def test_annullare_una_regola_che_non_c_e_piu(conn: sqlite3.Connection, ora: datetime) -> None:
    testo = assistente.annulla(conn, ora, Azione.CREA_REGOLA, identificatore=999)
    assert "niente da annullare" in testo


def test_annulla_una_creazione(conn: sqlite3.Connection, ora: datetime) -> None:
    esito = _esegui(conn, ora, "x", {"azione": "aggiungi_task", "titolo": "Sbagliato"})
    assert esito.task_id is not None

    testo = assistente.annulla(conn, ora, Azione.AGGIUNGI_TASK, identificatore=esito.task_id)
    assert dom_task.elenco(conn) == []
    assert "Sbagliato" in testo


def test_annulla_una_chiusura(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="Bolletta", ora=ora)
    _esegui(conn, ora, "x", {"azione": "completa_task", "riferimento": "Bolletta"})

    assistente.annulla(conn, ora, Azione.COMPLETA_TASK, identificatore=task.id)
    riaperto = dom_task.leggi(conn, task.id)
    assert riaperto.fatto is False
    assert riaperto.completato_il is None


def test_annulla_un_rinvio_scala_anche_il_contatore(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    task = dom_task.crea(conn, titolo="Dentista", ora=ora, scadenza=ora.date())
    _esegui(conn, ora, "x", {"azione": "rinvia_task", "riferimento": "Dentista", "giorni": 2})

    assistente.annulla(conn, ora, Azione.RINVIA_TASK, identificatore=task.id, giorni=2)
    tornato = dom_task.leggi(conn, task.id)
    assert tornato.scadenza == ora.date()
    # Un rinvio annullato non deve restare scritto nella storia del task.
    assert tornato.rinvii == 0


def test_annulla_un_aggiunta_alla_lista(conn: sqlite3.Connection, ora: datetime) -> None:
    esito = _esegui(conn, ora, "x", {"azione": "aggiungi_voce_spesa", "titolo": "capperi"})
    assert esito.voce_id is not None
    assistente.annulla(conn, ora, Azione.AGGIUNGI_SPESA, identificatore=esito.voce_id)
    assert dom_lista.elenco(conn) == []


def test_annulla_una_spunta(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = dom_lista.aggiungi(conn, nome="mele", ora=ora)
    dom_lista.imposta_preso(conn, voce.id, True, ora)
    assistente.annulla(conn, ora, Azione.SEGNA_PRESO, identificatore=voce.id)
    assert dom_lista.leggi(conn, voce.id).preso is False


def test_annullare_qualcosa_che_non_c_e_piu(conn: sqlite3.Connection, ora: datetime) -> None:
    testo = assistente.annulla(conn, ora, Azione.AGGIUNGI_TASK, identificatore=999)
    assert "non esiste più" in testo


# — diario (§8.4): il messaggio che racconta invece di chiedere —


def test_una_frase_raccontata_diventa_materiale_da_diario(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    esito = _esegui(
        conn,
        ora,
        "che giornata pesante",
        {"azione": "annota_diario", "titolo": "giornata pesante"},
    )

    assert esito.azione is Azione.ANNOTA_DIARIO
    assert esito.frammento_id is not None
    # Il grezzo si salva com'è: il riassunto è un altro passaggio, e passa da
    # Claude a fine giornata (§6).
    voce = dom_diario.leggi_giorno(conn, ora.date())
    assert voce is not None
    assert voce.grezzo == "giornata pesante"
    assert voce.riassunto_approvato is None


def test_una_nota_di_diario_senza_testo_non_scrive_niente(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    esito = _esegui(conn, ora, "boh", {"azione": "annota_diario", "titolo": "  "})

    assert esito.ha_cambiato_qualcosa is False
    assert dom_diario.leggi_giorno(conn, ora.date()) is None


def test_il_bottone_annulla_punta_al_frammento_giusto(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """`identificatore` è ciò che il bot impacchetta nel callback_data."""
    esito = _esegui(conn, ora, "x", {"azione": "annota_diario", "titolo": "prima"})
    assert esito.identificatore == esito.frammento_id


def test_annulla_una_nota_di_diario(conn: sqlite3.Connection, ora: datetime) -> None:
    _esegui(conn, ora, "x", {"azione": "annota_diario", "titolo": "resta"})
    esito = _esegui(conn, ora, "y", {"azione": "annota_diario", "titolo": "da togliere"})
    assert esito.frammento_id is not None

    testo = assistente.annulla(conn, ora, Azione.ANNOTA_DIARIO, identificatore=esito.frammento_id)

    assert "da togliere" in testo
    voce = dom_diario.leggi_giorno(conn, ora.date())
    assert voce is not None and voce.grezzo == "resta"


def test_annullare_una_nota_gia_tolta(conn: sqlite3.Connection, ora: datetime) -> None:
    esito = _esegui(conn, ora, "x", {"azione": "annota_diario", "titolo": "unica"})
    assert esito.frammento_id is not None
    assistente.annulla(conn, ora, Azione.ANNOTA_DIARIO, identificatore=esito.frammento_id)

    testo = assistente.annulla(conn, ora, Azione.ANNOTA_DIARIO, identificatore=esito.frammento_id)
    assert "non esiste più" in testo


def test_il_diario_e_fra_le_azioni_offerte_al_modello() -> None:
    """Un'azione che non è nell'enum dello schema il modello non la può scegliere."""
    consentite = assistente.SCHEMA_AZIONE["properties"]["azione"]["enum"]
    assert "annota_diario" in consentite


# — più cose in un messaggio solo —


def test_un_racconto_con_un_promemoria_finisce_in_tutti_e_due(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Il bug osservato: il task veniva creato, il racconto spariva in silenzio.

    Finché lo schema ammetteva una sola azione il modello doveva sceglierne
    una — e il prompt gli diceva pure di preferire quella pratica. Il diario
    restava vuoto senza che nessuno se ne accorgesse.
    """
    esiti = _esegui_tutte(
        conn,
        ora,
        "Oggi laboratorio pesante, tre ore sullo stesso bug. Devo ricordarmi di"
        " mandare la mail al prof.",
        {"azione": "aggiungi_task", "titolo": "Mandare la mail al prof"},
        {"azione": "annota_diario", "titolo": "Oggi laboratorio pesante, tre ore sullo stesso bug"},
    )

    assert [t.titolo for t in dom_task.elenco(conn, fatto=False)] == ["Mandare la mail al prof"]
    voce = dom_diario.leggi_giorno(conn, ora.date())
    assert voce is not None
    assert [f.testo for f in voce.frammenti] == [
        "Oggi laboratorio pesante, tre ore sullo stesso bug"
    ]
    # Due esiti, uno per cosa fatta: nel bot diventano due messaggi, ognuno col
    # suo «Annulla».
    assert [e.azione for e in esiti] == [Azione.AGGIUNGI_TASK, Azione.ANNOTA_DIARIO]
    assert esiti[0].task_id is not None
    assert esiti[1].frammento_id is not None


def test_il_diario_e_sempre_l_ultimo(conn: sqlite3.Connection, ora: datetime) -> None:
    """L'ordine non lo decide il modello: prima cosa è stato fatto, poi la nota."""
    esiti = _esegui_tutte(
        conn,
        ora,
        "x",
        {"azione": "annota_diario", "titolo": "Giornata storta"},
        {"azione": "registra_spesa", "titolo": "benzina", "importo": 12},
    )
    assert [e.azione for e in esiti] == [Azione.REGISTRA_SPESA, Azione.ANNOTA_DIARIO]


def test_due_promemoria_sono_due_task(conn: sqlite3.Connection, ora: datetime) -> None:
    esiti = _esegui_tutte(
        conn,
        ora,
        "ricordami di chiamare l'officina e di comprare il regalo",
        {"azione": "aggiungi_task", "titolo": "Chiamare l'officina"},
        {"azione": "aggiungi_task", "titolo": "Comprare il regalo"},
    )
    assert len(esiti) == 2
    assert {t.titolo for t in dom_task.elenco(conn, fatto=False)} == {
        "Chiamare l'officina",
        "Comprare il regalo",
    }


def test_un_doppione_esatto_si_conta_una_volta(conn: sqlite3.Connection, ora: datetime) -> None:
    """Un modello che si inceppa non deve creare due task uguali e due conferme."""
    esiti = _esegui_tutte(
        conn,
        ora,
        "x",
        {"azione": "aggiungi_task", "titolo": "Chiamare l'officina"},
        {"azione": "aggiungi_task", "titolo": "chiamare l'officina"},
    )
    assert len(esiti) == 1
    assert len(dom_task.elenco(conn, fatto=False)) == 1


def test_il_diario_non_si_spezza_in_due(conn: sqlite3.Connection, ora: datetime) -> None:
    """Il racconto è uno: due annota_diario darebbero due conferme per un gesto solo."""
    esiti = _esegui_tutte(
        conn,
        ora,
        "x",
        {"azione": "annota_diario", "titolo": "Prima parte"},
        {"azione": "annota_diario", "titolo": "Seconda parte"},
    )
    assert len(esiti) == 1
    voce = dom_diario.leggi_giorno(conn, ora.date())
    assert voce is not None
    assert [f.testo for f in voce.frammenti] == ["Prima parte"]


def test_una_nessuna_accanto_a_un_azione_sparisce(conn: sqlite3.Connection, ora: datetime) -> None:
    esiti = _esegui_tutte(
        conn,
        ora,
        "x",
        {"azione": "nessuna"},
        {"azione": "aggiungi_task", "titolo": "Cosa"},
    )
    assert [e.azione for e in esiti] == [Azione.AGGIUNGI_TASK]


def test_una_lista_vuota_risponde_comunque(conn: sqlite3.Connection, ora: datetime) -> None:
    """Non si resta mai in silenzio: chi ha scritto deve leggere qualcosa."""
    router = RouterFinto({"azioni": []})
    esiti = assistente.interpreta_ed_esegui(conn, ora, "ciao", router)  # type: ignore[arg-type]
    assert len(esiti) == 1
    assert esiti[0].testo
    assert not esiti[0].ha_cambiato_qualcosa


def test_troppe_azioni_si_fermano_al_tetto(conn: sqlite3.Connection, ora: datetime) -> None:
    """Un modello impazzito non riempie la chat di conferme."""
    esiti = _esegui_tutte(
        conn,
        ora,
        "x",
        *[{"azione": "aggiungi_task", "titolo": f"Cosa {i}"} for i in range(10)],
    )
    assert len(esiti) == assistente.MASSIMO_AZIONI


def test_la_vecchia_forma_a_azione_singola_funziona_ancora(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """DeepSeek garantisce JSON valido, non che rispetti lo schema (`deepseek.py`).

    Una risposta che ignora la lista e mette `azione` in cima non deve
    diventare un messaggio perso.
    """
    router = RouterFinto({"azione": "aggiungi_task", "titolo": "Cosa"})
    (esito,) = assistente.interpreta_ed_esegui(conn, ora, "x", router)  # type: ignore[arg-type]
    assert esito.azione is Azione.AGGIUNGI_TASK
    assert [t.titolo for t in dom_task.elenco(conn, fatto=False)] == ["Cosa"]


def test_il_segnale_si_attacca_all_ultimo_messaggio(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """La domanda di chiarimento è una parentesi su tutto, non su una azione."""
    esiti = _esegui_tutte(
        conn,
        ora,
        "x",
        {"azione": "aggiungi_task", "titolo": "Cosa"},
        {
            "azione": "annota_diario",
            "titolo": "Il frontend mi annoia",
            "segnale": "ambiguo",
            "segnale_estratto": "Preferisce il backend",
            "segnale_domanda": "Vale sempre o era la giornata?",
        },
    )
    assert esiti[0].domanda_chiarimento == ""
    assert esiti[-1].domanda_chiarimento == "Vale sempre o era la giornata?"
    assert esiti[-1].candidato_id is not None
    # Il candidato è uno solo, non uno per azione.
    assert len(dom_profilo.da_rivedere(conn)) == 1


def test_lo_schema_chiede_una_lista_di_azioni() -> None:
    """La causa del bug era qui: un solo posto per una sola azione."""
    assert assistente.SCHEMA_INTENZIONE["properties"]["azioni"]["type"] == "array"
    assert "azione" in assistente.SCHEMA_AZIONE["properties"]


# — canale passivo per il profilo (§8.4) —


def test_un_segnale_chiaro_diventa_un_candidato(conn: sqlite3.Connection, ora: datetime) -> None:
    _esegui(
        conn,
        ora,
        "oggi ho fatto un sito, che palle il frontend",
        {
            "azione": "annota_diario",
            "titolo": "ho fatto un sito, che palle il frontend",
            "segnale": "chiaro",
            "segnale_estratto": "Preferisce il backend al frontend",
        },
    )

    (candidato,) = dom_profilo.da_rivedere(conn)
    assert candidato.estratto == "Preferisce il backend al frontend"
    # Il messaggio intero resta: alla revisione serve poter vedere il contesto.
    assert "che palle il frontend" in candidato.messaggio_origine


def test_azione_e_segnale_sono_indipendenti(conn: sqlite3.Connection, ora: datetime) -> None:
    """Un messaggio può essere insieme un task e un segnale sul profilo."""
    esito = _esegui(
        conn,
        ora,
        "devo finire il sito",
        {
            "azione": "aggiungi_task",
            "titolo": "Finire il sito",
            "segnale": "chiaro",
            "segnale_estratto": "Lavora a progetti web",
        },
    )

    assert esito.task_id is not None
    assert esito.candidato_id is not None
    assert len(dom_task.elenco(conn)) == 1
    assert len(dom_profilo.da_rivedere(conn)) == 1


def test_l_annulla_punta_all_azione_non_al_candidato(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """Il bottone disfa quello che Custode ha fatto, non la raccolta silenziosa."""
    esito = _esegui(
        conn,
        ora,
        "devo finire il sito",
        {
            "azione": "aggiungi_task",
            "titolo": "Finire il sito",
            "segnale": "chiaro",
            "segnale_estratto": "Lavora a progetti web",
        },
    )
    assert esito.identificatore == esito.task_id


@pytest.mark.parametrize("segnale", ["nessuno", "boh", "", None])
def test_niente_segnale_niente_candidato(
    conn: sqlite3.Connection, ora: datetime, segnale: object
) -> None:
    """Un valore fuori dai tre previsti vale «nessuno»: sul profilo si sbaglia
    per difetto."""
    _esegui(
        conn,
        ora,
        "ciao",
        {"azione": "nessuna", "segnale": segnale, "segnale_estratto": "Qualcosa"},
    )
    assert dom_profilo.da_rivedere(conn) == []


def test_un_segnale_ambiguo_porta_la_domanda_nell_esito(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    esito = _esegui(
        conn,
        ora,
        "che palle",
        {
            "azione": "nessuna",
            "segnale": "ambiguo",
            "segnale_estratto": "Non sopporta il frontend",
            "segnale_domanda": "Vale sempre o era la giornata?",
        },
    )

    assert esito.domanda_chiarimento == "Vale sempre o era la giornata?"
    assert esito.candidato_id is not None


def test_il_segnale_si_registra_anche_se_l_azione_non_fa_niente(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    """«nessuna» è una risposta corretta, e non deve buttare via il segnale."""
    _esegui(
        conn,
        ora,
        "il frontend mi annoia",
        {
            "azione": "nessuna",
            "segnale": "chiaro",
            "segnale_estratto": "Il frontend lo annoia",
        },
    )
    assert len(dom_profilo.da_rivedere(conn)) == 1
