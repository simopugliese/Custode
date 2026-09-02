"""Backup e ripristino del database (§9).

Due cose distinte, e la seconda è quella che conta: un backup che non si
riapre non è un backup. Ogni prova qui fa il giro completo — scrivi, poi
rileggi e verifica che il database ripristinato contenga davvero i dati.

La retention ha i suoi test a parte come funzione pura: è l'unica parte del
sistema che, sbagliata, **cancella** invece di non fare.
"""

from __future__ import annotations

import gzip
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from custode_core.db import connect
from custode_core.migrazioni import migra
from custode_worker import backup

OGGI = date(2026, 9, 6)


@pytest.fixture
def db_pieno(tmp_path: Path) -> Path:
    """Un database vero, con lo schema migrato e una riga dentro."""
    percorso = tmp_path / "custode.db"
    conn = connect(percorso)
    migra(conn)
    conn.execute("INSERT INTO tasks (titolo, creato_il) VALUES ('Prova', '2026-09-06T10:00:00')")
    conn.close()
    return percorso


@pytest.fixture
def cartella(tmp_path: Path) -> Path:
    return tmp_path / "backup"


def _chiave() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _tocca(cartella: Path, nome: str) -> Path:
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / nome
    percorso.write_bytes(b"x")
    return percorso


# — il giro completo —


def test_backup_e_ripristino_in_chiaro(db_pieno: Path, cartella: Path, ora: datetime) -> None:
    esito = backup.esegui(db_pieno, cartella, ora)

    assert esito.cifrato is False
    assert esito.percorso.name == f"custode-{ora.date().isoformat()}.db.gz"
    assert esito.percorso.exists()

    ripristinato = backup.ripristina(esito.percorso, cartella / "ripristinato.db")

    conn = sqlite3.connect(ripristinato)
    assert conn.execute("SELECT titolo FROM tasks").fetchone()[0] == "Prova"
    conn.close()


def test_backup_e_ripristino_cifrato(db_pieno: Path, cartella: Path, ora: datetime) -> None:
    chiave = _chiave()

    esito = backup.esegui(db_pieno, cartella, ora, chiave=chiave)

    assert esito.cifrato is True
    assert esito.percorso.name.endswith(".db.gz.enc")
    # Cifrato davvero: non è un gzip che chiunque apre.
    with pytest.raises((OSError, EOFError)):
        gzip.decompress(esito.percorso.read_bytes())

    ripristinato = backup.ripristina(esito.percorso, cartella / "r.db", chiave=chiave)
    conn = sqlite3.connect(ripristinato)
    assert conn.execute("SELECT titolo FROM tasks").fetchone()[0] == "Prova"
    conn.close()


def test_la_copia_e_coerente_mentre_gli_altri_scrivono(
    db_pieno: Path, cartella: Path, ora: datetime
) -> None:
    """In WAL le scritture stanno in un file a parte: `cp` non basterebbe."""
    scrivente = connect(db_pieno)
    scrivente.execute("INSERT INTO tasks (titolo, creato_il) VALUES ('Aperta', '2026-09-06T11:00')")

    esito = backup.esegui(db_pieno, cartella, ora)
    scrivente.close()

    ripristinato = backup.ripristina(esito.percorso, cartella / "r.db")
    conn = sqlite3.connect(ripristinato)
    titoli = {r[0] for r in conn.execute("SELECT titolo FROM tasks")}
    conn.close()
    assert "Prova" in titoli  # lo snapshot è utilizzabile e integro


# — cosa va storto —


def test_la_chiave_sbagliata_non_apre(db_pieno: Path, cartella: Path, ora: datetime) -> None:
    esito = backup.esegui(db_pieno, cartella, ora, chiave=_chiave())

    with pytest.raises(backup.BackupNonRiuscito, match="non apre"):
        backup.ripristina(esito.percorso, cartella / "r.db", chiave=_chiave())


def test_un_cifrato_senza_chiave_lo_dice(db_pieno: Path, cartella: Path, ora: datetime) -> None:
    esito = backup.esegui(db_pieno, cartella, ora, chiave=_chiave())

    with pytest.raises(backup.BackupNonRiuscito, match="cifrato"):
        backup.ripristina(esito.percorso, cartella / "r.db")


def test_una_chiave_storta_si_scopre_scrivendo(
    db_pieno: Path, cartella: Path, ora: datetime
) -> None:
    """Meglio nessun backup che uno che credi cifrato e non si riapre."""
    with pytest.raises(backup.BackupNonRiuscito, match="non è una chiave valida"):
        backup.esegui(db_pieno, cartella, ora, chiave="non-una-chiave")


def test_il_ripristino_non_sovrascrive(db_pieno: Path, cartella: Path, ora: datetime) -> None:
    """Un restore che sovrascrive da solo trasforma un problema in due."""
    esito = backup.esegui(db_pieno, cartella, ora)
    esistente = cartella / "gia-qui.db"
    esistente.write_bytes(b"non toccarmi")

    with pytest.raises(backup.BackupNonRiuscito, match="esiste già"):
        backup.ripristina(esito.percorso, esistente)

    assert esistente.read_bytes() == b"non toccarmi"


