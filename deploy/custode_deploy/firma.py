"""La firma delle richieste che la CI manda al Pi.

Cloudflare Access ferma chi non ha il service token, ma il token viaggia in due
header e basta: chi lo rubasse potrebbe far partire un deploy. La firma è il
secondo strato, con un segreto che non passa da Cloudflare.

Copre metodo, percorso e corpo oltre al timestamp: una firma di un `GET` non
vale per un `POST`, e una richiesta vecchia non si può rimandare.
"""

from __future__ import annotations

import hashlib
import hmac

# Quanto può distare l'orologio della CI da quello del Pi. Cinque minuti coprono
# la deriva di un Pi senza NTP recente e restano pochi per un replay.
TOLLERANZA_SECONDI = 300


def firma(segreto: str, timestamp: int, metodo: str, percorso: str, corpo: bytes) -> str:
    """HMAC-SHA256 di `timestamp\\nMETODO\\npercorso\\ncorpo`, in esadecimale.

    Il workflow GitHub la calcola con `printf` e `openssl` sullo stesso
    messaggio: se cambi il formato, cambia anche `.github/workflows/ci.yml`.
    """
    messaggio = b"\n".join(
        [str(timestamp).encode(), metodo.upper().encode(), percorso.encode(), corpo]
    )
    return hmac.new(segreto.encode(), messaggio, hashlib.sha256).hexdigest()


def verifica(
    segreto: str,
    timestamp: str | None,
    firma_ricevuta: str | None,
    metodo: str,
    percorso: str,
    corpo: bytes,
    adesso: float,
) -> bool:
    """Vero solo se la firma torna **e** la richiesta è recente."""
    if not segreto or not timestamp or not firma_ricevuta:
        return False
    try:
        quando = int(timestamp)
    except ValueError:
        return False
    if abs(adesso - quando) > TOLLERANZA_SECONDI:
        return False
    atteso = firma(segreto, quando, metodo, percorso, corpo)
    return hmac.compare_digest(atteso, firma_ricevuta)
