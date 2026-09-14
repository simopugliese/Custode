"""Archivio degli eventi di calendario (§8.10): cosa entra, cosa resta, cosa sparisce.

Gli eventi in ingresso sono `custode_calendario.Evento` **veri**, non un finto
scritto per l'occasione: la promessa del modulo è che quel tipo soddisfa il
Protocol `EventoEsterno` senza che `core` lo importi, e un finto costruito qui
sarebbe compatibile per costruzione — proverebbe se stesso.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

import pytest

from custode_calendario.evento import Evento as EventoSorgente
from custode_core.dominio import calendario as dom

ORA = datetime(2026, 8, 31, 8, 41)
OGGI = ORA.date()
DA = OGGI - timedelta(days=7)
A = OGGI + timedelta(days=14)


def _evento(
    identificativo: str = "ev-1",
    titolo: str = "Analisi II",
    inizio: datetime | None = None,
    durata_ore: int = 2,
    **extra: object,
) -> EventoSorgente:
    partenza = inizio if inizio is not None else datetime.combine(OGGI, time(9, 0))
    return EventoSorgente(
        id=identificativo,
        titolo=titolo,
        inizio=partenza,
        fine=partenza + timedelta(hours=durata_ore),
        **extra,  # type: ignore[arg-type]
    )


def _sincronizza(
    conn: sqlite3.Connection,
    eventi: list[EventoSorgente],
    *,
    da: date = DA,
    a: date = A,
    ora: datetime = ORA,
    fonte: str = dom.FONTE_GOOGLE,
) -> dom.Esito:
    return dom.sincronizza(conn, eventi, da=da, a=a, ora=ora, fonte=fonte)


# — cosa entra —————————————————————————————————————————


def test_un_evento_letto_finisce_in_archivio_com_era(conn: sqlite3.Connection) -> None:
    esito = _sincronizza(
        conn, [_evento(luogo="Aula 3", serie_id="serie-lezioni", tutto_il_giorno=False)]
    )
    assert esito == dom.Esito(nuovi=1)

    (salvato,) = dom.del_giorno(conn, OGGI)
    assert salvato.id_esterno == "ev-1"
    assert salvato.titolo == "Analisi II"
    assert salvato.inizio == datetime.combine(OGGI, time(9, 0))
    assert salvato.fine == datetime.combine(OGGI, time(11, 0))
    assert salvato.luogo == "Aula 3"
    assert salvato.serie_id == "serie-lezioni"
    assert salvato.fonte == dom.FONTE_GOOGLE
    assert salvato.sincronizzato_il == ORA


def test_un_evento_nasce_sempre_senza_tag(conn: sqlite3.Connection) -> None:
    # Il tagging è il pezzo dopo: qui nessuno indovina che «Analisi II» è una
    # lezione, e fingere di saperlo produrrebbe tag sbagliati da correggere.
    _sincronizza(conn, [_evento()])
    (salvato,) = dom.del_giorno(conn, OGGI)
    assert salvato.tipo is dom.Tipo.ALTRO


def test_risincronizzare_lo_stesso_evento_non_lo_accoda(conn: sqlite3.Connection) -> None:
    _sincronizza(conn, [_evento()])
    esito = _sincronizza(conn, [_evento()])

    assert esito == dom.Esito(invariati=1)
    assert len(dom.del_giorno(conn, OGGI)) == 1


def test_lo_stesso_evento_due_volte_nella_stessa_risposta_si_conta_una_volta(
    conn: sqlite3.Connection,
) -> None:
    esito = _sincronizza(conn, [_evento(), _evento()])
    assert esito == dom.Esito(nuovi=1)
    assert len(dom.del_giorno(conn, OGGI)) == 1


def test_un_evento_di_giornata_non_risulta_cambiato_ad_ogni_giro(
    conn: sqlite3.Connection,
) -> None:
    # La fine di un evento di giornata arriva con i microsecondi (`time.max`),
    # e in tabella ci va al secondo. Se il confronto «è cambiato?» guardasse i
    # datetime invece delle due stringhe ISO, ogni evento di giornata
    # risulterebbe «aggiornato» ad ogni sincronizzazione, per sempre.
    giornata = EventoSorgente(
        id="ev-giornata",
        titolo="Ferie",
        inizio=datetime.combine(OGGI, time.min),
        fine=datetime.combine(OGGI, time.max),
        tutto_il_giorno=True,
    )
    _sincronizza(conn, [giornata])
    assert _sincronizza(conn, [giornata]) == dom.Esito(invariati=1)


def test_due_fonti_diverse_possono_usare_lo_stesso_identificativo(
    conn: sqlite3.Connection,
) -> None:
    # È la ragione per cui la chiave naturale è (fonte, id_esterno): il feed
    # iCal dell'università non deve sovrascrivere un evento di Google.
    _sincronizza(conn, [_evento(titolo="da Google")])
    _sincronizza(conn, [_evento(titolo="da iCal")], fonte="ical")

    titoli = sorted(e.titolo for e in dom.del_giorno(conn, OGGI))
    assert titoli == ["da Google", "da iCal"]
    assert [e.titolo for e in dom.del_giorno(conn, OGGI, fonte="ical")] == ["da iCal"]


# — cosa cambia ————————————————————————————————————————


def test_un_evento_spostato_si_aggiorna_sul_posto(conn: sqlite3.Connection) -> None:
    _sincronizza(conn, [_evento()])
    (prima,) = dom.del_giorno(conn, OGGI)

    nuovo_orario = datetime.combine(OGGI, time(14, 0))
    esito = _sincronizza(conn, [_evento(inizio=nuovo_orario, luogo="Aula 7")])

    (dopo,) = dom.del_giorno(conn, OGGI)
    assert esito == dom.Esito(aggiornati=1)
    assert dopo.id == prima.id  # stessa riga, non una nuova
    assert dopo.inizio == nuovo_orario
    assert dopo.luogo == "Aula 7"


def test_il_tag_corretto_a_mano_sopravvive_alla_sincronizzazione(
    conn: sqlite3.Connection,
) -> None:
    # È l'unica colonna che non viene dalla sorgente. Se il sync la riscrivesse
    # col default, ogni quarto d'ora cancellerebbe il tipo deciso una volta —
    # e il pezzo del tagging non avrebbe dove appoggiarsi.
    _sincronizza(conn, [_evento()])
    conn.execute("UPDATE calendar_events SET tipo = 'lezione'")

    _sincronizza(conn, [_evento(titolo="Analisi II (spostata)")])

    (salvato,) = dom.del_giorno(conn, OGGI)
    assert salvato.titolo == "Analisi II (spostata)"
    assert salvato.tipo is dom.Tipo.LEZIONE


def test_un_evento_immobile_aggiorna_comunque_quando_e_stato_visto(
    conn: sqlite3.Connection,
) -> None:
    # «Visto adesso» non è «cambiato adesso»: è ciò che distingue un evento
    # fermo da uno che la sorgente ha smesso di nominare.
    _sincronizza(conn, [_evento()])
    dopo = ORA + timedelta(minutes=15)
    _sincronizza(conn, [_evento()], ora=dopo)

    (salvato,) = dom.del_giorno(conn, OGGI)
    assert salvato.sincronizzato_il == dopo


# — cosa sparisce ——————————————————————————————————————


def test_un_evento_disdetto_dentro_la_finestra_esce_dall_archivio(
    conn: sqlite3.Connection,
) -> None:
    _sincronizza(conn, [_evento("ev-1"), _evento("ev-2", titolo="Palestra")])

    esito = _sincronizza(conn, [_evento("ev-1")])

    assert esito == dom.Esito(invariati=1, rimossi=1)
    assert [e.id_esterno for e in dom.del_giorno(conn, OGGI)] == ["ev-1"]


def test_un_evento_fuori_dalla_finestra_non_si_tocca(conn: sqlite3.Connection) -> None:
    # È la differenza fra archivio e cache: la sorgente non è stata interrogata
    # su marzo, quindi il suo silenzio su marzo non vuol dire niente. §8.10
    # vuole lo storico del calendario per cercarci i pattern.
    vecchio = datetime.combine(OGGI - timedelta(days=90), time(9, 0))
    _sincronizza(
        conn,
        [_evento("ev-vecchio", inizio=vecchio)],
        da=vecchio.date(),
        a=vecchio.date(),
    )

    esito = _sincronizza(conn, [])  # finestra di oggi: della vecchia non si parla

    assert esito == dom.Esito()
    assert [e.id_esterno for e in dom.del_giorno(conn, vecchio.date())] == ["ev-vecchio"]


def test_un_evento_cominciato_prima_della_finestra_non_si_tocca(
    conn: sqlite3.Connection,
) -> None:
    # Un viaggio partito il giorno prima dell'inizio della finestra la
    # attraversa: se la sorgente non lo restituisce può essere perché non
    # gliel'abbiamo chiesto, non perché è stato disdetto.
    partenza = datetime.combine(DA - timedelta(days=1), time(8, 0))
    _sincronizza(
        conn,
        [_evento("ev-viaggio", inizio=partenza, durata_ore=24 * 10)],
        da=partenza.date(),
        a=A,
    )

    esito = _sincronizza(conn, [])

    assert esito == dom.Esito()
    assert [e.id_esterno for e in dom.del_giorno(conn, DA)] == ["ev-viaggio"]


def test_la_riconciliazione_non_attraversa_le_fonti(conn: sqlite3.Connection) -> None:
    _sincronizza(conn, [_evento("condiviso")], fonte="ical")
    _sincronizza(conn, [_evento("condiviso")])

    esito = _sincronizza(conn, [])  # Google non ha più niente da dire

    assert esito == dom.Esito(rimossi=1)
    assert [e.fonte for e in dom.del_giorno(conn, OGGI)] == ["ical"]


# — come si rilegge ————————————————————————————————————


def test_un_evento_lungo_compare_in_tutti_i_giorni_che_occupa(
    conn: sqlite3.Connection,
) -> None:
    # Un viaggio che parte venerdì e finisce domenica è un impegno anche di
    # sabato: un filtro sul solo `inizio` lo farebbe sparire dal sabato.
    partenza = datetime.combine(OGGI, time(8, 0))
    _sincronizza(conn, [_evento("ev-viaggio", titolo="Roma", inizio=partenza, durata_ore=48)])

    for scarto in (0, 1, 2):
        giorno = OGGI + timedelta(days=scarto)
        assert [e.titolo for e in dom.del_giorno(conn, giorno)] == ["Roma"], giorno
    assert dom.del_giorno(conn, OGGI + timedelta(days=3)) == []
    assert dom.del_giorno(conn, OGGI - timedelta(days=1)) == []


def test_gli_eventi_del_giorno_arrivano_in_ordine_di_orario(conn: sqlite3.Connection) -> None:
    orari = [time(18, 0), time(9, 0), time(13, 30)]
    _sincronizza(
        conn,
        [
            _evento(f"ev-{i}", titolo=quando.isoformat(), inizio=datetime.combine(OGGI, quando))
            for i, quando in enumerate(orari)
        ],
    )
    assert [e.titolo for e in dom.del_giorno(conn, OGGI)] == ["09:00:00", "13:30:00", "18:00:00"]


def test_un_intervallo_rovesciato_e_un_errore_subito(conn: sqlite3.Connection) -> None:
    # Meglio un errore che una finestra vuota: `da > a` in una sincronizzazione
    # significherebbe «non cancellare niente», cioè un guasto silenzioso.
    with pytest.raises(ValueError, match="rovesciato"):
        dom.fra(conn, OGGI, OGGI - timedelta(days=1))
    with pytest.raises(ValueError, match="rovesciato"):
        _sincronizza(conn, [], da=OGGI, a=OGGI - timedelta(days=1))


# — il tag (§8.10, pezzo 5) —————————————————————————————


def test_un_evento_nuovo_non_ha_ancora_un_tag_proposto(conn: sqlite3.Connection) -> None:
    _sincronizza(conn, [_evento()])
    (salvato,) = dom.del_giorno(conn, OGGI)
    assert salvato.tag_proposto_il is None
    assert salvato.tag_confermato_da_te is False


def test_una_nuova_occorrenza_di_una_serie_taggata_eredita_il_tag(
    conn: sqlite3.Connection,
) -> None:
    # È il duplicato da evitare: senza eredità, ogni settimana la lezione
    # rinascerebbe 'altro' e il job di tagging la riproporrebbe da capo.
    _sincronizza(conn, [_evento("ev-1", serie_id="serie-analisi")])
    (prima,) = dom.del_giorno(conn, OGGI)
    dom.applica_tag(
        conn,
        dom.GruppoDaTaggare(
            fonte=dom.FONTE_GOOGLE, serie_id="serie-analisi", evento_id=None, titolo=""
        ),
        dom.Tipo.LEZIONE,
        ORA,
    )

    domani = OGGI + timedelta(days=1)
    _sincronizza(
        conn,
        [_evento("ev-2", serie_id="serie-analisi", inizio=datetime.combine(domani, time(9, 0)))],
        da=DA,
        a=domani,
    )

    (seconda,) = dom.del_giorno(conn, domani)
    assert seconda.tipo is dom.Tipo.LEZIONE
    assert seconda.tag_proposto_il == ORA
    assert seconda.id != prima.id  # occorrenza diversa, non la stessa riga


def test_una_nuova_occorrenza_di_una_serie_non_ancora_taggata_resta_senza_tag(
    conn: sqlite3.Connection,
) -> None:
    _sincronizza(conn, [_evento("ev-1", serie_id="serie-analisi")])

    domani = OGGI + timedelta(days=1)
    _sincronizza(
        conn,
        [_evento("ev-2", serie_id="serie-analisi", inizio=datetime.combine(domani, time(9, 0)))],
        da=DA,
        a=domani,
    )

    (seconda,) = dom.del_giorno(conn, domani)
    assert seconda.tag_proposto_il is None


def test_un_evento_singolo_non_eredita_niente(conn: sqlite3.Connection) -> None:
    # Senza serie non c'è niente da cui ereditare: ogni evento singolo è un
    # gruppo di una riga sola, anche se per caso condivide il titolo con un
    # altro già taggato.
    _sincronizza(conn, [_evento("ev-1", titolo="Ricevimento")])
    dom.applica_tag(
        conn,
        dom.GruppoDaTaggare(fonte=dom.FONTE_GOOGLE, serie_id="", evento_id=1, titolo=""),
        dom.Tipo.ALTRO,
        ORA,
    )

    _sincronizza(conn, [_evento("ev-2", titolo="Ricevimento")])

    (nuovo,) = [e for e in dom.del_giorno(conn, OGGI) if e.id_esterno == "ev-2"]
    assert nuovo.tag_proposto_il is None


def test_gruppi_senza_tag_conta_una_serie_una_volta_sola(conn: sqlite3.Connection) -> None:
    domani = OGGI + timedelta(days=1)
    _sincronizza(
        conn,
        [
            _evento("ev-1", serie_id="serie-analisi"),
            _evento("ev-2", serie_id="serie-analisi", inizio=datetime.combine(domani, time(9, 0))),
            _evento("ev-3", titolo="Ricevimento", serie_id=""),
        ],
    )

    gruppi = dom.gruppi_senza_tag(conn)

    # La lunghezza conta quanto le chiavi: due gruppi, non tre — se le due
    # occorrenze della serie finissero due volte in lista, un confronto per
    # insieme di chiavi non se ne accorgerebbe, essendo la stessa chiave.
    assert len(gruppi) == 2
    chiavi = {(g.serie_id, g.evento_id) for g in gruppi}
    assert chiavi == {("serie-analisi", None), ("", 3)}


def test_gruppi_senza_tag_non_ripropone_una_serie_gia_taggata(conn: sqlite3.Connection) -> None:
    _sincronizza(conn, [_evento("ev-1", serie_id="serie-analisi")])
    dom.applica_tag(
        conn,
        dom.GruppoDaTaggare(
            fonte=dom.FONTE_GOOGLE, serie_id="serie-analisi", evento_id=None, titolo=""
        ),
        dom.Tipo.LEZIONE,
        ORA,
    )
    assert dom.gruppi_senza_tag(conn) == []


def test_applica_tag_scrive_tutta_la_serie_insieme(conn: sqlite3.Connection) -> None:
    domani = OGGI + timedelta(days=1)
    _sincronizza(
        conn,
        [
            _evento("ev-1", serie_id="serie-analisi"),
            _evento("ev-2", serie_id="serie-analisi", inizio=datetime.combine(domani, time(9, 0))),
        ],
    )

    toccate = dom.applica_tag(
        conn,
        dom.GruppoDaTaggare(
            fonte=dom.FONTE_GOOGLE, serie_id="serie-analisi", evento_id=None, titolo=""
        ),
        dom.Tipo.LEZIONE,
        ORA,
    )

    assert toccate == 2
    for evento in [*dom.del_giorno(conn, OGGI), *dom.del_giorno(conn, domani)]:
        assert evento.tipo is dom.Tipo.LEZIONE
        assert evento.tag_confermato_da_te is False


def test_applica_tag_su_un_evento_singolo_tocca_solo_quella_riga(conn: sqlite3.Connection) -> None:
    _sincronizza(conn, [_evento("ev-1", titolo="Ricevimento"), _evento("ev-2", titolo="Palestra")])
    ((riga_1,), (riga_2,)) = (
        [e for e in dom.del_giorno(conn, OGGI) if e.id_esterno == "ev-1"],
        [e for e in dom.del_giorno(conn, OGGI) if e.id_esterno == "ev-2"],
    )

    toccate = dom.applica_tag(
        conn,
        dom.GruppoDaTaggare(fonte=dom.FONTE_GOOGLE, serie_id="", evento_id=riga_1.id, titolo=""),
        dom.Tipo.ALTRO,
        ORA,
    )

    assert toccate == 1
    del_giorno = {e.id: e for e in dom.del_giorno(conn, OGGI)}
    assert del_giorno[riga_1.id].tag_proposto_il is not None
    assert del_giorno[riga_2.id].tag_proposto_il is None


def test_correggi_tag_segna_la_conferma_e_tocca_tutta_la_serie(conn: sqlite3.Connection) -> None:
    domani = OGGI + timedelta(days=1)
    _sincronizza(
        conn,
        [
            _evento("ev-1", serie_id="serie-analisi"),
            _evento("ev-2", serie_id="serie-analisi", inizio=datetime.combine(domani, time(9, 0))),
        ],
    )
    (proposta,) = dom.del_giorno(conn, OGGI)
    dom.applica_tag(
        conn,
        dom.GruppoDaTaggare(
            fonte=dom.FONTE_GOOGLE, serie_id="serie-analisi", evento_id=None, titolo=""
        ),
        dom.Tipo.PALESTRA,
        ORA,
    )

    dom.correggi_tag(conn, proposta.id, dom.Tipo.LEZIONE, ORA)

    for evento in [*dom.del_giorno(conn, OGGI), *dom.del_giorno(conn, domani)]:
        assert evento.tipo is dom.Tipo.LEZIONE
        assert evento.tag_confermato_da_te is True


def test_correggi_tag_su_id_inesistente_solleva(conn: sqlite3.Connection) -> None:
    with pytest.raises(dom.EventoInesistente):
        dom.correggi_tag(conn, 999, dom.Tipo.LEZIONE, ORA)