def test_un_archivio_che_non_e_un_database(cartella: Path) -> None:
    cartella.mkdir(parents=True)
    finto = cartella / "custode-2026-09-06.db.gz"
    finto.write_bytes(gzip.compress(b"questo non e' un database"))

    with pytest.raises(backup.BackupNonRiuscito):
        backup.ripristina(finto, cartella / "r.db")
    # E non lascia in giro il file mezzo scritto.
    assert not (cartella / "r.db").exists()


def test_un_database_che_non_esiste(tmp_path: Path, cartella: Path, ora: datetime) -> None:
    with pytest.raises(backup.BackupNonRiuscito, match="non esiste"):
        backup.esegui(tmp_path / "manca.db", cartella, ora)


# — retention (§9): 7 giornalieri + 4 settimanali —


def test_pochi_backup_si_tengono_tutti() -> None:
    giorni = [OGGI - timedelta(days=n) for n in range(5)]
    assert backup.da_tenere(giorni, OGGI) == set(giorni)


def test_tiene_sette_giornalieri() -> None:
    giorni = [OGGI - timedelta(days=n) for n in range(20)]

    tenuti = backup.da_tenere(giorni, OGGI)

    ultimi_sette = {OGGI - timedelta(days=n) for n in range(7)}
    assert ultimi_sette <= tenuti


def test_oltre_i_sette_giorni_ne_resta_uno_per_settimana() -> None:
    """Dopo un mese: una copia recente al giorno, poi una per settimana."""
    giorni = [OGGI - timedelta(days=n) for n in range(40)]

    tenuti = backup.da_tenere(giorni, OGGI)

    # Non undici file dello stesso periodo: 7 giornalieri + al più 4 settimanali.
    assert len(tenuti) <= backup.GIORNALIERI + backup.SETTIMANALI
    # E i più vecchi se ne vanno.
    assert OGGI - timedelta(days=39) not in tenuti


def test_i_settimanali_coprono_settimane_diverse() -> None:
    giorni = [OGGI - timedelta(days=n) for n in range(40)]

    tenuti = backup.da_tenere(giorni, OGGI)

    from custode_core.formato import inizio_settimana

    settimane = {inizio_settimana(g) for g in tenuti}
    # Almeno quattro settimane distinte rappresentate: è il punto della regola.
    assert len(settimane) >= 4


def test_un_backup_con_data_futura_non_si_cancella() -> None:
    """Un orologio storto non deve costare un file: cancellare è irreparabile."""
    futuro = OGGI + timedelta(days=3)
    giorni = [OGGI - timedelta(days=n) for n in range(20)] + [futuro]

    assert futuro in backup.da_tenere(giorni, OGGI)


# — la pulizia sul disco —


def test_la_pulizia_toglie_i_vecchi_e_lascia_gli_estranei(db_pieno: Path, cartella: Path) -> None:
    for n in range(40):
        giorno = OGGI - timedelta(days=n)
        _tocca(cartella, backup.nome_file(giorno, cifrato=False))
    estraneo = _tocca(cartella, "appunti.txt")

    esito = backup.esegui(db_pieno, cartella, datetime.combine(OGGI, datetime.min.time()))

    assert esito.rimossi  # qualcosa è stato tolto
    assert estraneo.exists()  # ma non ciò che non è nostro
    rimasti = {g for g, _, _ in backup.elenco(cartella)}
    assert len(rimasti) <= backup.GIORNALIERI + backup.SETTIMANALI


def test_cambiare_idea_sulla_chiave_non_lascia_doppioni(
    db_pieno: Path, cartella: Path, ora: datetime
) -> None:
    """Due copie dello stesso giorno che la retention non vede come doppione."""
    in_chiaro = backup.esegui(db_pieno, cartella, ora)
    assert in_chiaro.percorso.exists()

    cifrato = backup.esegui(db_pieno, cartella, ora, chiave=_chiave())

    assert cifrato.percorso.exists()
    assert not in_chiaro.percorso.exists()
    assert len(backup.elenco(cartella)) == 1


def test_un_backup_interrotto_non_prende_il_posto_di_uno_buono(
    db_pieno: Path, cartella: Path, ora: datetime
) -> None:
    buono = backup.esegui(db_pieno, cartella, ora)
    dimensione = buono.percorso.stat().st_size
    _tocca(cartella, buono.percorso.name + ".parziale")

    # Il file `.parziale` non è riconosciuto come backup e non conta.
    assert [g for g, _, _ in backup.elenco(cartella)] == [ora.date()]
    assert buono.percorso.stat().st_size == dimensione


# — lettura dei nomi —


@pytest.mark.parametrize(
    ("nome", "atteso"),
    [
        ("custode-2026-09-06.db.gz", date(2026, 9, 6)),
        ("custode-2026-09-06.db.gz.enc", date(2026, 9, 6)),
        ("custode-non-una-data.db.gz", None),
        ("altro-2026-09-06.db.gz", None),
        ("custode-2026-09-06.db.gz.parziale", None),
        ("appunti.txt", None),
    ],
)
def test_giorno_di(nome: str, atteso: date | None) -> None:
    assert backup.giorno_di(Path(nome)) == atteso
