"""I tipi di evento, adesso che li decidi tu (ARCHITECTURE.md §8.10, pezzo 6).

Erano quattro e fissi, incisi in un CHECK e in una StrEnum. Adesso sono righe di
`calendar_tags`, e quello che qui si verifica è soprattutto ciò che **non**
succede quando li tocchi: rinominarne uno non deve toccare nessun evento,
archiviarne uno non deve toglierlo agli impegni che ce l'hanno, e cancellarne
uno in uso non deve poter succedere affatto.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from custode_core.dominio import calendario as dom

ORA = datetime(2026, 9, 15, 8, 41)


def _evento(
    conn: sqlite3.Connection,
    *,
    id_esterno: str = "ev1",
    titolo: str = "Analisi Matematica I",
    serie: str = "",
    tipo: str = dom.SLUG_ALTRO,
) -> int:
    cursore = conn.execute(
        "INSERT INTO calendar_events (fonte, id_esterno, titolo, inizio, fine, serie_id,"
        " tipo, sincronizzato_il) VALUES ('google', ?, ?, ?, ?, ?, ?, ?)",
        (
            id_esterno,
            titolo,
            "2026-09-15T09:00:00",
            "2026-09-15T11:00:00",
            serie,
            tipo,
            ORA.isoformat(timespec="seconds"),
        ),
    )
    return int(cursore.lastrowid or 0)


# — quello che c'era prima è ancora lì —


def test_i_quattro_di_prima_ci_sono_come_dati_iniziali(conn: sqlite3.Connection) -> None:
    """La 009 non cambia cosa Custode sa fare, cambia da dove lo legge."""
    tag = dom.elenco_tag(conn)

    assert [t.slug for t in tag] == ["lezione", "palestra", "viaggio", "altro"]
    assert [t.nome for t in tag] == ["Lezione", "Palestra", "Viaggio", "Altro"]
    # Le descrizioni sono quelle del prompt di ieri, non dei segnaposto.
    assert "laboratori" in dom.tag_per_slug(conn, "lezione").descrizione
    assert "treni" in dom.tag_per_slug(conn, "viaggio").descrizione


def test_altro_e_l_unico_di_sistema(conn: sqlite3.Connection) -> None:
    """È il tipo con cui nasce ogni evento: senza di lui non c'è un default."""
    di_sistema = [t.slug for t in dom.elenco_tag(conn) if t.di_sistema]
    assert di_sistema == [dom.SLUG_ALTRO]


def test_altro_resta_in_fondo_anche_dopo_che_ne_crei_dei_tuoi(conn: sqlite3.Connection) -> None:
    """In un menu il ripiego va in fondo: in mezzo si legge come una scelta."""
    dom.crea_tag(conn, nome="Spesa", descrizione="il supermercato.", ora=ORA)
    assert [t.slug for t in dom.elenco_tag(conn)][-1] == dom.SLUG_ALTRO


# — crearne uno —


def test_un_tipo_nuovo_nasce_attivo_e_con_lo_slug_ricavato_dal_nome(
    conn: sqlite3.Connection,
) -> None:
    tag = dom.crea_tag(conn, nome="Spesa grossa", descrizione="il supermercato.", ora=ORA)

    assert tag.slug == "spesa_grossa"
    assert tag.nome == "Spesa grossa"
    assert tag.attivo is True
    assert tag.di_sistema is False


@pytest.mark.parametrize(
    ("nome", "atteso"),
    [
        ("Palestra", "palestra"),
        ("Visite mediche", "visite_mediche"),
        ("Caffè con Andrea", "caffe_con_andrea"),
        ("  Spesa   grossa  ", "spesa_grossa"),
        ("Pausa/riposo", "pausa_riposo"),
        ("Corso 2026", "corso_2026"),
        ("Università!!!", "universita"),
    ],
)
def test_lo_slug_regge_come_identificatore(
    conn: sqlite3.Connection, nome: str, atteso: str
) -> None:
    """Minuscole, niente accenti, niente da virgolettare.

    Lo slug finisce in un URL, in un enum JSON e in `calendar_events.tipo`: se
    ne uscisse uno con uno spazio o un accento, il CHECK della 009 lo
    rifiuterebbe — ed è giusto che sia così, ma l'errore arriverebbe da SQLite
    invece che da qui.
    """
    assert dom.slug_da(nome) == atteso


def test_un_nome_senza_lettere_ne_cifre_si_rifiuta_subito(conn: sqlite3.Connection) -> None:
    """Non c'è niente da cui ricavare un identificatore, e inventarne uno
    darebbe un tipo che nel database non si riconosce più."""
    with pytest.raises(ValueError, match="lettera o cifra"):
        dom.crea_tag(conn, nome="🏋️", descrizione="palestra.", ora=ORA)


