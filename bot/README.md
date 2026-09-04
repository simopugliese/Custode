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
| `/spese` | Quanto hai speso questo mese, per categoria |
| `/profilo` | Cosa Custode ha capito di te, e quanti segnali sono in attesa |
| `/abitudini` | Come stai andando questa settimana, con un tap per segnare oggi |
| `/aiuto` | L'elenco qui sopra |

Oltre ai comandi il bot capisce il **linguaggio libero**, scritto o dettato:
«ricordami di chiamare l'officina», «sto finendo il latte», «fatto la
bolletta», «oggi palestra e lettura, ma niente meditazione». Il messaggio passa
dal router (§6), che ne ricava un'intenzione
strutturata; il bot esegue subito e dice cosa ha fatto, lasciando un bottone
«Annulla» — l'interpretazione è automatica, quindi disfare deve costare un tap.

I **vocali** seguono esattamente lo stesso percorso: whisper.cpp locale li
trascrive e da lì in poi non c'è differenza col testo (§8.1). Il bot rimanda
anche la trascrizione, così se qualcosa esce storto si vede subito se la colpa
è di Whisper o dell'interpretazione.

Una **foto** è uno scontrino: vedi §8.5 qui sotto.

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

## Le spese (§8.5)

Due strade, che finiscono nello stesso posto.

- **A parole** — «ho pagato 8€ la colazione da Bar Rossi» entra **subito** nei
  conti, con un bottone «Annulla» come tutto il resto. Chiedere conferma venti
  volte al giorno è il modo più sicuro di smettere di registrare le spese
  piccole.
- **Una foto dello scontrino** — la legge Claude (§6), che ne estrae totale,
  luogo, data e voci. La sintesi arriva con **Conferma** e **Scarta**, e
  **finché non confermi resta fuori dai totali**: lì il modello legge dieci
  numeri da un'immagine, e sbagliarne uno è facile in un modo in cui non lo è
  leggere una frase. La foto non viene conservata: restano il totale e le voci
  lette.

La categoria la propone Claude confrontandola con quelle che già usi, così non
nascono «Cibo» accanto ad «Alimentari» — e il nome del negozio non diventa mai
una categoria: da Bricoman compri vernice, che è «Casa». È una chiamata a parte, fatta **dopo**
aver salvato la spesa: se il modello non risponde, la spesa resta lì senza
categoria invece di andare persa, e si sistema dalla dashboard.

Uno scontrino letto e mai confermato non si perde nella cronologia della chat:
`/spese` lo ripropone coi suoi due bottoni. E una spesa che risulta di un altro
giorno — uno scontrino di fine mese scorso fotografato oggi — non sparisce dai
totali in silenzio: la conferma dice a che giorno è finita, e `/spese` elenca a
parte quello che hai registrato ma che è datato fuori dal mese.

## Il profilo (§8.4)

Oltre al diario, ogni messaggio passa da un controllo leggero: c'è qui dentro
qualcosa che descrive **come sei fatto** e che tornerà utile fra mesi? Viaggia
nella stessa risposta del modello che interpreta il messaggio, quindi non costa
una chiamata in più.

- Segnale **chiaro** → messo da parte in silenzio, nessuna interruzione.
- Segnale **ambiguo** (uno sfogo o una preferenza vera?) → il bot te lo chiede,
  attaccando la domanda alla risposta che stava già dando, con due bottoni. Una
  domanda alla volta: se ce n'è già una in sospeso, il segnale nuovo aspetta la
  revisione invece di aprirne una seconda.

Una volta a settimana il worker (§5) manda il riepilogo dei giorni scritti e
l'elenco dei segnali raccolti. Si lavora **per sottrazione**: butti quelli che
non ti rappresentano, poi «Aggiorna il profilo» e Claude lo riscrive da capo
fondendolo col vecchio. La nuova versione arriva con l'elenco di cosa è
cambiato e un bottone «Torna alla precedente» — e tornando indietro i segnali
non si perdono, rientrano nella rifusione successiva.

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

## Abitudini (§8.6)

Il bot le **segna**, non le crea: «oggi palestra e lettura, ma niente
meditazione» aggancia i nomi all'elenco di quelle che segui e scrive tre log in
un colpo, con un «Annulla» che li toglie tutti e tre — quella frase è stato un
gesto solo. Un nome che non è nell'elenco viene detto («non seguo
«Chitarra»»), mai creato: aprire un'abitudine è una decisione, e si prende
dalla pagina Abitudini della dashboard.

`/abitudini` mostra l'aderenza della settimana con gli stessi numeri della
dashboard — §8.6 la vuole in tutti e due i posti, e due conti diversi che
dicono due numeri diversi sono peggio di uno solo. Il tap su un'abitudine già
segnata **toglie** il log invece di scrivere «non fatta»: un tap per sbaglio
deve riportare al silenzio, non affermare il contrario.
