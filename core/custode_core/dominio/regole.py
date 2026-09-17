"""Le regole di contesto dettate da te (ARCHITECTURE.md §8.10).

§8.10 dà due origini alle regole. Questo modulo copre la prima: quelle che
**detti tu** — «questa cosa dimmela alle 19», «dimmelo prima di lezione» — che
diventano attive subito, perché scrivendole le hai già approvate. Le
auto-proposte da pattern hanno bisogno di Claude e di uno storico su cui
ragionare, e §12 le mette dopo.

**Niente modello, qui dentro né a valle.** §8.10 è esplicita: una regola già
approvata si valuta con logica pura, costo zero. Il modello serve solo a capire
la frase con cui la crei, e quello succede in `custode_router.assistente` — da
lì arriva un'intenzione strutturata, e a scriverla in tabella è questo modulo.

**La valutazione è una funzione pura**, come «cosa è dovuto adesso?» del worker:
`dovute()` prende le regole, un istante e gli eventi, e non tocca né database né
orologio. È la stessa ragione di `custode_worker.pianificazione` — l'unica cosa
che può sbagliare, *quando*, si prova in un millesimo di secondo invece che
aspettando le 19.

**Chi ricorda cosa è già scattato non sta qui.** Sta in `job_runs`, come per
ogni altro lavoro periodico: uno `Scatto` porta la chiave con cui si registra, e
il worker la usa per non mandarti lo stesso promemoria due volte se riparte.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from custode_core.dominio import impostazioni as dom_impostazioni
from custode_core.formato import GIORNI, plurale

FINESTRA = timedelta(minutes=5)
"""Quanto indietro guarda una valutazione: la larghezza di un giro del worker.

Una regola scatta se il momento previsto cade negli ultimi cinque minuti da
adesso. In esercizio normale il worker passa ogni cinque minuti e non perde
niente; se il Pi era spento, la finestra resta larga cinque minuti e tutto il
resto è perso.

**Perso e non recuperato, ed è una scelta.** Il riepilogo settimanale e il
backup guardano indietro perché il lavoro arretrato esiste ancora — la settimana
da riassumere non scade. Un promemoria no: «prendi la creatina» che arriva alle
23:30 perché il Pi era spento alle 19 non è un recupero, è rumore, ed è lo
stesso ragionamento per cui `fascia_dovuta` della sincronizzazione non guarda
indietro.

Non è configurabile: discende dal passo del worker, non dai gusti della
macchina su cui gira.
"""

MAX_MINUTI = 24 * 60
"""Quanto può distare uno scatto dal suo evento: un giorno.

Oltre, «prima di lezione» non parla più di quella lezione — e un anticipo di tre
giorni su una serie settimanale si sovrapporrebbe all'occorrenza precedente,
cioè la stessa regola direbbe due cose insieme.
"""

MAX_CARATTERI_MESSAGGIO = 300
"""Un promemoria è una riga. Più lungo non è un promemoria, è una voce di diario."""


class RegolaInesistente(LookupError):
    """L'id richiesto non corrisponde a nessuna regola."""


class TransizioneNonValida(ValueError):
    """Lo stato chiesto non si può raggiungere da quello attuale."""


class Trigger(StrEnum):
    """I tipi di trigger che una regola può avere oggi.

    §8.10 ne elenca un quarto, `pattern`, e qui non c'è: è il trigger di una
    regola che il motore genera da sé, e la sua forma si conoscerà costruendo
    quel motore. Ammetterlo adesso vorrebbe dire permettere una regola `attiva`
    che nessun valutatore sa far scattare.
    """

    ORARIO = "orario"
    PRIMA_EVENTO = "prima_evento"
    DOPO_EVENTO = "dopo_evento"


class Stato(StrEnum):
    PROPOSTA = "proposta"
    """Nessun codice la produce ancora: la scriverà il job delle auto-proposte."""
    ATTIVA = "attiva"
    PAUSA = "pausa"
    SCARTATA = "scartata"
    """Non si cancella: la pagina Regole mostra le scartate e promette che
    Custode non ne riproponga una due volte — una promessa che si mantiene solo
    se la riga resta."""


class Origine(StrEnum):
    IA = "ia"
    UTENTE = "utente"


TUTTI_I_GIORNI: tuple[int, ...] = ()
"""Nessun giorno indicato vuol dire **tutti**, non nessuno.

È il caso normale («dimmi alle 19»), e scrivere i sette numeri per dirlo
renderebbe più difficile da leggere proprio la riga più frequente.
"""


