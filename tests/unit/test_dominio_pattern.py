"""I pattern da cui nasce una proposta di regola (§8.10).

Tutto quello che conta qui dentro è **puro**: si costruiscono otto settimane di
storico a mano e si guarda cosa ne esce, invece di aspettare otto settimane.

Le cose che si sbagliano sono tre, e i test ci stanno addosso una per una: la
**specificità** di un aggancio (se segni la creatina tutti i giorni, la palestra
non c'entra niente), la **mezzanotte** nel grappolo degli orari, e la
distinzione fra «tutti i giorni» e «nessun giorno», che scritta male propone un
promemoria quotidiano proprio alle abitudini che non hanno nessun ritmo.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from custode_core.dominio import pattern as dom
from custode_core.dominio import regole as dom_regole

# Un lunedì, per contare le settimane senza doverci pensare.
DA = date(2026, 7, 20)
A = date(2026, 9, 13)  # otto settimane esatte, fino a una domenica


def _giorni(*isoweekday: int, da: date = DA, a: date = A) -> list[date]:
    """Tutte le date della finestra che cadono in quei giorni della settimana."""
    return [g for g in dom.giorni_fra(da, a) if g.isoweekday() in isoweekday]


def _segnate(giorni: list[date], *, abitudine: str, ora: time = time(21, 0)) -> list[dom.Segnata]:
    return [
        dom.Segnata(abitudine=abitudine, giorno=g, scritto_il=datetime.combine(g, ora))
        for g in giorni
    ]


def _impegni(giorni: list[date], *, tipo: str) -> list[dom.Impegno]:
    return [dom.Impegno(giorno=g, tipo=tipo) for g in giorni]


# — «la creatina quando vai in palestra»: l'esempio di §8.10 —


def test_la_creatina_quando_vai_in_palestra() -> None:
    """L'esempio che §8.10 fa per esteso, dall'inizio alla fine."""
    palestra = _giorni(2, 4)  # martedì e giovedì, 16 volte in otto settimane
    trovati = dom.cerca(
        segnate=_segnate(palestra, abitudine="Creatina"),
        impegni=_impegni(palestra, tipo="palestra"),
        da=DA,
        a=A,
    )

    assert len(trovati) == 1
    candidato = trovati[0]
    assert candidato.genere is dom.Genere.SU_IMPEGNO
    assert candidato.soggetto == "Creatina"
    assert candidato.tipo_evento == "palestra"
    assert candidato.occasioni == len(palestra)
    assert candidato.coperte == len(palestra)
    assert candidato.altrove == 0


def test_una_volta_saltata_su_otto_regge_ancora() -> None:
    palestra = _giorni(2, 4)
    trovati = dom.cerca(
        segnate=_segnate(palestra[:-2], abitudine="Creatina"),
        impegni=_impegni(palestra, tipo="palestra"),
        da=DA,
        a=A,
    )

    assert [c.genere for c in trovati] == [dom.Genere.SU_IMPEGNO]
    assert trovati[0].coperte == len(palestra) - 2


def test_meta_delle_volte_non_e_un_pattern() -> None:
    """Un promemoria che sbaglia una volta su due è un promemoria che si mette in pausa."""
    palestra = _giorni(2, 4)
    trovati = dom.cerca(
        segnate=_segnate(palestra[::2], abitudine="Creatina"),
        impegni=_impegni(palestra, tipo="palestra"),
        da=DA,
        a=A,
    )

    assert [c.genere for c in trovati] != [dom.Genere.SU_IMPEGNO]


def test_se_la_segni_tutti_i_giorni_la_palestra_non_c_entra_niente() -> None:
    """Il controllo che distingue un aggancio vero da una coincidenza.

    La copertura sulle giornate con palestra è del 100% comunque — ma una regola
    agganciata alla palestra tacerebbe negli altri cinque giorni, in cui quella
    cosa la fai lo stesso. È il caso che tocca al pattern a orario.
    """
    tutti = dom.giorni_fra(DA, A)
    trovati = dom.cerca(
        segnate=_segnate(tutti, abitudine="Creatina"),
        impegni=_impegni(_giorni(2, 4), tipo="palestra"),
        da=DA,
        a=A,
    )

    assert [c.genere for c in trovati] == [dom.Genere.A_ORARIO]


def test_una_cosa_di_tutti_i_giorni_non_si_aggancia_a_un_impegno() -> None:
    """Il caso in cui la **dispersione** è l'unica cosa che ferma il candidato.

    Gli orari sono sparsi apposta, così il pattern a orario non regge e l'unica
    cosa che può uscire è l'aggancio alla palestra: se esce, la soglia non sta
    facendo il suo lavoro. La versione con gli orari regolari di questo stesso
    caso **non** provava niente — lì usciva comunque il candidato a orario, che
    è più forte, e il test passava anche a controllo spento.
    """
    tutti = dom.giorni_fra(DA, A)
    segnate = [
        dom.Segnata(
            abitudine="Creatina",
            giorno=g,
            scritto_il=datetime.combine(g, time((i * 3) % 24, 0)),
        )
        for i, g in enumerate(tutti)
    ]

    trovati = dom.cerca(
        segnate=segnate, impegni=_impegni(_giorni(2, 4), tipo="palestra"), da=DA, a=A
    )

    assert trovati == []


def test_tre_occasioni_sono_una_coincidenza() -> None:
    poche = _giorni(2)[:3]
    trovati = dom.cerca(
        segnate=_segnate(poche, abitudine="Creatina"),
        impegni=_impegni(poche, tipo="palestra"),
        da=DA,
        a=A,
    )

    assert trovati == []


def test_gli_impegni_di_un_tipo_solo_non_si_mescolano() -> None:
    """Due tipi diversi nella stessa finestra: l'aggancio va su quello giusto."""
    palestra = _giorni(2, 4)
    lezione = _giorni(1, 3, 5)
    trovati = dom.cerca(
        segnate=_segnate(palestra, abitudine="Creatina"),
        impegni=_impegni(palestra, tipo="palestra") + _impegni(lezione, tipo="lezione"),
        da=DA,
        a=A,
    )

    assert [c.tipo_evento for c in trovati] == ["palestra"]


