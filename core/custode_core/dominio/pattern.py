"""I pattern da cui nasce una proposta di regola (ARCHITECTURE.md §6, §8.10).

§8.10 vuole «un job periodico che cerca pattern nei dati storici (calendario,
abitudini, orari in cui scrivi) e, appena trova un pattern che regge, ti propone
una regola». Questo modulo è la prima metà di quella frase: **cerca**, conta, e
dice quali candidati reggono abbastanza da valere una domanda. La seconda metà —
se valga la pena interromperti, e con che parole dirtelo — è giudizio, e §6 la
manda a Claude (`custode_router.regole`).

**Il taglio fra i due non è arbitrario.** Contare è una cosa che il codice fa
meglio e gratis: quante giornate con palestra ci sono state, in quante hai
segnato la creatina, in quante delle altre l'hai segnata comunque. Un modello
che conta è un modello che sbaglia a contare, e per giunta lo fa a pagamento una
volta a notte per sempre — anche le notti, che sono quasi tutte, in cui non è
cambiato niente. Quindi qui c'è una **soglia**, e se non la passa nessuno il job
non chiama nessuno: è lo stesso ripiego di `calendario.gruppi_senza_tag`, che su
coda vuota torna senza aver parlato con nessun modello.

**Tutto quello che conta è puro.** `cerca()` prende degli elenchi e restituisce
dei candidati, senza toccare né database né orologio — come `regole.dovute()` e
come `pianificazione`. È l'unico modo di provare «otto lezioni su otto» senza
aspettare otto settimane.

**Un candidato è già una regola concreta.** Non esiste un pattern che resta
pattern: quello che esce di qui ha un aggancio che il valutatore di §8.10 sa già
far scattare — un'ora del giorno, o un tipo di impegno. È la ragione per cui il
quarto trigger `pattern` di §8.10 non è mai servito.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from custode_core.dominio import calendario as dom_calendario
from custode_core.dominio import regole as dom_regole

SETTIMANE_DI_STORICO = 8
"""Quanto indietro si guarda: due mesi.

Un impegno settimanale ci sta dentro otto volte, che è abbastanza per
distinguere «sempre» da «due volte di fila». Su quattro settimane quattro
ripetizioni sono poche e una coincidenza sembra una regola; su sei mesi
un'abitudine che hai lasciato a marzo peserebbe quanto quella di adesso, e la
proposta arriverebbe per una cosa che non fai più.

Si può guardare così indietro perché `calendar_events` è un **archivio** e non
una cache — §8.10 lo aveva deciso proprio per questo motore, e questa è la riga
di codice che incassa quella decisione.
"""

MIN_OCCASIONI = 4
"""Quante volte l'occasione deve essersi presentata perché il conto voglia dire qualcosa.

Sotto le quattro non si sta misurando un'abitudine, si sta guardando una
coincidenza: due volte di fila capita a chiunque.
"""

MIN_SEGNATE = 6
"""Quante volte devi aver segnato una cosa perché il suo orario abbia una forma.

Più alto delle occasioni perché qui si guarda la **dispersione** di un orario, e
tre punti stanno sempre vicini fra loro per caso.
"""

MIN_COPERTURA = 0.75
"""Quanto spesso, all'occasione, la cosa succede davvero.

Tre volte su quattro. Più in basso non è un'abitudine ma una cosa che ogni
tanto fai, e un promemoria che sbaglia una volta su tre è un promemoria che si
mette in pausa.
"""

MAX_DISPERSIONE = 0.35
"""Quanto può succedere **anche fuori** dall'occasione, prima che l'aggancio sia una bugia.

Serve solo ai pattern agganciati a un impegno, ed è la domanda che distingue
«prendi la creatina quando vai in palestra» da «prendi la creatina», punto. Se
la segni tutti i giorni, la copertura sulle giornate con palestra è comunque del
100% — ma la palestra non c'entra niente, e una regola agganciata a lei tacerebbe
nei giorni in cui non ci vai. Quel caso lo prende il pattern a orario, che è
quello giusto per una cosa di tutti i giorni.
"""

MINUTI_GRAPPOLO = 45
"""Entro quanto due orari parlano dello stesso momento della giornata."""

MIN_CONCENTRAZIONE = 0.70
"""Quanta parte delle volte deve stare dentro il grappolo perché ci sia un orario.