@dataclass(frozen=True)
class Regola:
    """Una regola in archivio.

    I campi del trigger sono tre e solo quelli del proprio tipo sono
    valorizzati: lo impone il `CHECK` della migrazione 011, così non può
    esistere una regola a orario che si porta dietro anche un tipo di evento —
    con nessuno in grado di dire quale dei due conti.
    """

    id: int
    origine: Origine
    trigger: Trigger
    messaggio: str
    stato: Stato
    creata_il: datetime

    ora: str | None = None
    """`HH:MM` locali, solo per `orario`."""
    giorni: tuple[int, ...] = TUTTI_I_GIORNI
    """Giorni della settimana come li numera Python (1 = lunedì … 7 = domenica).
    Vuoto: tutti."""
    tipo_evento: str | None = None
    """Lo slug di un `calendar_tags`, solo per `prima_evento` e `dopo_evento`."""
    minuti: int | None = None
    """Minuti prima dell'inizio, o dopo la fine."""

    def vale_il(self, giorno: date) -> bool:
        return not self.giorni or giorno.isoweekday() in self.giorni


@dataclass(frozen=True)
class EventoInCalendario:
    """Ciò che serve di un evento per far scattare una regola.

    Un `dataclass` e non il `calendario.Evento` intero perché `dovute()` è pura
    e si prova scrivendo gli eventi a mano: un test che deve costruire titolo,
    luogo, serie e timbri di sincronizzazione per provare un anticipo di trenta
    minuti è un test che nessuno scrive.
    """

    id: int
    tipo: str
    inizio: datetime
    fine: datetime
    tutto_il_giorno: bool = False


@dataclass(frozen=True)
class Scatto:
    """Una regola che è il momento di far scattare, e quando era il momento."""

    regola: Regola
    momento: datetime
    """L'istante previsto, non quello in cui la si è valutata: è ciò che rende la
    chiave stabile fra due giri del worker."""
    evento_id: int | None = None
    """L'evento che l'ha fatta scattare, per i trigger che ne hanno uno."""

    @property
    def nome_job(self) -> str:
        """Come si chiama in `job_runs`."""
        return nome_job(self.regola.id)

    @property
    def chiave(self) -> str:
        """Il periodo, in `job_runs`: l'istante previsto, e l'evento se c'è.

        L'evento fa parte della chiave e non è ridondante: due lezioni diverse
        che cominciano alla stessa ora — succede, due corsi in due aule —
        darebbero lo stesso istante, e senza l'id la seconda risulterebbe già
        fatta.
        """
        istante = self.momento.isoformat(timespec="minutes")
        return istante if self.evento_id is None else f"{istante}#{self.evento_id}"


def nome_job(regola_id: int) -> str:
    """Il nome con cui gli scatti di una regola stanno in `job_runs`.

    Un nome per regola, non uno solo per tutte: il registro tiene il conto «per
    periodo», e periodi di regole diverse non hanno niente da dirsi. Serve anche
    alla pagina, che conta quante volte ha scattato *ognuna*.
    """
    return f"regola:{regola_id}"


# — la valutazione, pura —


def dovute(
    regole: Sequence[Regola],
    adesso: datetime,
    *,
    eventi: Sequence[EventoInCalendario] = (),
    finestra: timedelta = FINESTRA,
) -> list[Scatto]:
    """Le regole da far scattare adesso, con l'istante previsto di ognuna.

    Ritorna solo le **attive**: una in pausa non si valuta, e una scartata
    nemmeno. L'ordine è quello degli istanti previsti, così i messaggi arrivano
    nell'ordine in cui le cose dovevano succedere e non in quello degli id.

    La finestra è aperta a sinistra e chiusa a destra — `(adesso - finestra,
    adesso]` — e non è pignoleria: con entrambi gli estremi inclusi, un istante
    esattamente cinque minuti fa rientrerebbe nel giro di adesso **e** in quello
    di prima. A non mandarti due volte lo stesso promemoria basterebbe comunque
    `job_runs`, ma un valutatore che restituisce due volte lo stesso scatto è un
    valutatore che non si può provare senza un database accanto.
    """
    scatti: list[Scatto] = []
    for regola in regole:
        if regola.stato is not Stato.ATTIVA:
            continue
        if regola.trigger is Trigger.ORARIO:
            scatti.extend(_dovute_a_orario(regola, adesso, finestra))
        else:
            scatti.extend(_dovute_da_evento(regola, adesso, finestra, eventi))
    scatti.sort(key=lambda s: (s.momento, s.regola.id, s.evento_id or 0))
    return scatti


def _nella_finestra(momento: datetime, adesso: datetime, finestra: timedelta) -> bool:
    return adesso - finestra < momento <= adesso


