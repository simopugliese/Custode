"""Job schedulati di Custode (ARCHITECTURE.md §5).

Il worker non decide niente da solo: si sveglia ogni pochi minuti, chiede a una
funzione pura *cosa è dovuto adesso*, e chiama il job corrispondente. Tutta la
logica di "quando" sta in `pianificazione.py` e si prova senza aspettare.

**Dipendenze.** Questo pacchetto importa `custode_bot.risposte` per comporre i
messaggi che manda su Telegram: quel modulo è fatto di funzioni pure e non sa
cosa sia `python-telegram-bot` (lo dice il suo docstring), quindi il worker non
si porta dietro la libreria del bot. È un'invariante da non rompere: se un
giorno `risposte.py` importasse `telegram`, questo import andrebbe spezzato.
"""
