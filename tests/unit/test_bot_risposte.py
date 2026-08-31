"""Cosa risponde il bot: è testabile perché non tocca Telegram (§8.1)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from custode_bot import azioni, risposte
from custode_core.dominio import lista_spesa as dom_lista
from custode_core.dominio import task as dom_task


def _dati_bottoni(risposta: risposte.Risposta) -> list[str]:
    return [b.dato for riga in risposta.bottoni for b in riga]


# — riepilogo —


def test_oggi_quando_non_c_e_niente(conn: sqlite3.Connection, ora: datetime) -> None:
    assert risposte.riepilogo_oggi(conn, ora).testo == "Niente in sospeso."


def test_oggi_mostra_ritardi_scadenze_e_lista(conn: sqlite3.Connection, ora: datetime) -> None:
    dom_task.crea(conn, titolo="bolletta", ora=ora, scadenza=ora.date() - timedelta(days=2))
    dom_task.crea(conn, titolo="officina", ora=ora, scadenza=datetime(2026, 8, 31, 18, 0))
    dom_task.crea(conn, titolo="paper", ora=ora)  # senza scadenza: non è "oggi"
    dom_lista.aggiungi(conn, nome="latte", ora=ora)

    testo = risposte.riepilogo_oggi(conn, ora).testo
    assert "In ritardo" in testo and "bolletta" in testo
    assert "Oggi" in testo and "officina" in testo
    assert "18:00" in testo
    assert "1 voce da prendere" in testo
    assert "paper" not in testo


# — task —


def test_elenco_task_vuoto(conn: sqlite3.Connection, ora: datetime) -> None:
    risposta = risposte.elenco_task(conn, ora)
    assert risposta.testo == "Nessun task aperto."
    assert risposta.bottoni == []


def test_elenco_task_ha_spunta_e_rinvio_per_ciascuno(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    primo = dom_task.crea(conn, titolo="uno", ora=ora)
    secondo = dom_task.crea(conn, titolo="due", ora=ora)

    risposta = risposte.elenco_task(conn, ora)
    assert _dati_bottoni(risposta) == [
        azioni.task_fatto(primo.id, "task"),
        azioni.task_rinvia(primo.id, "task"),
        azioni.task_fatto(secondo.id, "task"),
        azioni.task_rinvia(secondo.id, "task"),
    ]


def test_i_task_chiusi_spariscono_dall_elenco(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="paper", ora=ora)
    dom_task.imposta_fatto(conn, task.id, True, ora)
    assert risposte.elenco_task(conn, ora).testo == "Nessun task aperto."


def test_nuovo_task_chiede_la_scadenza_coi_bottoni(conn: sqlite3.Connection, ora: datetime) -> None:
    risposta = risposte.nuovo_task(conn, ora, "  Chiamare l'officina  ")
    assert "Chiamare l&#x27;officina" in risposta.testo  # testo dell'utente, messo al sicuro
    assert "Quando scade?" in risposta.testo

    creato = dom_task.elenco(conn)[0]
    assert creato.origine == "telegram"  # si vedrà in "Da dove arrivano"
    assert _dati_bottoni(risposta) == [
        azioni.task_scadenza(creato.id, "oggi"),
        azioni.task_scadenza(creato.id, "domani"),
        azioni.task_scadenza(creato.id, "settimana"),
        azioni.task_scadenza(creato.id, "mai"),
    ]


def test_nuovo_task_senza_titolo(conn: sqlite3.Connection, ora: datetime) -> None:
    assert "Serve un titolo" in risposte.nuovo_task(conn, ora, "   ").testo
    assert dom_task.elenco(conn) == []


def test_titolo_con_html_non_rompe_il_messaggio(conn: sqlite3.Connection, ora: datetime) -> None:
    # Un titolo con dei segni di markup non deve poter alterare il messaggio.
    risposte.nuovo_task(conn, ora, "<b>grassetto</b> & co")
    testo = risposte.elenco_task(conn, ora).testo
    assert "&lt;b&gt;grassetto&lt;/b&gt; &amp; co" in testo


# — lista della spesa —


def test_lista_vuota(conn: sqlite3.Connection, ora: datetime) -> None:
    assert risposte.elenco_lista(conn).testo == "Lista della spesa vuota."


def test_lista_raggruppata_per_reparto(conn: sqlite3.Connection, ora: datetime) -> None:
    dom_lista.aggiungi(conn, nome="latte", ora=ora, quantita="1 L", reparto="Latticini")
    dom_lista.aggiungi(conn, nome="mele", ora=ora, reparto="Frutta e verdura")
    dom_lista.aggiungi(conn, nome="carta forno", ora=ora)

    testo = risposte.elenco_lista(conn).testo
    assert testo.index("Frutta e verdura") < testo.index("Latticini") < testo.index("Altro")
    assert "1 L" in testo
    assert len(_dati_bottoni(risposte.elenco_lista(conn))) == 3


def test_aggiungi_voce_e_doppione(conn: sqlite3.Connection, ora: datetime) -> None:
    assert "Aggiunto" in risposte.aggiungi_voce(conn, ora, "latte").testo
    # La seconda volta lo dice, invece di far credere di aver aggiunto due latti.
    assert "era già in lista" in risposte.aggiungi_voce(conn, ora, "Latte").testo
    assert len(dom_lista.elenco(conn)) == 1


def test_aggiungi_voce_vuota(conn: sqlite3.Connection, ora: datetime) -> None:
    assert "Serve una voce" in risposte.aggiungi_voce(conn, ora, "  ").testo


def test_svuota_chiede_conferma(conn: sqlite3.Connection, ora: datetime) -> None:
    assert "niente di già preso" in risposte.chiedi_svuota(conn).testo

    voce = dom_lista.aggiungi(conn, nome="latte", ora=ora)
    dom_lista.imposta_preso(conn, voce.id, True, ora)

    risposta = risposte.chiedi_svuota(conn)
    assert _dati_bottoni(risposta) == [azioni.svuota(True), azioni.svuota(False)]


# — bottoni —


def test_bottone_spunta_un_task_e_ridisegna_l_elenco(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    task = dom_task.crea(conn, titolo="paper", ora=ora)
    dom_task.crea(conn, titolo="slide", ora=ora)

    risposta = risposte.esegui_azione(conn, ora, azioni.task_fatto(task.id, "task"))
    assert dom_task.leggi(conn, task.id).fatto is True
    assert "paper" not in risposta.testo
    assert "slide" in risposta.testo  # il messaggio si aggiorna in posto


def test_il_bottone_ridisegna_la_vista_da_cui_e_partito(
    conn: sqlite3.Connection, ora: datetime
) -> None:
    task = dom_task.crea(conn, titolo="paper", ora=ora, scadenza=ora.date())
    dom_lista.aggiungi(conn, nome="latte", ora=ora)

    da_oggi = risposte.esegui_azione(conn, ora, azioni.task_fatto(task.id, "oggi"))
    assert "Lista spesa" in da_oggi.testo  # è il riepilogo, non l'elenco task


def test_bottone_rinvia(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="dentista", ora=ora, scadenza=ora.date())

    risposte.esegui_azione(conn, ora, azioni.task_rinvia(task.id, "task"))
    aggiornato = dom_task.leggi(conn, task.id)
    assert aggiornato.scadenza == ora.date() + timedelta(days=1)
    assert aggiornato.rinvii == 1


def test_bottoni_di_scadenza(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="officina", ora=ora)

    risposta = risposte.esegui_azione(conn, ora, azioni.task_scadenza(task.id, "domani"))
    assert dom_task.leggi(conn, task.id).scadenza == date(2026, 9, 1)
    assert "domani" in risposta.testo

    risposte.esegui_azione(conn, ora, azioni.task_scadenza(task.id, "settimana"))
    assert dom_task.leggi(conn, task.id).scadenza == date(2026, 9, 7)


def test_bottone_senza_scadenza_non_ne_mette_una(conn: sqlite3.Connection, ora: datetime) -> None:
    task = dom_task.crea(conn, titolo="paper", ora=ora)
    risposte.esegui_azione(conn, ora, azioni.task_scadenza(task.id, "mai"))
    assert dom_task.leggi(conn, task.id).scadenza is None


def test_bottone_spunta_una_voce_della_spesa(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = dom_lista.aggiungi(conn, nome="latte", ora=ora)
    risposte.esegui_azione(conn, ora, azioni.voce_presa(voce.id, "lista"))
    assert dom_lista.leggi(conn, voce.id).preso is True


def test_conferma_e_annullamento_dello_svuotamento(conn: sqlite3.Connection, ora: datetime) -> None:
    voce = dom_lista.aggiungi(conn, nome="latte", ora=ora)
    dom_lista.imposta_preso(conn, voce.id, True, ora)

    risposte.esegui_azione(conn, ora, azioni.svuota(False))
    assert len(dom_lista.elenco(conn)) == 1  # annullato: la riga è ancora lì

    risposte.esegui_azione(conn, ora, azioni.svuota(True))
    assert dom_lista.elenco(conn) == []


def test_bottone_su_qualcosa_che_non_esiste_piu(conn: sqlite3.Connection, ora: datetime) -> None:
    # Succede col messaggio vecchio ancora in cronologia sul telefono.
    risposta = risposte.esegui_azione(conn, ora, azioni.task_fatto(999, "task"))
    assert risposta.testo == "Quella voce non esiste più."


def test_bottone_con_dato_malformato(conn: sqlite3.Connection, ora: datetime) -> None:
    for dato in ("", "boh", "t:inventata:1:t", "t:fatto:non-un-numero:t"):
        assert risposte.esegui_azione(conn, ora, dato).testo == "Questo bottone non è più valido."


def test_aiuto_elenca_i_comandi() -> None:
    testo = risposte.aiuto().testo
    for comando in ("/oggi", "/task", "/nuovo", "/lista", "/aggiungi", "/svuota"):
        assert comando in testo