def _dovute_a_orario(regola: Regola, adesso: datetime, finestra: timedelta) -> list[Scatto]:
    """Gli scatti a orario, guardando anche a **ieri**.

    Ieri perché la finestra scavalca la mezzanotte: una regola delle 23:58
    valutata alle 00:01 ha il suo istante nel giorno prima, e guardare solo
    `adesso.date()` la perderebbe una notte su due. Il giorno della settimana si
    controlla su quello dell'**occorrenza** e non su quello di adesso, o una
    regola del lunedì scatterebbe il martedì mattina.
    """
    assert regola.ora is not None  # lo garantisce il CHECK della 011
    ore, minuti = dom_impostazioni.ore_e_minuti(regola.ora)
    scatti: list[Scatto] = []
    for giorno in (adesso.date(), adesso.date() - timedelta(days=1)):
        if not regola.vale_il(giorno):
            continue
        momento = datetime.combine(giorno, datetime.min.time()).replace(hour=ore, minute=minuti)
        if _nella_finestra(momento, adesso, finestra):
            scatti.append(Scatto(regola=regola, momento=momento))
    return scatti


def _dovute_da_evento(
    regola: Regola,
    adesso: datetime,
    finestra: timedelta,
    eventi: Sequence[EventoInCalendario],
) -> list[Scatto]:
    """Gli scatti agganciati a un tipo di evento: **uno per ogni evento**.

    Tre lezioni in un giorno sono tre messaggi, ognuno col suo anticipo rispetto
    alla sua lezione: «fra trenta minuti hai lezione» detto una volta sola al
    mattino non aiuterebbe per quella delle sedici.

    Gli eventi **di giornata restano fuori**, ed è una regola che il progetto
    aveva già scritto prima che le regole esistessero: `custode_calendario.Evento`
    dice che un evento senza un'ora non ha un «prima». Un compleanno che in
    tabella finisce alle 23:59:59 farebbe scattare «dopo» a mezzanotte, il che
    non vuol dire niente.
    """
    assert regola.minuti is not None  # lo garantisce il CHECK della 011
    scarto = timedelta(minutes=regola.minuti)
    scatti: list[Scatto] = []
    for evento in eventi:
        if evento.tutto_il_giorno or evento.tipo != regola.tipo_evento:
            continue
        momento = (
            evento.inizio - scarto
            if regola.trigger is Trigger.PRIMA_EVENTO
            else evento.fine + scarto
        )
        if _nella_finestra(momento, adesso, finestra):
            scatti.append(Scatto(regola=regola, momento=momento, evento_id=evento.id))
    return scatti


def finestra_eventi(adesso: datetime, finestra: timedelta = FINESTRA) -> tuple[date, date]:
    """I giorni di calendario da leggere per valutare le regole di adesso.

    Un solo giorno non basta in nessuna delle due direzioni: `prima_evento` con
    un anticipo lungo guarda a un evento di domani, `dopo_evento` a uno finito
    ieri, e la finestra stessa scavalca la mezzanotte. `MAX_MINUTI` è un giorno,
    quindi ieri-oggi-domani copre tutto per costruzione.
    """
    del finestra  # il margine di un giorno la contiene comunque
    giorno = adesso.date()
    return giorno - timedelta(days=1), giorno + timedelta(days=1)


# — le forme che una regola può avere —


def _orario(testo: str) -> str:
    """`HH:MM`, normalizzato: «9:5» entra come «09:05».

    Passa dal controllo delle impostazioni (§8) invece di riscriverlo: è la
    stessa domanda, e due normalizzatori di orari destinati a divergere sono
    esattamente ciò che il progetto evita tenendo una cosa in un posto solo.
    """
    ore, minuti = dom_impostazioni.ore_e_minuti(testo)
    return f"{ore:02d}:{minuti:02d}"


def _giorni(giorni: Sequence[int]) -> tuple[int, ...]:
    """I giorni della settimana, ordinati e senza doppioni.

    Sette giorni indicati valgono «tutti», cioè nessuno: sono la stessa regola
    scritta in due modi, e tenerli distinti darebbe due righe che si comportano
    uguale ma si leggono diverse.
    """
    puliti = sorted({int(g) for g in giorni})
    for giorno in puliti:
        if not 1 <= giorno <= 7:
            raise ValueError(
                f"{giorno} non è un giorno della settimana (1 = lunedì … 7 = domenica)"
            )
    return TUTTI_I_GIORNI if len(puliti) == 7 else tuple(puliti)


