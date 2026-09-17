"""Le regole di contesto (ARCHITECTURE.md §8.10).

§8.10 dà due origini alle regole, e adesso ci sono tutte e due. Quelle che
**detti tu** — «questa cosa dimmela alle 19», «dimmelo prima di lezione» —
nascono attive, perché scrivendole le hai già approvate. Quelle **auto-proposte**
nascono in stato `proposta`, con la confidenza e il perché di chi le ha
proposte, e diventano attive solo se le approvi.

**Una proposta è una regola concreta**, non un tipo di trigger a parte: ha uno
dei tre trigger di sempre, quindi il giorno che l'approvi la fa scattare lo
stesso `dovute()` già scritto e già provato. Quello che §8.10 chiama «trigger
pattern» è in realtà `origine`: il pattern è come la regola è nata, non come
scatta.

**Niente modello, qui dentro né a valle.** §8.10 è esplicita: una regola già
approvata si valuta con logica pura, costo zero. Il modello serve a capire la
frase con cui la detti (`custode_router.assistente`) e a giudicare se un pattern
regge abbastanza da proporlo (`custode_router.regole`); da tutti e due arriva
roba strutturata, e a scriverla in tabella è questo modulo. Anche il confronto
che impedisce di riproporre una regola già scartata sta qui ed è **senza
modello**: `stessa_proposta()` è una funzione pura.

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
import unicodedata
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

MAX_CARATTERI_MOTIVAZIONE = 400
"""Il perché di una proposta sta in due righe di pagina.

Più lungo non aiuta a decidere: se per spiegarti un pattern servono cinque
righe, quel pattern non regge abbastanza da meritare un'interruzione.
"""

GIORNI_SCADENZA_PROPOSTA = 14
"""Dopo quanto una proposta che non hai guardato passa fra le scartate.

Due settimane di silenzio sono una risposta, e trattarle come tale è ciò che
tiene corta la coda: una coda di proposte che non guardi mai è una coda che
smetti di guardare. La scadenza **non cancella** la riga — la porta in
`scartata`, cioè nella stessa memoria che impedisce di riproporla, che è la
promessa di §8.10. Non c'è uno stato `scaduta` apposta: distinguerebbe il non
deciso dal rifiutato senza cambiare niente di quello che succede dopo.
"""

MAX_PROPOSTE_IN_ATTESA = 3
"""Quante proposte non decise possono stare in coda insieme.

È la valvola: se non decidi, Custode **smette di chiedere** invece di
accumulare. Tre insieme sono già un elenco da smaltire; il quarto candidato non
scappa, lo storico da cui è uscito c'è ancora domani notte.
"""

SOGLIA_PAROLE_SIMILI = 0.6
"""Quanto si devono somigliare due messaggi per essere la stessa proposta.

È la frazione di parole del messaggio **più corto** che si ritrovano nell'altro,
non un Jaccard: «prendi la creatina» e «prendi la creatina prima di uscire»
dicono la stessa cosa, e un indice che le divide per l'unione le farebbe
sembrare diverse man mano che una delle due si allunga.
"""

MINUTI_STESSA_ORA = 60
"""Entro quanto due promemoria a orario parlano dello stesso momento.

Serve a non fermarsi all'uguaglianza esatta: una proposta alle 19:00 e una alle
19:30 sono la stessa idea con una manopola girata, ed è proprio il caso
«simile ma non identico» che §8.10 chiede di non riproporre.
"""


class RegolaInesistente(LookupError):
    """L'id richiesto non corrisponde a nessuna regola."""


class TransizioneNonValida(ValueError):
    """Lo stato chiesto non si può raggiungere da quello attuale."""


class Trigger(StrEnum):
    """I tipi di trigger che una regola può avere oggi.

    §8.10 ne elenca un quarto, `pattern`, e qui continua a non esserci — adesso
    non più perché la sua forma è ignota, ma perché **non serve**: una regola
    auto-proposta nasce già con uno di questi tre, quindi la fa scattare lo
    stesso valutatore di tutte le altre. Il pattern è come la regola è nata, e
    quello lo dice `Origine.IA`.
    """

    ORARIO = "orario"
    PRIMA_EVENTO = "prima_evento"
    DOPO_EVENTO = "dopo_evento"


