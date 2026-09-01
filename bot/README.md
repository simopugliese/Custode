# bot — interfaccia Telegram

Il canale principale di Custode (ARCHITECTURE.md §8.1). Parla direttamente al
database attraverso gli stessi servizi di dominio che usa l'API
(`custode_core.dominio`): nessuna regola duplicata fra i due canali.

- `config.py` — token e whitelist, da variabili `TELEGRAM_*`.
- `azioni.py` — codifica dei `callback_data` dei bottoni inline.
- `risposte.py` — **cosa** dice il bot, come funzioni pure: niente qui sa cosa
  sia python-telegram-bot, ed è il livello che i test esercitano davvero.
- `applicazione.py` — l'adattatore verso python-telegram-bot: handler, filtri,
  invio dei messaggi.
- `main.py` — avvio.

## Sicurezza

Whitelist su un solo user ID Telegram (§9): ogni altro mittente viene ignorato
**senza risposta** — a uno sconosciuto non si conferma nemmeno che il bot
esista. La whitelist copre comandi, testo libero e tap sui bottoni: i bottoni
vanno controllati a mano, perché `CallbackQueryHandler` non accetta un filtro
sul mittente come gli altri handler.

Il default `TELEGRAM_ALLOWED_USER_ID=0` significa "nessuno", mai "chiunque", e
senza token o senza user ID il bot si rifiuta di partire.

Il bot lavora in **long polling**: è lui a chiamare Telegram, quindi non serve
nessuna porta in ingresso né un tunnel già configurato (§2, §9).

## Cosa capisce

| Comando | Cosa fa |
|---|---|
| `/oggi` | Task scaduti, in scadenza oggi, e quanto manca sulla lista |
| `/task` | I task aperti, con un bottone per spuntarli e uno per rinviarli |
| `/nuovo <titolo>` | Crea un task, poi chiede la scadenza con dei bottoni |
| `/lista` | La lista della spesa per reparto, spuntabile |
| `/aggiungi <voce>` | Aggiunge alla lista della spesa |
| `/svuota` | Toglie le voci già prese, previa conferma |
| `/diario` | Chiude la giornata e propone il riassunto da approvare |
| `/aiuto` | L'elenco qui sopra |

Oltre ai comandi il bot capisce il **linguaggio libero**, scritto o dettato:
«ricordami di chiamare l'officina», «sto finendo il latte», «fatto la
bolletta». Il messaggio passa dal router (§6), che ne ricava un'intenzione
strutturata; il bot esegue subito e dice cosa ha fatto, lasciando un bottone
«Annulla» — l'interpretazione è automatica, quindi disfare deve costare un tap.

I **vocali** seguono esattamente lo stesso percorso: whisper.cpp locale li
trascrive e da lì in poi non c'è differenza col testo (§8.1). Il bot rimanda
anche la trascrizione, così se qualcosa esce storto si vede subito se la colpa
è di Whisper o dell'interpretazione.

## Il diario (§8.4)

Non c'è un momento in cui «si scrive il diario»: quello che racconti durante il
giorno — «capitolo 3 finalmente chiaro», «che palle il frontend» — il router lo
riconosce come materiale da diario e lo mette da parte sulla **giornata di
oggi**, grezzo, con un bottone «Annulla» che toglie esattamente quella frase.

`/diario` chiude la giornata: il materiale va a **Claude** (§6), che ne scrive
un riassunto e dei tag, e il bot te lo rimanda con tre uscite.

- **Approva** — entra nel diario così com'è.
- **Modifica** — il bot chiede il testo corretto, e il messaggio successivo
  (scritto o dettato) diventa la voce **parola per parola**, senza passare da
  nessun modello: ciò che resta scritto è tuo.
- **Scarta** — butta via tutto, materiale grezzo compreso.

Finché non approvi, nel diario non c'è niente. Un secondo `/diario` non
richiama Claude: la bozza c'è già, e rigenerarla sarebbe spesa buttata (§1). Se
Claude non è raggiungibile o la chiave manca, il bot lo dice e **il materiale
resta sul disco**: si riprova più tardi senza aver perso niente.

Lo stato «sto aspettando la tua riscrittura» sta sul database, non nella memoria
del processo: se il bot riparte a metà, la conversazione riprende da dov'era
invece di scambiare la riscrittura per una frase qualsiasi.

Le scadenze del comando `/nuovo` si scelgono con dei bottoni (oggi / domani /
fra una settimana / senza scadenza) invece di essere lette da una frase: quattro
bottoni si premono più in fretta di quanto si scriva una data. In linguaggio
libero la scadenza la ricava il modello.

## Provarlo

```bash
# nel .env: TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID
uv run python -m custode_bot.main
```

I test non hanno bisogno di un token: `tests/integration/test_bot_end_to_end.py`
fa passare aggiornamenti veri attraverso l'applicazione con un bot finto al
posto della rete.