Sotto, quella cosa non ha un'ora: la fai quando capita, e proporre un orario
vorrebbe dire inventare una regolarità che nei dati non c'è.
"""

PASSO_ORARIO = 30
"""A che scatti si arrotonda l'ora proposta, verso il basso.

Mezz'ora, e verso il basso non per pigrizia: l'orario che si misura è quello in
cui **scrivi** di aver fatto una cosa, cioè dopo averla fatta. Un promemoria a
quell'ora esatta arriverebbe sempre un po' tardi; arrotondare indietro gli dà il
piccolo anticipo che serve a essere utile nei giorni in cui te ne dimentichi.
"""


class Genere(StrEnum):
    """Da che tipo di regolarità nasce il candidato."""

    SU_IMPEGNO = "su_impegno"
    """Una cosa che fai nelle giornate in cui hai un certo tipo di impegno, e
    quasi mai nelle altre. Diventa una regola `prima_evento` o `dopo_evento`."""

    A_ORARIO = "a_orario"
    """Una cosa che fai quasi sempre, e quasi sempre alla stessa ora. Diventa una
    regola `orario`. L'ora la dicono gli **orari in cui scrivi** di averla
    fatta: è l'unico orologio che questo progetto abbia su un'abitudine, e §8.10
    lo elenca fra le sorgenti del motore proprio così."""


# — ciò che il nucleo puro riceve —


@dataclass(frozen=True)
class Segnata:
    """Una volta in cui hai detto a Custode di aver fatto una cosa."""

    abitudine: str
    giorno: date
    """Il giorno a cui il log si riferisce."""
    scritto_il: datetime
    """Quando l'hai scritto. **Non** è lo stesso: puoi segnare stamattina la
    corsa di ieri, e in quel caso l'orario non dice niente sull'ora della corsa.
    Chi guarda gli orari tiene solo i log scritti nel giorno a cui si
    riferiscono, e lo fa per questo."""


@dataclass(frozen=True)
class Impegno:
    """Una giornata in cui avevi in calendario un impegno di un certo tipo."""

    giorno: date
    tipo: str


# — ciò che ne esce —


@dataclass(frozen=True)
class Candidato:
    """Una regolarità che ha passato le soglie, coi numeri che l'hanno fatta passare.

    I campi sono quelli del proprio genere e solo quelli — `tipo_evento` e
    `altrove` per `SU_IMPEGNO`, `ora`, `giorni` e il grappolo per `A_ORARIO` —
    con la stessa forma che ha `Regola` per i suoi tre trigger.

    **I numeri viaggiano insieme al candidato** e non restano nella funzione che
    li ha calcolati: sono ciò che Claude legge per decidere se valga la pena
    interromperti, e sono la motivazione che poi ti arriva in pagina. Una
    proposta che dicesse solo «mi pare che tu faccia così» sarebbe un bottone
    «Approva» da premere al buio.
    """

    genere: Genere
    soggetto: str
    """Il nome dell'abitudine di cui parla: «Creatina», «Meditazione»."""

    occasioni: int
    """Quante volte si è presentata l'occasione nella finestra."""
    coperte: int
    """In quante di quelle l'hai fatta."""

    tipo_evento: str | None = None
    altrove: int = 0
    """`SU_IMPEGNO`: in quante giornate **senza** quell'impegno l'hai fatta lo stesso."""
    giornate_altrove: int = 0
    """`SU_IMPEGNO`: quante erano in tutto le giornate senza quell'impegno."""

    ora: str | None = None
    giorni: tuple[int, ...] = ()
    nel_grappolo: int = 0
    """`A_ORARIO`: quanti dei log stanno dentro i `MINUTI_GRAPPOLO` dall'ora trovata."""
    segnate: int = 0
    """`A_ORARIO`: quanti log avevano un orario utilizzabile."""

    @property
    def copertura(self) -> float:
        return self.coperte / self.occasioni if self.occasioni else 0.0

    @property
    def dispersione(self) -> float:
        """Quanto la cosa succede anche fuori dall'occasione. Solo `SU_IMPEGNO`."""
        return self.altrove / self.giornate_altrove if self.giornate_altrove else 0.0

    @property
    def concentrazione(self) -> float:
        """Quanta parte dei log sta dentro il grappolo. Solo `A_ORARIO`."""
        return self.nel_grappolo / self.segnate if self.segnate else 0.0

    @property
    def forza(self) -> float:
        """Quanto regge, fra 0 e 1, **per metterli in fila**.

        Non è una probabilità e non va letta come tale: nessuno l'ha calibrata
        su niente, e serve solo a decidere quale candidato guardare per primo
        quando ce n'è più di uno. Il giudizio vero — se valga un'interruzione —
        arriva dopo, e lo dà Claude con la sua confidenza.
        """
        if self.genere is Genere.SU_IMPEGNO:
            return self.copertura * (1.0 - self.dispersione)
        return self.copertura * self.concentrazione

    def abbozzo(self) -> dom_regole.Abbozzo:
        """Come si presenta al controllo dei doppioni, **prima** di chiamare Claude.

        Il testo è il nome dell'abitudine e non il messaggio finale, che ancora
        non esiste: è quanto basta a riconoscere una cosa già proposta senza
        pagare una chiamata per scoprirlo dopo. Il controllo si rifà comunque
        sul messaggio vero quando c'è, perché Claude potrebbe scriverci sopra
        qualcosa di diverso da quello che ci si aspettava.
        """
        if self.genere is Genere.SU_IMPEGNO:
            return dom_regole.Abbozzo(
                trigger=dom_regole.Trigger.DOPO_EVENTO,
                testo=self.soggetto,
                tipo_evento=self.tipo_evento,
            )
        return dom_regole.Abbozzo(
            trigger=dom_regole.Trigger.ORARIO, testo=self.soggetto, ora=self.ora
        )