class Stato(StrEnum):
    PROPOSTA = "proposta"
    """Custode l'ha proposta e aspetta che tu decida. Ci arriva solo il job delle
    auto-proposte, e ci resta al massimo `GIORNI_SCADENZA_PROPOSTA` giorni."""
    ATTIVA = "attiva"
    PAUSA = "pausa"
    SCARTATA = "scartata"
    """Non si cancella: la pagina Regole mostra le scartate e promette che
    Custode non ne riproponga una due volte — una promessa che si mantiene solo
    se la riga resta."""


class Origine(StrEnum):
    IA = "ia"
    UTENTE = "utente"


class Confidenza(StrEnum):
    """Quanto Custode crede alla proposta che ti sta facendo.

    A parole e non come numero, ed è la forma che il contratto della dashboard
    chiede da sempre (`RegolaProposta.confidenza` è una `string`): «0.82» sarebbe
    una precisione che non c'è dietro — nessuno ha calibrato niente — mentre
    «alta» dice a colpo d'occhio l'unica cosa che serve, se guardarla adesso o
    dopo.
    """

    ALTA = "alta"
    MEDIA = "media"
    BASSA = "bassa"


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

    confidenza: Confidenza | None = None
    """Quanto Custode ci credeva, solo sulle regole che ha proposto lui."""
    motivazione: str | None = None
    """Il pattern che l'ha fatta nascere, a parole. Solo su quelle proposte.

    Non si azzera quando la approvi: «questa te l'aveva proposta Custode a
    settembre, e per questo motivo» è la risposta a «e questa da dove salta
    fuori?» sei mesi dopo.
    """

    def vale_il(self, giorno: date) -> bool:
        return not self.giorni or giorno.isoweekday() in self.giorni

    def scade_il(self) -> datetime:
        """Quando smetterà di aspettare una risposta. Ha senso solo su una proposta."""
        return self.creata_il + timedelta(days=GIORNI_SCADENZA_PROPOSTA)

    def abbozzo(self) -> Abbozzo:
        """Come si presenta al confronto con una proposta nuova."""
        return Abbozzo(
            trigger=self.trigger,
            testo=self.messaggio,
            ora=self.ora,
            tipo_evento=self.tipo_evento,
        )


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


