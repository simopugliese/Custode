# bot — interfaccia Telegram

Il canale principale di Custode (ARCHITECTURE.md §8.1): stesso comportamento
via testo o vocale, con l'audio che passa da Whisper locale e poi imbocca la
stessa pipeline del testo.

## Stato

Vuota. Arriva alla fase 3 del piano di lavoro, dopo API + DB reali, così il bot
può appoggiarsi ai servizi di dominio in `core/` invece di riscriverli.

Quando esisterà: `python-telegram-bot` (§4), whitelist sul solo user ID
Telegram autorizzato e ogni altro mittente ignorato (§9), collegamento ai
moduli task e lista della spesa (§8.2, §8.3).