# — «la creatina verso le 19»: l'ora la dicono gli orari in cui scrivi —


def test_una_cosa_di_tutti_i_giorni_alla_stessa_ora() -> None:
    tutti = dom.giorni_fra(DA, A)
    trovati = dom.cerca(
        segnate=_segnate(tutti, abitudine="Creatina", ora=time(19, 10)),
        impegni=[],
        da=DA,
        a=A,
    )

    assert len(trovati) == 1
    candidato = trovati[0]
    assert candidato.genere is dom.Genere.A_ORARIO
    assert candidato.giorni == dom_regole.TUTTI_I_GIORNI
    # Arrotondata indietro alla mezz'ora: il promemoria deve arrivare prima del
    # momento in cui di solito scrivi di averlo già fatto.
    assert candidato.ora == "19:00"


def test_i_giorni_in_cui_la_fai_davvero_finiscono_nella_regola() -> None:
    """Non «tutti i giorni»: lunedì, mercoledì e venerdì, che è quando succede."""
    suoi = _giorni(1, 3, 5)
    trovati = dom.cerca(
        segnate=_segnate(suoi, abitudine="Corsa", ora=time(7, 20)),
        impegni=[],
        da=DA,
        a=A,
    )

    assert [c.giorni for c in trovati] == [(1, 3, 5)]
    assert trovati[0].ora == "07:00"


def test_senza_nessun_ritmo_non_si_propone_niente() -> None:
    """Il caso che `None` e `()` confusi trasformerebbero in un promemoria quotidiano.

    Sette log su otto settimane, **uno per ogni giorno della settimana**: nessun
    giorno regge (uno su otto, contro una soglia di tre su quattro), quindi non
    c'è nessuna regola da proporre. Con i due casi confusi uscirebbe «tutti i
    giorni», cioè 56 promemoria per 7 occasioni vere.

    Il passo è di otto giorni e non di sette **apposta**: sette, partendo da un
    lunedì, darebbe otto lunedì di fila — cioè il ritmo settimanale più regolare
    che esista, che è l'opposto di quello che questo test vuole dire.
    """
    sparsi = dom.giorni_fra(DA, A)[::8]
    trovati = dom.cerca(
        segnate=_segnate(sparsi, abitudine="Lettura", ora=time(22, 0)),
        impegni=[],
        da=DA,
        a=A,
    )

    assert trovati == []