def _messaggio(testo: str) -> str:
    pulito = " ".join(testo.strip().split())
    if not pulito:
        raise ValueError("una regola senza messaggio non direbbe niente quando scatta")
    if len(pulito) > MAX_CARATTERI_MESSAGGIO:
        raise ValueError(
            f"il messaggio di una regola sta in {MAX_CARATTERI_MESSAGGIO} caratteri:"
            f" questo ne ha {len(pulito)}"
        )
    return pulito


def _minuti(minuti: int) -> int:
    if not 0 <= minuti <= MAX_MINUTI:
        raise ValueError(f"i minuti devono stare fra 0 e {MAX_MINUTI} (un giorno)")
    return minuti


def etichetta_giorni(giorni: tuple[int, ...]) -> str:
    """«tutti i giorni», «il lunedì», «la domenica», «lunedì, mercoledì e venerdì».

    L'articolo lo prende solo il giorno singolo, e segue il genere: in italiano
    la domenica è l'unica femminile della settimana, e «il domenica» è il tipo
    di stonatura che nessun test prende e che si legge ogni volta che la regola
    scatta.
    """
    if not giorni:
        return "tutti i giorni"
    nomi = [GIORNI[g - 1] for g in giorni]
    if len(nomi) == 1:
        articolo = "la" if giorni[0] == 7 else "il"
        return f"{articolo} {nomi[0]}"
    return f"{', '.join(nomi[:-1])} e {nomi[-1]}"


def descrizione(regola: Regola) -> str:
    """La regola detta a parole: «tutti i giorni alle 19:00», «30 minuti prima…».

    Sta qui e non in chi la mostra perché la dicono in **tre** posti — il
    promemoria che ti arriva su Telegram, la conferma quando la scrivi, e la
    riga della pagina Regole — e tre frasi destinate a divergere sono esattamente
    ciò che il progetto evita tenendo le etichette in un posto solo.
    """
    if regola.trigger is Trigger.ORARIO:
        return f"{etichetta_giorni(regola.giorni)} alle {regola.ora}"

    tipo = f"un impegno di tipo «{regola.tipo_evento}»"
    prima = regola.trigger is Trigger.PRIMA_EVENTO
    if not regola.minuti:
        return f"{'quando comincia' if prima else 'appena finisce'} {tipo}"
    quanto = plurale(regola.minuti, "minuto", "minuti")
    return f"{quanto} {'prima di' if prima else 'dopo'} {tipo}"


# — lettura —


def _da_riga(riga: sqlite3.Row) -> Regola:
    grezzi = riga["giorni"]
    return Regola(
        id=riga["id"],
        origine=Origine(riga["origine"]),
        trigger=Trigger(riga["trigger_tipo"]),
        messaggio=riga["messaggio"],
        stato=Stato(riga["stato"]),
        creata_il=datetime.fromisoformat(riga["creata_il"]),
        ora=riga["ora"],
        giorni=tuple(int(g) for g in grezzi.split(",")) if grezzi else TUTTI_I_GIORNI,
        tipo_evento=riga["tipo_evento"],
        minuti=riga["minuti"],
    )


def elenco(conn: sqlite3.Connection, *, stati: Sequence[Stato] | None = None) -> list[Regola]:
    """Le regole, dalla più recente. Con `stati`, solo quelle negli stati dati."""
    dove = ""
    valori: list[object] = []
    if stati is not None:
        dove = f"WHERE stato IN ({', '.join('?' for _ in stati)}) "
        valori = [s.value for s in stati]
    righe = conn.execute(f"SELECT * FROM context_rules {dove}ORDER BY id DESC", valori)
    return [_da_riga(r) for r in righe]


def attive(conn: sqlite3.Connection) -> list[Regola]:
    """Quelle che il worker deve valutare, e nessun'altra."""
    return elenco(conn, stati=[Stato.ATTIVA])


def per_id(conn: sqlite3.Connection, regola_id: int) -> Regola:
    riga = conn.execute("SELECT * FROM context_rules WHERE id = ?", (regola_id,)).fetchone()
    if riga is None:
        raise RegolaInesistente(regola_id)
    return _da_riga(riga)


# — scrittura —


def crea_a_orario(
    conn: sqlite3.Connection,
    *,
    ora: str,
    messaggio: str,
    creata_il: datetime,
    giorni: Sequence[int] = (),
    origine: Origine = Origine.UTENTE,
    stato: Stato = Stato.ATTIVA,
) -> Regola:
    """«Dimmi alle 19 di prendere la creatina», «ogni domenica sera chiedimi…».

    Nasce **attiva**: §8.10 dice che una regola dettata da te non ha bisogno di
    un'altra conferma, perché scrivendola l'hai già approvata.
    """
    return _inserisci(
        conn,
        trigger=Trigger.ORARIO,
        ora=_orario(ora),
        giorni=_giorni(giorni),
        tipo_evento=None,
        minuti=None,
        messaggio=_messaggio(messaggio),
        origine=origine,
        stato=stato,
        creata_il=creata_il,
    )


