# worker — job schedulati

I lavori che girano da soli (ARCHITECTURE.md §5): controllo scadenze task e
promemoria su Telegram (§8.2), riepilogo settimanale del diario con rifusione
del `profile_document` (§8.4), digest mattutino (§8.13), valutazione delle
regole di contesto approvate (§8.10), backup cifrato del DB (§9).

- `config.py` — quando far girare le cose (prefisso `WORKER_`).
- `pianificazione.py` — **quando** un job è dovuto, come logica pura: prende
  `adesso` come parametro, quindi si prova senza aspettare domenica sera. Qui
  sta anche il registro `job_runs` di cosa è già stato fatto.
- `settimanale.py` — il job di §8.4 punto 7: legge le voci di diario approvate
  della settimana, ne fa scrivere il riepilogo a Claude, e prepara il messaggio
  con la revisione dei candidati per il profilo.
- `telegram.py` — mandare un messaggio, una chiamata HTTP e basta.
- `main.py` — il ciclo: sveglia, «cosa è dovuto?», dormi.

## Niente libreria di scheduling

Il worker si sveglia ogni `WORKER_INTERVALLO_SECONDI` (cinque minuti) e chiede a
`pianificazione` cosa tocca. Il vantaggio non è risparmiare una dipendenza su
arm64: è che l'unica cosa che può sbagliare — *quando* — diventa una funzione
pura che si esercita in un millesimo di secondo.

Due comportamenti che ne derivano e che valgono per ogni job futuro:

- **Recupero.** Se il Pi era spento all'ora prevista, il job parte appena torna
  su, invece di saltare la settimana. Si guarda indietro al massimo di due
  settimane: dopo un'assenza lunga ha senso riprendere dall'ultima, non
  rovesciare addosso quattro revisioni insieme.
- **Registro.** `job_runs` segna cosa è stato fatto per quale periodo, anche
  quando il job non ha prodotto niente. Senza, una settimana senza voci
  approvate — che non scrive nessuna riga da nessuna parte — farebbe ripartire
  il job ad ogni giro per sempre.

## Perché non usa `python-telegram-bot`

Il worker deve solo **spedire**: i tap sui bottoni li riceve il bot, che è già
in long polling. Per una chiamata HTTP non vale la pena mettere la libreria del
bot anche in questa immagine.

Compone però i messaggi con `custode_bot.risposte`, che è fatto di funzioni pure
e non sa cosa sia Telegram. È un'invariante da non rompere: se un giorno
`risposte.py` importasse `telegram`, questo import andrebbe spezzato — e i
`callback_data` continuerebbero comunque a passare da `custode_bot.azioni`, che
esiste apposta perché non vengano scritti a mano in due punti diversi.

## Stato

Fatto: il **riepilogo settimanale del diario** (§8.4 punto 7), con la revisione
dei candidati per il profilo e la rifusione che ne segue.

Da fare, ognuno insieme al modulo che serve: controllo delle scadenze dei task
(§8.2), digest mattutino (§8.13), valutazione delle regole di contesto approvate
(§8.10), backup cifrato del DB (§9) — con il runbook di restore che §11 chiede.

## Provarlo

```bash
uv run python -m custode_worker.main    # servono TELEGRAM_* e WORKER_* nel .env
```

Il ciclo dice all'avvio quando farà scattare il riepilogo. Per esercitare il job
senza aspettare, i test lo chiamano direttamente:

```bash
uv run pytest tests/integration/test_worker_settimanale.py tests/unit/test_worker_pianificazione.py
```