def test_un_tipo_senza_descrizione_non_si_crea(conn: sqlite3.Connection) -> None:
    """La descrizione è la riga che legge il modello: senza, sbaglia."""
    with pytest.raises(ValueError, match="descrizione"):
        dom.crea_tag(conn, nome="Spesa", descrizione="   ", ora=ORA)


def test_un_nome_gia_usato_non_apre_un_doppione(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.NomeTagGiaUsato, match="Palestra"):
        dom.crea_tag(conn, nome="palestra", descrizione="altro sport.", ora=ORA)


# — rinominarne uno: il punto di tutta la forma scelta —


def test_rinominare_non_tocca_nessun_evento(conn: sqlite3.Connection) -> None:
    """È la ragione per cui un evento porta lo slug e non l'etichetta.

    Se `calendar_events.tipo` contenesse «Palestra», rinominare vorrebbe dire
    riscrivere ogni riga che ce l'ha — e ogni riga che *non* si riesce a
    riscrivere resterebbe con un tipo che non esiste più.
    """
    evento_id = _evento(conn, tipo="palestra")

    tag = dom.modifica_tag(conn, "palestra", nome="Allenamento")

    assert tag.slug == "palestra"
    assert tag.nome == "Allenamento"
    assert dom.per_id(conn, evento_id).tipo == "palestra"
    # E la pagina mostra il nome nuovo, senza che l'evento sia stato toccato.
    assert dom.etichette(dom.mappa_tag(conn), "palestra") == "Allenamento"


def test_rinominare_col_nome_di_un_altro_non_si_puo(conn: sqlite3.Connection) -> None:
    """Due «Palestra» renderebbero ambiguo sia il menu sia l'elenco del modello."""
    with pytest.raises(dom.NomeTagGiaUsato, match="Viaggio"):
        dom.modifica_tag(conn, "palestra", nome="viaggio")


def test_anche_altro_si_rinomina(conn: sqlite3.Connection) -> None:
    """È ciò che *fa* a essere di sistema, non come si chiama."""
    tag = dom.modifica_tag(conn, dom.SLUG_ALTRO, nome="Varie")

    assert tag.nome == "Varie"
    assert tag.slug == dom.SLUG_ALTRO
    assert tag.di_sistema is True


def test_la_descrizione_si_riscrive_quando_il_modello_sbaglia(conn: sqlite3.Connection) -> None:
    tag = dom.modifica_tag(
        conn, "viaggio", descrizione="solo treni e voli, non gli spostamenti in città."
    )
    assert tag.descrizione == "solo treni e voli, non gli spostamenti in città."


# — archiviarne uno —


def test_archiviare_lo_toglie_dal_menu_e_lo_lascia_agli_eventi(conn: sqlite3.Connection) -> None:
    """La storia di cos'era un impegno non si riscrive perché oggi hai cambiato idea."""
    evento_id = _evento(conn, tipo="palestra")

    dom.modifica_tag(conn, "palestra", attivo=False)

    assert [t.slug for t in dom.elenco_tag(conn, solo_attivi=True)] == [
        "lezione",
        "viaggio",
        "altro",
    ]
    assert dom.per_id(conn, evento_id).tipo == "palestra"
    # E l'etichetta si mostra lo stesso: `elenco_tag` senza filtro li dà tutti.
    assert dom.etichette(dom.mappa_tag(conn), "palestra") == "Palestra"


def test_riprendere_un_tipo_archiviato_lo_rimette_dov_era(conn: sqlite3.Connection) -> None:
    dom.modifica_tag(conn, "palestra", attivo=False)
    tag = dom.modifica_tag(conn, "palestra", attivo=True)

    assert tag.attivo is True
    assert [t.slug for t in dom.elenco_tag(conn, solo_attivi=True)][1] == "palestra"


def test_ricrearne_uno_archiviato_lo_riprende_invece_di_duplicarlo(
    conn: sqlite3.Connection,
) -> None:
    """`palestra` e `palestra_2` spaccherebbero in due gli eventi già taggati.

    E riprenderlo lo restituisce a tutti i suoi impegni nello stesso istante:
    non l'avevano mai perso.
    """
    evento_id = _evento(conn, tipo="palestra")
    dom.modifica_tag(conn, "palestra", attivo=False)

    tag = dom.crea_tag(conn, nome="Palestra", descrizione="allenamento e corsa.", ora=ORA)

    assert tag.slug == "palestra"
    assert tag.attivo is True
    assert tag.descrizione == "allenamento e corsa."
    assert len([t for t in dom.elenco_tag(conn) if t.slug.startswith("palestra")]) == 1
    assert dom.per_id(conn, evento_id).tipo == "palestra"