def crea_da_evento(
    conn: sqlite3.Connection,
    *,
    trigger: Trigger,
    tipo_evento: str,
    minuti: int,
    messaggio: str,
    creata_il: datetime,
    origine: Origine = Origine.UTENTE,
    stato: Stato = Stato.ATTIVA,
) -> Regola:
    """«Trenta minuti prima di una lezione», «appena finisce la palestra».

    `tipo_evento` è lo **slug** di un tipo, e che esista lo garantisce la chiave
    esterna della 011: un tipo cancellato mentre scrivevi la regola fa fallire
    l'inserimento invece di lasciare una regola che non scatterà mai.
    """
    if trigger not in (Trigger.PRIMA_EVENTO, Trigger.DOPO_EVENTO):
        raise ValueError(f"«{trigger}» non è un trigger agganciato a un evento")
    return _inserisci(
        conn,
        trigger=trigger,
        ora=None,
        giorni=TUTTI_I_GIORNI,
        tipo_evento=tipo_evento,
        minuti=_minuti(minuti),
        messaggio=_messaggio(messaggio),
        origine=origine,
        stato=stato,
        creata_il=creata_il,
    )


def _inserisci(
    conn: sqlite3.Connection,
    *,
    trigger: Trigger,
    ora: str | None,
    giorni: tuple[int, ...],
    tipo_evento: str | None,
    minuti: int | None,
    messaggio: str,
    origine: Origine,
    stato: Stato,
    creata_il: datetime,
) -> Regola:
    cursore = conn.execute(
        "INSERT INTO context_rules"
        " (origine, trigger_tipo, ora, giorni, tipo_evento, minuti, messaggio, stato, creata_il)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            origine.value,
            trigger.value,
            ora,
            ",".join(str(g) for g in giorni),
            tipo_evento,
            minuti,
            messaggio,
            stato.value,
            creata_il.isoformat(timespec="seconds"),
        ),
    )
    return per_id(conn, int(cursore.lastrowid or 0))


_TRANSIZIONI: dict[Stato, frozenset[Stato]] = {
    Stato.PROPOSTA: frozenset({Stato.ATTIVA, Stato.SCARTATA}),
    Stato.ATTIVA: frozenset({Stato.PAUSA, Stato.SCARTATA}),
    Stato.PAUSA: frozenset({Stato.ATTIVA, Stato.SCARTATA}),
    Stato.SCARTATA: frozenset(),
}
"""Da dove si può andare dove.

Scritto qui e non lasciato implicito nelle rotte perché è la sola cosa che
impedisce a una regola scartata di tornare attiva senza che tu l'abbia chiesto —
e §8.10 promette che una scartata non si ripropone. Approvare è la transizione
`proposta → attiva`: oggi nessuna riga è in `proposta`, quindi non la prende
mai nessuno, ma è la stessa tabella che leggerà il job delle auto-proposte.
"""


def imposta_stato(conn: sqlite3.Connection, regola_id: int, stato: Stato) -> Regola:
    """Mette in pausa, riattiva, approva o scarta. Solleva se la mossa non esiste."""
    regola = per_id(conn, regola_id)
    if stato is regola.stato:
        return regola
    if stato not in _TRANSIZIONI[regola.stato]:
        raise TransizioneNonValida(f"una regola «{regola.stato}» non può diventare «{stato}»")
    conn.execute("UPDATE context_rules SET stato = ? WHERE id = ?", (stato.value, regola_id))
    return per_id(conn, regola_id)


def elimina(conn: sqlite3.Connection, regola_id: int) -> None:
    """Cancella una regola per davvero. Serve a «Annulla», e a null'altro.

    Cancellare e scartare non sono la stessa cosa, ed è la stessa distinzione
    dei tipi di evento fra archiviare e cancellare: **scartare** è una decisione
    che resta — la pagina mostra le scartate e Custode non le ripropone —
    mentre qui si sta disfacendo un gesto di trenta secondi fa, che il modello
    ha capito male. Una regola nata per errore non deve lasciare traccia in un
    elenco di scelte che non hai mai fatto.
    """
    if conn.execute("DELETE FROM context_rules WHERE id = ?", (regola_id,)).rowcount == 0:
        raise RegolaInesistente(regola_id)
