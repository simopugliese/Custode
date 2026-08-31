"""Avvio del bot: `python -m custode_bot.main`.

Non parte senza token e senza user ID autorizzato — un bot con la whitelist
vuota che si mette comunque in ascolto sarebbe la peggiore delle
configurazioni possibili (§9).
"""

from __future__ import annotations

import logging
import sys

from custode_bot.applicazione import crea_applicazione
from custode_bot.config import ImpostazioniBot, get_impostazioni_bot
from custode_core.config import Settings, get_settings

log = logging.getLogger("custode.bot")


def _mancanti(bot: ImpostazioniBot) -> list[str]:
    fuori: list[str] = []
    if not bot.bot_token:
        fuori.append("TELEGRAM_BOT_TOKEN")
    if bot.allowed_user_id <= 0:
        fuori.append("TELEGRAM_ALLOWED_USER_ID")
    return fuori


def main(settings: Settings | None = None, bot: ImpostazioniBot | None = None) -> int:
    impostazioni = settings or get_settings()
    impostazioni_bot = bot or get_impostazioni_bot()
    logging.basicConfig(
        level=impostazioni.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    mancanti = _mancanti(impostazioni_bot)
    if mancanti:
        log.error("il bot non parte: manca %s nel .env (vedi .env.example)", " e ".join(mancanti))
        return 1

    log.info(
        "bot avviato in long polling, unico mittente ammesso: %s",
        impostazioni_bot.allowed_user_id,
    )
    applicazione = crea_applicazione(impostazioni, impostazioni_bot)
    applicazione.run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