# — il nucleo, puro —


def giorni_fra(da: date, a: date) -> list[date]:
    return [da + timedelta(days=i) for i in range((a - da).days + 1)]


def _minuti_del_giorno(momento: datetime) -> int:
    return momento.hour * 60 + momento.minute


def _distanza_circolare(primo: int, secondo: int) -> int:
    """Quanto distano due momenti della giornata, passando anche per la mezzanotte."""
    scarto = abs(primo - secondo)
    return min(scarto, 24 * 60 - scarto)


def _grappolo(minuti: Sequence[int]) -> tuple[int, int]:
    """Il momento attorno a cui gli orari si stringono di più, e quanti ne prende.

    Il centro è uno degli orari veri e non la loro media, e il motivo è la
    mezzanotte: la media fra le 23:50 e le 00:10 è mezzogiorno, che è il momento
    in cui quella cosa non è mai successa. Preso fra i punti, e con una distanza
    che gira in tondo, il conto regge anche a cavallo del giorno.

    A parità di quanti ne prende vince il più mattiniero, perché una scelta che
    dipende dall'ordine delle righe darebbe due risposte diverse allo stesso
    archivio.
    """
    migliore = (0, -1)
    for centro in sorted(set(minuti)):
        dentro = sum(1 for m in minuti if _distanza_circolare(m, centro) <= MINUTI_GRAPPOLO)
        if dentro > migliore[1]:
            migliore = (centro, dentro)
    return migliore


