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

FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"

NASCOSTO = "<nascosto>"

# I segreti del progetto, nella forma in cui si vedono in un log. Ognuno ha un
# prefisso riconoscibile: si cerca quello e non «una stringa lunga a caso»,
# perché un filtro troppo largo cancellerebbe anche gli id degli eventi di
# Google e i percorsi dei file, rendendo i log inutili invece che sicuri.
SEGRETI: tuple[re.Pattern[str], ...] = (
    # Token di un bot Telegram: `1234567890:AAF...`. Il lookbehind rifiuta solo
    # una cifra o un due punti — non una lettera — perché il posto in cui il
    # token si vede davvero è **dentro l'URL**, attaccato a «bot»:
    # `/bot1234567890:AAF.../getUpdates`. Rifiutare qualunque carattere di
    # parola lascerebbe passare proprio quello.
    re.compile(r"(?<![\d:])\d{6,12}:[A-Za-z0-9_-]{30,}"),
    # Chiavi API in stile OpenAI/DeepSeek/Anthropic: `sk-...`, `sk-ant-...`.
    re.compile(r"(?<![\w-])sk-[A-Za-z0-9_-]{16,}"),
    # Refresh token di Google (`1//0g...`) e client secret (`GOCSPX-...`).
    re.compile(r"(?<![\w-])1//[A-Za-z0-9_-]{20,}"),
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
    """Il formattatore normale, con i segreti nascosti dopo la formattazione.

    Dopo, non prima: a quel punto messaggio, argomenti ed eventuale traceback
    sono già una stringa sola, e non c'è modo che uno dei tre scappi.
    """

    def format(self, record: logging.LogRecord) -> str:
        return nascondi_segreti(super().format(record))


def configura(livello: str, *, formato: str = FORMATO) -> None:
    """Prepara i log del processo: livello, formato, e niente segreti.

    Da chiamare al posto di `logging.basicConfig` in ogni punto d'ingresso.
    Se qualcuno ha già configurato dei gestori — succede sotto `uvicorn` —
    `basicConfig` non li tocca, ma il formattatore va messo lo stesso: è quello
    che nasconde i segreti, e saltarlo lascerebbe scoperto proprio il caso in
    cui il processo gira in produzione.
    """
    logging.basicConfig(level=livello.upper(), format=formato)
    for gestore in logging.getLogger().handlers:
        gestore.setFormatter(FormattatoreSenzaSegreti(formato))
