"""Configurazione dei log, uguale per tutti i servizi — e senza segreti dentro.

**Perché esiste questo modulo.** L'API di Telegram mette il token del bot
*nell'URL* (`api.telegram.org/bot<token>/getUpdates`), e `httpx` registra a
livello INFO l'URL di ogni richiesta. Il risultato è che il token compariva in
ogni riga di `docker compose logs bot` — cioè nel primo posto da cui si
copia-incolla quando qualcosa non va, e da lì in una chat o in un issue. È
successo davvero.

La difesa non è abbassare il livello di httpx: quelle righe servono a capire se
il bot sta parlando con Telegram o no, ed è esattamente quando qualcosa non va
che si vogliono leggere. Si nasconde il **segreto**, non la riga.

Il filtro sta nel *formattatore* e non in un `logging.Filter` apposta: così
passa di lì tutto ciò che finisce nel log — il messaggio, i suoi argomenti e
anche il testo di un traceback, che è il posto meno sorvegliato di tutti e
quello in cui un URL con dentro un token ci finisce da solo.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator

FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"

NASCOSTO = "<nascosto>"

# I segreti del progetto, nella forma in cui si vedono in un log. Ognuno ha un
# prefisso riconoscibile: si cerca quello e non «una stringa lunga a caso»,
# perché un filtro troppo largo cancellerebbe anche gli id degli eventi di
# Google e i percorsi dei file, rendendo i log inutili invece che sicuri.
# Un URL in un log arriva in due forme, e i separatori cambiano: `httpx`
# stampa l'URL com'è (`/bot123:AAF.../getUpdates`), mentre l'access log di
# uvicorn riporta il *request target* grezzo, che è percent-encoded
# (`/bot123%3AAAF.../getUpdates`). Cercare solo i due punti veri lascerebbe
# passare la seconda — ed è quella del processo esposto alla rete.
DUE_PUNTI = r"(?::|%3[Aa])"
BARRA = r"(?:/|%2[Ff])"

SEGRETI: tuple[re.Pattern[str], ...] = (
    # Token di un bot Telegram: `1234567890:AAF...`. Il lookbehind rifiuta solo
    # una cifra o un due punti — non una lettera — perché il posto in cui il
    # token si vede davvero è **dentro l'URL**, attaccato a «bot»:
    # `/bot1234567890:AAF.../getUpdates`. Rifiutare qualunque carattere di
    # parola lascerebbe passare proprio quello.
    re.compile(rf"(?<![\d:])\d{{6,12}}{DUE_PUNTI}[A-Za-z0-9_-]{{30,}}"),
    # Chiavi API in stile OpenAI/DeepSeek/Anthropic: `sk-...`, `sk-ant-...`.
    re.compile(r"(?<![\w-])sk-[A-Za-z0-9_-]{16,}"),
    # Refresh token di Google (`1//0g...`) e client secret (`GOCSPX-...`).
    re.compile(rf"(?<![\w-])1{BARRA}{BARRA}[A-Za-z0-9_-]{{20,}}"),
    re.compile(r"(?<![\w-])GOCSPX-[A-Za-z0-9_-]{10,}"),
)


def nascondi_segreti(testo: str) -> str:
    """Sostituisce i segreti riconoscibili, lasciando intatto il resto.

    Funzione pura, ed è il punto: la si prova senza far girare nessun logger,
    che è l'unico modo di essere sicuri che copra le forme giuste prima che un
    token vero passi di qui.
    """
    for segreto in SEGRETI:
        testo = segreto.sub(NASCOSTO, testo)
    return testo


class FormattatoreSenzaSegreti(logging.Formatter):
    """Avvolge un altro formattatore e nasconde i segreti da ciò che produce.

    Dopo la formattazione, non prima: a quel punto messaggio, argomenti ed
    eventuale traceback sono già una stringa sola, e non c'è modo che uno dei
    tre scappi.

    **Avvolge invece di sostituire** perché non tutti i formattatori del
    processo sono nostri. Quello dell'access log di `uvicorn` è una classe sua
    che sa di `%(client_addr)s`, `%(request_line)s` e del colore del livello:
    rimpiazzarlo con il formato di Custode nasconderebbe i segreti buttando via
    la riga: resterebbe un access log senza dentro l'accesso.
    """

    def __init__(self, dentro: logging.Formatter | None = None) -> None:
        # Nessun `super().__init__`: di `logging.Formatter` qui non serve
        # niente se non l'interfaccia — tutto il lavoro lo fa quello dentro.
        self._dentro = dentro if dentro is not None else logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return nascondi_segreti(self._dentro.format(record))


def _gestori_del_processo() -> Iterator[logging.Handler]:
    """Ogni gestore già installato, non solo quelli della radice.

    Sotto `uvicorn` i log del server **non passano dalla radice**: `uvicorn`,
    `uvicorn.error` e `uvicorn.access` hanno gestori propri e `propagate=False`,
    che è proprio il meccanismo con cui un logger dice «di me mi occupo io».
    Un formattatore messo solo sulla radice li lascerebbe quindi fuori, e sono
    le righe di un processo esposto alla rete — il posto in cui un URL con
    dentro un segreto finisce senza che nessuno l'abbia scritto apposta.

    `uvicorn` configura i suoi prima di importare l'app (`Config.__init__`
    chiama `configure_logging()`, `Config.load()` importa l'app dopo), quindi
    quando `crea_app` arriva qui li trova già montati.
    """
    yield from logging.getLogger().handlers
    for logger in list(logging.root.manager.loggerDict.values()):
        # `loggerDict` contiene anche dei `PlaceHolder`, che sono i buchi
        # nell'albero dei nomi e non hanno gestori.
        if isinstance(logger, logging.Logger):
            yield from logger.handlers


def configura(livello: str, *, formato: str = FORMATO) -> None:
    """Prepara i log del processo: livello, formato, e niente segreti.

    Da chiamare al posto di `logging.basicConfig` in ogni punto d'ingresso.
    Se qualcuno ha già configurato dei gestori — succede sotto `uvicorn` —
    `basicConfig` non li tocca, ma il formattatore va messo lo stesso: è quello
    che nasconde i segreti, e saltarlo lascerebbe scoperto proprio il caso in
    cui il processo gira in produzione.
    """
    logging.basicConfig(level=livello.upper(), format=formato)

    radice = logging.getLogger().handlers
    for gestore in _gestori_del_processo():
        if isinstance(gestore.formatter, FormattatoreSenzaSegreti):
            # Già avvolto: `crea_app` si chiama più volte nei test, e avvolgere
            # due volte funzionerebbe ma metterebbe uno strato ad ogni giro.
            continue
        # Sulla radice il formato è il nostro; altrove si tiene quello che il
        # gestore ha già — vedi `FormattatoreSenzaSegreti`.
        dentro = logging.Formatter(formato) if gestore in radice else gestore.formatter
        gestore.setFormatter(FormattatoreSenzaSegreti(dentro))
