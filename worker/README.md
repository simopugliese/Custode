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
- `backup.py` — il backup giornaliero del database e il suo ripristino (§9).
- `ripristino.py` — il comando del runbook: `python -m custode_worker.ripristino`.
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

## Il backup (§9)

Ogni notte: copia coerente con l'API `.backup()` di SQLite — che **non ferma
nessun servizio**, mentre un `cp` in modalità WAL potrebbe cogliere il database
a metà transazione — poi gzip, poi cifratura se c'è una chiave, poi pulizia con
retention 7 giornalieri + 4 settimanali.

`da_tenere()` è una funzione pura e ha i suoi test: è l'unica parte del sistema
che, sbagliata, **cancella** invece di non fare. Un backup con data futura non
si tocca mai — è un orologio storto, non un file da buttare.

Senza `WORKER_BACKUP_CHIAVE` il backup si fa lo stesso, in chiaro: il rischio
più probabile in casa è la scheda che si rompe, e da quello protegge anche una
copia non cifrata. Perché non diventi una falsa sicurezza, l'estensione cambia
(`.db.gz` invece di `.db.gz.enc`) e il worker lo ripete ad ogni avvio.

Un backup riuscito non manda notifiche — se ne arrivasse una ogni giorno
smetterebbe di voler dire qualcosa; uno fallito va nei log e non si segna come
fatto, quindi al giro dopo si riprova.

Il ripristino è un comando, non un one-liner da incollare:

```bash
python -m custode_worker.ripristino --elenco
python -m custode_worker.ripristino /backup/custode-2026-09-06.db.gz.enc /data/ripristinato.db
```

Non tocca mai il database in esercizio e verifica l'integrità di ciò che
scrive. Il runbook completo è in [DEPLOY.md §7](../DEPLOY.md).

## Stato

Fatti: il **riepilogo settimanale del diario** (§8.4 punto 7), con la revisione
dei candidati per il profilo e la rifusione che ne segue, e il **backup
giornaliero** del database (§9).

Da fare, ognuno insieme al modulo che serve: controllo delle scadenze dei task
(§8.2), digest mattutino (§8.13), valutazione delle regole di contesto approvate
(§8.10).

## Provarlo

```bash
uv run python -m custode_worker.main    # servono TELEGRAM_* e WORKER_* nel .env
```

Il ciclo dice all'avvio quando farà scattare il riepilogo. Per esercitare il job
senza aspettare, i test lo chiamano direttamente:

```bash
uv run pytest tests/integration/test_worker_settimanale.py tests/unit/test_worker_pianificazione.py
```