def test_un_orario_sparso_non_e_un_orario() -> None:
    """La fai sempre, ma quando capita: proporre un'ora sarebbe inventarla."""
    tutti = dom.giorni_fra(DA, A)
    segnate = [
        dom.Segnata(
            abitudine="Lettura",
            giorno=g,
            # Sparpagliate su tutta la giornata, un'ora diversa per ogni giorno.
            scritto_il=datetime.combine(g, time((i * 3) % 24, 0)),
        )
        for i, g in enumerate(tutti)
    ]
    trovati = dom.cerca(segnate=segnate, impegni=[], da=DA, a=A)

    assert trovati == []


def test_il_grappolo_scavalca_la_mezzanotte() -> None:
    """La media fra le 23:50 e le 00:10 è mezzogiorno, che è quando non succede mai.

    Il centro si prende fra gli orari veri e la distanza gira in tondo, quindi
    un'abitudine della notte resta un'abitudine della notte.
    """
    tutti = dom.giorni_fra(DA, A)
    segnate = [
        dom.Segnata(
            abitudine="Sveglia",
            giorno=g,
            scritto_il=datetime.combine(g, time(23, 50))
            if i % 2
            else datetime.combine(g, time(0, 10)),
        )
        for i, g in enumerate(tutti)
    ]
    trovati = dom.cerca(segnate=segnate, impegni=[], da=DA, a=A)

    assert len(trovati) == 1
    # Una delle due punte, non mezzogiorno.
    assert trovati[0].ora in ("23:30", "00:00")


def test_i_log_scritti_il_giorno_dopo_non_dicono_l_ora() -> None:
    """Segnare stamattina la corsa di ieri è una cosa che capita, e il suo orario
    parla di quando te ne sei ricordato."""
    tutti = dom.giorni_fra(DA, A)
    recuperati = [
        dom.Segnata(
            abitudine="Corsa",
            giorno=g,
            scritto_il=datetime.combine(g + timedelta(days=1), time(9, 0)),
        )
        for g in tutti
    ]

    assert dom.cerca(segnate=recuperati, impegni=[], da=DA, a=A) == []


# — una sola proposta per abitudine —


def test_una_sola_proposta_per_abitudine() -> None:
    """Due modi di chiedere lo stesso promemoria non sono due proposte.

    Qui la creatina regge sia sull'aggancio alla palestra sia sull'orario: esce
    il più forte dei due, non tutti e due.
    """
    palestra = _giorni(2, 4)
    trovati = dom.cerca(
        segnate=_segnate(palestra, abitudine="Creatina", ora=time(19, 5)),
        impegni=_impegni(palestra, tipo="palestra"),
        da=DA,
        a=A,
    )

    assert len(trovati) == 1
    assert trovati[0].soggetto == "Creatina"


def test_due_abitudini_danno_due_candidati_in_ordine_di_forza() -> None:
    palestra = _giorni(2, 4)
    lezione = _giorni(1, 3)
    trovati = dom.cerca(
        segnate=(
            _segnate(palestra, abitudine="Creatina")
            # Il portatile lo dimentica due volte: stessa forma, forza minore.
            + _segnate(lezione[:-2], abitudine="Portatile")
        ),
        impegni=_impegni(palestra, tipo="palestra") + _impegni(lezione, tipo="lezione"),
        da=DA,
        a=A,
    )

    assert [c.soggetto for c in trovati] == ["Creatina", "Portatile"]
    assert trovati[0].forza > trovati[1].forza


# — l'abbozzo con cui si controllano i doppioni prima di chiamare —