def _ora_proposta(minuti: int) -> str:
    arrotondato = (minuti // PASSO_ORARIO) * PASSO_ORARIO
    return f"{arrotondato // 60:02d}:{arrotondato % 60:02d}"


def _giorni_tuoi(fatti: set[date], giornate: Sequence[date]) -> tuple[int, ...] | None:
    """I giorni della settimana in cui quella cosa succede davvero.

    Un giorno è «tuo» se in quel giorno della settimana la copertura arriva
    comunque a `MIN_COPERTURA`: la stessa soglia del resto, non una seconda da
    tarare. Ne discende che la copertura complessiva sui giorni scelti è per
    costruzione sopra soglia — quindi non c'è un secondo controllo da fare, e
    non ci sono due numeri che potrebbero contraddirsi.

    **`None` e `()` dicono l'opposto, e per questo sono due cose diverse.**
    `()` è `TUTTI_I_GIORNI`, cioè tutti e sette reggono — che è come il resto
    del progetto scrive «tutti», perché «dimmi alle 19» è il caso normale e
    scrivere i sette numeri per dirlo renderebbe più difficile da leggere
    proprio la riga più frequente. `None` è il contrario: non regge nessuno,
    quindi non c'è nessuna regola da proporre. Restituire `()` in tutti e due i
    casi — che è il primo modo in cui questa funzione era scritta — proporrebbe
    un promemoria **tutti i giorni** proprio alle abitudini che non hanno
    nessun ritmo.
    """
    occorrenze: dict[int, int] = {}
    presenze: dict[int, int] = {}
    for giorno in giornate:
        occorrenze[giorno.isoweekday()] = occorrenze.get(giorno.isoweekday(), 0) + 1
        if giorno in fatti:
            presenze[giorno.isoweekday()] = presenze.get(giorno.isoweekday(), 0) + 1
    tuoi = tuple(
        g
        for g in range(1, 8)
        if occorrenze.get(g, 0) and presenze.get(g, 0) / occorrenze[g] >= MIN_COPERTURA
    )
    if not tuoi:
        return None
    return dom_regole.TUTTI_I_GIORNI if len(tuoi) == 7 else tuoi


def _su_impegno(
    abitudine: str, fatti: set[date], impegni: Iterable[Impegno], giornate: Sequence[date]
) -> list[Candidato]:
    """«La creatina quando vai in palestra»: l'esempio che §8.10 fa per esteso."""
    per_tipo: dict[str, set[date]] = {}
    for impegno in impegni:
        per_tipo.setdefault(impegno.tipo, set()).add(impegno.giorno)

    tutte = set(giornate)
    trovati: list[Candidato] = []
    for tipo, con_impegno in per_tipo.items():
        occasioni = len(con_impegno)
        if occasioni < MIN_OCCASIONI:
            continue
        senza_impegno = tutte - con_impegno
        candidato = Candidato(
            genere=Genere.SU_IMPEGNO,
            soggetto=abitudine,
            occasioni=occasioni,
            coperte=len(con_impegno & fatti),
            tipo_evento=tipo,
            altrove=len(fatti & senza_impegno),
            giornate_altrove=len(senza_impegno),
        )
        if candidato.copertura >= MIN_COPERTURA and candidato.dispersione <= MAX_DISPERSIONE:
            trovati.append(candidato)
    return trovati


def _a_orario(
    abitudine: str, segnate: Sequence[Segnata], fatti: set[date], giornate: Sequence[date]
) -> Candidato | None:
    """«La creatina verso le 19»: l'ora la dicono gli orari in cui scrivi.

    Si tengono solo i log **scritti nel giorno a cui si riferiscono**: segnare
    stamattina la corsa di ieri è una cosa che capita, e il suo orario parla di
    quando te ne sei ricordato, non di quando sei uscito a correre. Tenerli
    dentro sposterebbe l'ora proposta verso il mattino di chi recupera.
    """
    in_giornata = [s for s in segnate if s.scritto_il.date() == s.giorno]
    if len(in_giornata) < MIN_SEGNATE:
        return None

    giorni = _giorni_tuoi(fatti, giornate)
    if giorni is None:
        # Nessun giorno della settimana regge da solo: quella cosa non ha un
        # ritmo settimanale, e un promemoria quotidiano parlerebbe a vuoto
        # quasi sempre.
        return None
    validi = [g for g in giornate if not giorni or g.isoweekday() in giorni]
    if len(validi) < MIN_OCCASIONI:
        return None

    centro, dentro = _grappolo([_minuti_del_giorno(s.scritto_il) for s in in_giornata])
    candidato = Candidato(
        genere=Genere.A_ORARIO,
        soggetto=abitudine,
        occasioni=len(validi),
        coperte=len(fatti & set(validi)),
        ora=_ora_proposta(centro),
        giorni=giorni,
        nel_grappolo=dentro,
        segnate=len(in_giornata),
    )
    if candidato.concentrazione < MIN_CONCENTRAZIONE:
        return None
    return candidato


def cerca(
    *,
    segnate: Sequence[Segnata],
    impegni: Sequence[Impegno],
    da: date,
    a: date,
) -> list[Candidato]:
    """I candidati che reggono, dal più forte. **Uno per abitudine al massimo.**

    Uno solo perché due proposte sulla stessa cosa — «la creatina dopo la
    palestra» e «la creatina alle 19» — sono due modi di chiedere lo stesso
    promemoria, e mandarli insieme costringerebbe a scegliere fra due righe che
    dicono quasi la stessa frase. Vince il più forte; se lo scarti, la notte
    dopo l'altro non torna, perché `stessa_proposta` li riconosce entrambi
    dall'abitudine di cui parlano.
    """
    giornate = giorni_fra(da, a)
    per_abitudine: dict[str, list[Segnata]] = {}
    for segno in segnate:
        per_abitudine.setdefault(segno.abitudine, []).append(segno)

    trovati: list[Candidato] = []
    for abitudine, suoi in per_abitudine.items():
        fatti = {s.giorno for s in suoi}
        suoi_candidati = _su_impegno(abitudine, fatti, impegni, giornate)
        a_orario = _a_orario(abitudine, suoi, fatti, giornate)
        if a_orario is not None:
            suoi_candidati.append(a_orario)
        if suoi_candidati:
            trovati.append(max(suoi_candidati, key=lambda c: (c.forza, c.soggetto)))

    trovati.sort(key=lambda c: (-c.forza, c.soggetto))
    return trovati


# — la lettura dall'archivio —


def _segnate(conn: sqlite3.Connection, *, da: date, a: date) -> list[Segnata]:
    """I log delle abitudini **ancora attive**, con l'ora in cui li hai scritti.

    Solo le attive: una che hai disattivato è una cosa che hai smesso di fare, e
    proporre un promemoria per rimetterla in piedi sarebbe rispondere a una
    domanda che non hai fatto.

    Non passa da `abitudini.log_del_periodo` perché quella risponde a un'altra
    domanda — «quali giorni», che è ciò che serve all'aderenza — e qui serve
    anche `creato_il`, che è l'unico orologio che questo progetto abbia su
    un'abitudine.
    """
    righe = conn.execute(
        "SELECT h.nome AS nome, l.data AS data, l.creato_il AS creato_il"
        " FROM habit_logs l JOIN habits h ON h.id = l.habit_id"
        " WHERE l.fatto = 1 AND h.attivo = 1 AND l.data BETWEEN ? AND ?",
        (da.isoformat(), a.isoformat()),
    )
    return [
        Segnata(
            abitudine=riga["nome"],
            giorno=date.fromisoformat(riga["data"]),
            scritto_il=datetime.fromisoformat(riga["creato_il"]),
        )
        for riga in righe
    ]


def _impegni(conn: sqlite3.Connection, *, da: date, a: date) -> list[Impegno]:
    """Le giornate con un impegno di un tipo a cui una regola si possa agganciare.

    Tre esclusioni, e nessuna è cosmetica:
    - gli eventi **di giornata**, perché `regole.dovute()` li lascia fuori: un
      evento senza un'ora non ha un «prima», quindi una regola agganciata a un
      tipo che compare solo così non scatterebbe mai;
    - il tipo **`altro`**, che è il ripiego con cui nasce ogni evento appena
      sincronizzato: una regola agganciata a lui scatterebbe su tutto ciò che il
      tagging non ha ancora guardato;
    - i tipi **archiviati**, che hai tolto di mezzo tu e che non compaiono
      nemmeno nel menu di correzione.
    """
    righe = conn.execute(
        "SELECT DISTINCT date(e.inizio) AS giorno, e.tipo AS tipo"
        " FROM calendar_events e JOIN calendar_tags t ON t.slug = e.tipo"
        " WHERE e.tutto_il_giorno = 0 AND t.attivo = 1 AND e.tipo <> ?"
        " AND date(e.inizio) BETWEEN ? AND ?",
        (dom_calendario.SLUG_ALTRO, da.isoformat(), a.isoformat()),
    )
    return [Impegno(giorno=date.fromisoformat(r["giorno"]), tipo=r["tipo"]) for r in righe]


def finestra(oggi: date, *, settimane: int = SETTIMANE_DI_STORICO) -> tuple[date, date]:
    """I giorni da guardare: le ultime `settimane` fino a **ieri**.

    Ieri e non oggi: la giornata in corso è incompleta per costruzione — a
    mezzanotte e mezza, quando il job gira, non hai ancora segnato niente — e
    contarla abbasserebbe ogni copertura di una giornata mancata che non è
    mancata affatto.
    """
    ieri = oggi - timedelta(days=1)
    return ieri - timedelta(weeks=settimane) + timedelta(days=1), ieri


def candidati(
    conn: sqlite3.Connection, oggi: date, *, settimane: int = SETTIMANE_DI_STORICO
) -> list[Candidato]:
    """I pattern che reggono nello storico, dal più forte. Nessuna chiamata a nessuno."""
    da, a = finestra(oggi, settimane=settimane)
    return cerca(
        segnate=_segnate(conn, da=da, a=a),
        impegni=_impegni(conn, da=da, a=a),
        da=da,
        a=a,
    )
