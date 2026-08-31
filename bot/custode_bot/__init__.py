"""Bot Telegram di Custode (ARCHITECTURE.md §8.1).

Il canale principale: da qui si fanno le stesse cose della dashboard, usando
gli stessi servizi di dominio in `custode_core.dominio` — nessuna logica
duplicata fra i due canali.

Le risposte sono costruite da funzioni pure in `risposte.py`; `applicazione.py`
è solo l'adattatore verso `python-telegram-bot`.
"""