def test_altro_non_si_archivia(conn: sqlite3.Connection) -> None:
    """Ogni evento appena sincronizzato ci finisce dentro: senza, non ha casa."""
    with pytest.raises(dom.TagDiSistema, match="archiviare"):
        dom.modifica_tag(conn, dom.SLUG_ALTRO, attivo=False)


# — cancellarne uno —


def test_un_tipo_che_nessuno_usa_si_cancella(conn: sqlite3.Connection) -> None:
    """Il caso che serve: l'hai appena creato e ti sei accorto che non ti serve."""
    dom.crea_tag(conn, nome="Spesa", descrizione="il supermercato.", ora=ORA)
    dom.elimina_tag(conn, "spesa")

    with pytest.raises(dom.TagInesistente):
        dom.tag_per_slug(conn, "spesa")


def test_un_tipo_in_uso_non_si_cancella_e_l_errore_dice_quanti(
    conn: sqlite3.Connection,
) -> None:
    """Un no senza un numero è un vicolo cieco: col numero è una scelta."""
    _evento(conn, id_esterno="ev1", tipo="lezione")
    _evento(conn, id_esterno="ev2", tipo="lezione")

    with pytest.raises(dom.TagInUso) as guasto:
        dom.elimina_tag(conn, "lezione")

    assert guasto.value.eventi == 2
    assert guasto.value.slug == "lezione"
    assert dom.tag_per_slug(conn, "lezione").attivo is True


def test_un_tipo_in_uso_da_un_evento_passato_conta_lo_stesso(conn: sqlite3.Connection) -> None:
    """Il conteggio guarda tutto l'archivio, non da oggi in poi.

    Al contrario dei contatori della pagina: lì il numero è una cosa da fare, e
    un impegno di marzo non lo è. Qui è ciò che si perderebbe cancellando, e un
    impegno di marzo si perde come uno di domani.
    """
    conn.execute(
        "INSERT INTO calendar_events (fonte, id_esterno, titolo, inizio, fine, tipo,"
        " sincronizzato_il) VALUES ('google', 'vecchio', 'Palestra',"
        " '2026-03-02T18:00:00', '2026-03-02T19:00:00', 'palestra', '2026-03-02T08:00:00')"
    )
    with pytest.raises(dom.TagInUso) as guasto:
        dom.elimina_tag(conn, "palestra")
    assert guasto.value.eventi == 1


def test_altro_non_si_cancella_nemmeno_da_vuoto(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.TagDiSistema, match="cancellare"):
        dom.elimina_tag(conn, dom.SLUG_ALTRO)


def test_su_un_tipo_che_non_esiste_si_solleva(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.TagInesistente):
        dom.elimina_tag(conn, "inventato")
    with pytest.raises(dom.TagInesistente):
        dom.modifica_tag(conn, "inventato", nome="X")


# — scrivere un tag su un evento —


def test_applica_tag_rifiuta_uno_slug_che_non_esiste(conn: sqlite3.Connection) -> None:
    """Il caso vero: hai cancellato un tipo mentre il modello rispondeva.

    Senza questo controllo arriverebbe una `IntegrityError` di SQLite, che il
    worker non saprebbe raccontare — e che nel mezzo di un ciclo di scritture
    lascerebbe metà coda taggata e metà no senza dirlo a nessuno.
    """
    evento_id = _evento(conn, tipo=dom.SLUG_ALTRO)
    gruppo = dom.GruppoDaTaggare(fonte="google", serie_id="", evento_id=evento_id, titolo="X")

    with pytest.raises(dom.TagInesistente):
        dom.applica_tag(conn, gruppo, "inventato", ORA)


def test_correggi_tag_rifiuta_uno_slug_che_non_esiste(conn: sqlite3.Connection) -> None:
    evento_id = _evento(conn)
    with pytest.raises(dom.TagInesistente):
        dom.correggi_tag(conn, evento_id, "inventato", ORA)


def test_un_evento_puo_ricevere_un_tipo_creato_da_te(conn: sqlite3.Connection) -> None:
    """Il giro completo: creo un tipo mio e ce lo metto sopra."""
    evento_id = _evento(conn, serie="serie-sp")
    dom.crea_tag(conn, nome="Spesa", descrizione="il supermercato.", ora=ORA)

    assert dom.correggi_tag(conn, evento_id, "spesa", ORA) == 1

    evento = dom.per_id(conn, evento_id)
    assert evento.tipo == "spesa"
    assert evento.tag_confermato_da_te is True


def test_eventi_per_tag_conta_per_slug(conn: sqlite3.Connection) -> None:
    _evento(conn, id_esterno="ev1", tipo="lezione")
    _evento(conn, id_esterno="ev2", tipo="lezione")
    _evento(conn, id_esterno="ev3", tipo="palestra")

    assert dom.eventi_per_tag(conn) == {"lezione": 2, "palestra": 1}