def _motivazione(testo: str | None) -> str | None:
    if testo is None:
        return None
    pulito = " ".join(testo.strip().split())
    if not pulito:
        raise ValueError("una proposta senza il perché non si può mostrare")
    if len(pulito) > MAX_CARATTERI_MOTIVAZIONE:
        raise ValueError(
            f"il perché di una proposta sta in {MAX_CARATTERI_MOTIVAZIONE} caratteri:"
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


# — «questa te l'ho già proposta», senza chiamare nessuno —


@dataclass(frozen=True)
class Abbozzo:
    """La forma di una proposta, ridotta a ciò che la rende «la stessa».

    Non è una `Regola` a cui manca l'id: è **di proposito più grossolana**.
    §8.10 promette che una regola scartata non venga riproposta, e mantenerlo
    con l'uguaglianza esatta non basta — «trenta minuti prima di palestra» e
    «quarantacinque minuti prima di palestra» sono la stessa proposta con una
    manopola girata, e riproporre la seconda il giorno dopo che hai scartato la
    prima è esattamente il modo di far smettere di guardare la pagina.

    Quindi qui dentro **non** ci sono i minuti, né la direzione fra prima e
    dopo, né i giorni della settimana: sono le manopole. Ci sono l'aggancio
    (quale tipo di impegno, o che ora del giorno) e cosa dice.
    """

    trigger: Trigger
    testo: str
    """Il messaggio della regola. Prima che Claude lo scriva, il nome della cosa
    di cui parla — che è quanto basta a riconoscere un doppione senza pagare una
    chiamata per scoprirlo dopo."""
    ora: str | None = None
    tipo_evento: str | None = None


_PAROLE_VUOTE = frozenset(
    {
        # Le parole che ci sono in quasi ogni promemoria e non distinguono niente:
        # se restassero, «ricordami la creatina» e «ricordami il portatile»
        # avrebbero già una parola in comune su due.
        "che",
        "chi",
        "col",
        "come",
        "con",
        "cosa",
        "dal",
        "dalla",
        "degli",
        "dei",
        "del",
        "della",
        "delle",
        "dello",
        "dimmi",
        "dopo",
        "ogni",
        "per",
        "poi",
        "prima",
        "quando",
        "ricorda",
        "ricordami",
        "ricordarmi",
        "ricordati",
        "sempre",
        "sul",
        "sulla",
        "tra",
        "tue",
        "tuo",
        "tuoi",
        "tutte",
        "tutti",
        "una",
        "uno",
    }
)


def _normalizza(testo: str) -> str:
    """Minuscolo e senza accenti: «perché» e «perche» sono la stessa parola.

    Serve perché i due testi da confrontare arrivano da due tastiere diverse —
    uno l'hai scritto tu da Telegram, l'altro l'ha scritto un modello — e un
    accento di differenza non deve far sembrare nuova una proposta già scartata.
    """
    scomposto = unicodedata.normalize("NFD", testo.casefold())
    return "".join(c for c in scomposto if not unicodedata.combining(c))


def _parole(testo: str) -> frozenset[str]:
    """Le parole che distinguono un promemoria da un altro.

    Sotto le tre lettere non si tiene niente: sono articoli e preposizioni, e un
    elenco che li contenesse tutti sarebbe una lista da manutenere per sempre.
    """
    pulito = "".join(c if c.isalnum() else " " for c in _normalizza(testo))
    return frozenset(p for p in pulito.split() if len(p) >= 3 and p not in _PAROLE_VUOTE)


def _parole_simili(primo: str, secondo: str) -> bool:
    pa, pb = _parole(primo), _parole(secondo)
    if not pa or not pb:
        # Un messaggio fatto solo di parole corte («bevi»): niente su cui
        # calcolare una frazione, quindi si torna all'uguaglianza del testo.
        return _normalizza(primo).split() == _normalizza(secondo).split()
    return len(pa & pb) / min(len(pa), len(pb)) >= SOGLIA_PAROLE_SIMILI


def _minuti_del_giorno(ora: str) -> int:
    ore, minuti = dom_impostazioni.ore_e_minuti(ora)
    return ore * 60 + minuti


def _stesso_aggancio(primo: Abbozzo, secondo: Abbozzo) -> bool:
    """Se i due scattano nello stesso punto della giornata o della tua settimana."""
    a_orario = primo.trigger is Trigger.ORARIO
    b_orario = secondo.trigger is Trigger.ORARIO
    if a_orario != b_orario:
        return False
    if a_orario:
        assert primo.ora is not None and secondo.ora is not None
        scarto = abs(_minuti_del_giorno(primo.ora) - _minuti_del_giorno(secondo.ora))
        # In tondo sulla giornata: le 23:50 e le 00:10 distano venti minuti, non
        # ventitré ore e quaranta.
        return min(scarto, 24 * 60 - scarto) <= MINUTI_STESSA_ORA
    # Prima e dopo lo stesso impegno sono la stessa proposta: la direzione è una
    # manopola, e §8.10 chiede di non riproporre nemmeno il «simile».
    return primo.tipo_evento == secondo.tipo_evento


def stessa_proposta(primo: Abbozzo, secondo: Abbozzo) -> bool:
    """Se i due sono la stessa proposta — **senza chiedere niente a nessuno**.

    È la funzione che mantiene la promessa di §8.10 («una scartata non si
    ripropone») senza pagarla con una seconda chiamata al modello solo per
    confrontare due frasi. Due condizioni insieme, e il perché sono due:
    l'aggancio da solo zittirebbe per sempre qualunque altra proposta sullo
    stesso impegno — la borraccia dopo che hai scartato la creatina — e le sole
    parole aggancerebbero un promemoria del mattino a uno della sera che dicono
    la stessa cosa in momenti che non c'entrano niente.
    """
    return _stesso_aggancio(primo, secondo) and _parole_simili(primo.testo, secondo.testo)


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
        confidenza=Confidenza(riga["confidenza"]) if riga["confidenza"] else None,
        motivazione=riga["motivazione"],
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


def in_attesa(conn: sqlite3.Connection) -> list[Regola]:
    """Le proposte che aspettano una tua risposta."""
    return elenco(conn, stati=[Stato.PROPOSTA])


def gia_vista(conn: sqlite3.Connection, abbozzo: Abbozzo) -> Regola | None:
    """La regola che copre già questo abbozzo, se c'è. **In qualunque stato.**

    Non solo fra le scartate, e le altre tre non sono un di più:
    - una **attiva** che dice già questa cosa renderebbe la proposta un
      doppione da approvare per ricevere due volte lo stesso promemoria;
    - una in **pausa** l'hai messa in pausa apposta, e riproporla sarebbe
      chiedere di riaccendere ciò che hai appena spento;
    - una **proposta** è già in coda: riproporla riempirebbe il tetto con la
      stessa domanda scritta due volte.

    Ritorna la regola e non un `bool` perché chi chiama ci scrive sopra una riga
    di log che serve a capire *perché* una notte non è uscito niente.
    """
    for regola in elenco(conn):
        if stessa_proposta(regola.abbozzo(), abbozzo):
            return regola
    return None


def scadi_proposte(conn: sqlite3.Connection, adesso: datetime) -> list[Regola]:
    """Porta fra le scartate le proposte che aspettano da troppo. Ritorna quali.

    Due settimane di silenzio sono una risposta, e trattarle come tale è ciò che
    tiene corta la coda. Finiscono in `scartata` e non cancellate: è la stessa
    memoria che impedisce di riproporle, cioè la promessa di §8.10 — e la pagina
    le mostra, il che è la verità, Custode te l'aveva chiesto e non hai risposto.

    L'`UPDATE` è uno solo e non passa da `imposta_stato`: `proposta → scartata`
    è una transizione che `_TRANSIZIONI` ammette già, quindi non c'è nessuna
    regola da far rispettare riga per riga, e una scadenza che facesse una query
    per proposta pagherebbe il tetto di tre con tre giri.
    """
    scadute = [r for r in in_attesa(conn) if r.scade_il() <= adesso]
    if not scadute:
        return []
    conn.execute(
        "UPDATE context_rules SET stato = ? WHERE id IN" f" ({', '.join('?' for _ in scadute)})",
        [Stato.SCARTATA.value, *(r.id for r in scadute)],
    )
    return scadute


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
    confidenza: Confidenza | None = None,
    motivazione: str | None = None,
) -> Regola:
    """«Dimmi alle 19 di prendere la creatina», «ogni domenica sera chiedimi…».

    Di default nasce **attiva**: §8.10 dice che una regola dettata da te non ha
    bisogno di un'altra conferma, perché scrivendola l'hai già approvata. Il job
    delle auto-proposte passa invece `stato=PROPOSTA` con la sua confidenza.
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
        confidenza=confidenza,
        motivazione=motivazione,
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
    confidenza: Confidenza | None = None,
    motivazione: str | None = None,
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
        confidenza=confidenza,
        motivazione=motivazione,
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
    confidenza: Confidenza | None = None,
    motivazione: str | None = None,
) -> Regola:
    motivazione = _motivazione(motivazione)
    # Il CHECK della 012 dice la stessa cosa, e non è un doppione: là è la rete
    # che tiene lo schema coerente contro chiunque scriva in tabella, qui è un
    # messaggio leggibile per chi ha sbagliato a chiamare. Un `IntegrityError`
    # di SQLite non nomina quale dei due vincoli ha toccato.
    if (origine is Origine.IA) != (confidenza is not None):
        raise ValueError(
            "confidenza e motivazione vanno insieme a origine «ia», e solo a quella:"
            " una regola che hai dettato tu non ha una confidenza perché nessuno"
            " l'ha stimata"
        )
    if (confidenza is None) != (motivazione is None):
        raise ValueError("una proposta senza il perché non si può mostrare")

    cursore = conn.execute(
        "INSERT INTO context_rules"
        " (origine, trigger_tipo, ora, giorni, tipo_evento, minuti, messaggio,"
        " confidenza, motivazione, stato, creata_il)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            origine.value,
            trigger.value,
            ora,
            ",".join(str(g) for g in giorni),
            tipo_evento,
            minuti,
            messaggio,
            confidenza.value if confidenza is not None else None,
            motivazione,
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
`proposta → attiva`, e scartare o lasciar scadere una proposta è
`proposta → scartata`: da lì non si torna, che è ciò che rende l'elenco delle
scartate una memoria affidabile per `gia_vista`.
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