def test_l_abbozzo_di_un_candidato_riconosce_la_stessa_regola_gia_scartata() -> None:
    """È il controllo che risparmia la chiamata: si fa sul nome dell'abitudine,
    che è quanto basta a riconoscere una cosa già vista."""
    palestra = _giorni(2, 4)
    candidato = dom.cerca(
        segnate=_segnate(palestra, abitudine="Creatina"),
        impegni=_impegni(palestra, tipo="palestra"),
        da=DA,
        a=A,
    )[0]

    gia_scartata = dom_regole.Abbozzo(
        trigger=dom_regole.Trigger.PRIMA_EVENTO,
        testo="prendi la creatina",
        tipo_evento="palestra",
    )

    assert dom_regole.stessa_proposta(candidato.abbozzo(), gia_scartata)


# — la lettura dall'archivio —


def test_la_finestra_finisce_ieri() -> None:
    """La giornata in corso è incompleta per costruzione: a mezzanotte e mezza,
    quando il job gira, non hai ancora segnato niente."""
    da, a = dom.finestra(date(2026, 9, 14), settimane=8)

    assert a == date(2026, 9, 13)
    assert (a - da).days + 1 == 8 * 7


def test_gli_eventi_di_giornata_e_il_tipo_altro_restano_fuori(conn: sqlite3.Connection) -> None:
    """Una regola agganciata a un tipo che compare solo come evento di giornata
    non scatterebbe mai: `dovute()` li lascia fuori."""
    conn.execute(
        "INSERT INTO calendar_tags (slug, nome, descrizione, creato_il)"
        " VALUES ('viaggio2', 'Viaggio lungo', 'giorni interi.', '2026-07-01T08:00:00')"
    )
    conn.executemany(
        "INSERT INTO calendar_events (fonte, id_esterno, titolo, inizio, fine,"
        " tutto_il_giorno, luogo, serie_id, tipo, sincronizzato_il)"
        " VALUES ('google', ?, ?, ?, ?, ?, '', '', ?, '2026-09-14T08:00:00')",
        [
            # Di giornata: fuori.
            ("g1", "Ferie", "2026-08-03T00:00:00", "2026-08-03T23:59:59", 1, "viaggio2"),
            # Tipo `altro`, il ripiego di chi non è ancora stato taggato: fuori.
            ("g2", "Boh", "2026-08-04T10:00:00", "2026-08-04T11:00:00", 0, "altro"),
            # Questo resta.
            ("g3", "Palestra", "2026-08-05T18:00:00", "2026-08-05T19:00:00", 0, "palestra"),
        ],
    )

    letti = dom._impegni(conn, da=DA, a=A)

    assert [i.tipo for i in letti] == ["palestra"]


def test_i_tipi_archiviati_restano_fuori(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE calendar_tags SET attivo = 0 WHERE slug = 'palestra'")
    conn.execute(
        "INSERT INTO calendar_events (fonte, id_esterno, titolo, inizio, fine,"
        " tutto_il_giorno, luogo, serie_id, tipo, sincronizzato_il)"
        " VALUES ('google', 'g1', 'Palestra', '2026-08-05T18:00:00', '2026-08-05T19:00:00',"
        " 0, '', '', 'palestra', '2026-09-14T08:00:00')"
    )

    assert dom._impegni(conn, da=DA, a=A) == []


def test_le_abitudini_disattivate_restano_fuori(conn: sqlite3.Connection) -> None:
    """Una che hai disattivato è una cosa che hai smesso di fare: proporre un
    promemoria per rimetterla in piedi risponderebbe a una domanda non fatta."""
    conn.execute(
        "INSERT INTO habits (nome, frequenza_target_settimanale, attivo, creato_il)"
        " VALUES ('Creatina', 7, 0, '2026-07-01T08:00:00')"
    )
    conn.execute(
        "INSERT INTO habit_logs (habit_id, data, fatto, creato_il)"
        " VALUES (1, '2026-08-05', 1, '2026-08-05T19:00:00')"
    )

    assert dom._segnate(conn, da=DA, a=A) == []
