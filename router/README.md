# router — scelta del modello DeepSeek / Claude

Decide quale modello serve per ogni tipo di compito, secondo la tabella di
ARCHITECTURE.md §6, e ci parla. Il principio di §1 è "massima resa, minima
spesa": i compiti banali e ad alto volume vanno a DeepSeek, quelli che
richiedono qualità, visione o ragionamento a Claude.

- `compiti.py` — **la tabella di §6 in codice**, con il motivo di ogni riga
  accanto alla scelta. Chi chiama nomina il *compito*, mai il modello: cambiare
  instradamento non richiede di toccare i moduli.
- `deepseek.py` — client httpx (l'API di DeepSeek è compatibile con quella di
  OpenAI, ma qui se ne usa una sola chiamata: non vale l'SDK di OpenAI).
- `claude.py` — client sull'SDK ufficiale `anthropic`, con structured outputs.
- `router.py` — mette insieme le due cose.
- `assistente.py` — dal testo libero all'azione: è ciò che rende utile tutto il
  resto (§8.1).
- `diario.py` — dal materiale grezzo di una giornata al riassunto proposto, e
  dalle voci approvate di una settimana al riepilogo (§8.4).
- `profilo.py` — la **rifusione**: Claude riscrive il profilo da capo fondendo
  il vecchio con i segnali nuovi (§8.4). Non è un accodamento, ed è il motivo
  per cui §6 la manda a Claude e non a DeepSeek.
- `spese.py` — la categoria di una spesa e la **lettura degli scontrini**
  (§8.5): l'unica riga *vision* di §6, e l'unica che manda un'immagine al
  modello. Da qui escono numeri e nomi, non righe di database.

Questo pacchetto dipende da `custode_core`, mai il contrario: il codice
condiviso non deve sapere che esistono dei modelli.

## Il modello non tocca il database

`assistente.py` chiede al modello solo un'**intenzione strutturata** (`azione`,
`titolo`, `riferimento`, …) e la traduce lui in chiamate ai servizi di dominio.
Un modello che sbaglia può quindi far fare a Custode una cosa sbagliata fra
quelle previste, mai una cosa non prevista. I riferimenti a task e voci
esistenti vengono risolti in codice, e un riferimento ambiguo non chiude nulla:
meglio non fare niente che indovinare.

Ogni azione dell'assistente lascia un bottone «Annulla», perché
l'interpretazione è automatica e tornare indietro deve costare un tap.

## Stato

Instradati e in uso, su DeepSeek: parsing della lista, CRUD dei task,
riconoscimento del materiale da diario e rilevazione dei segnali per il profilo
— tutti e quattro **nella stessa chiamata**, perché sono compiti diversi di §6
ma con lo stesso provider, e farne quattro giri costerebbe quattro volte tanto
su ogni messaggio — più l'estrazione di una spesa detta a parole. Su Claude:
riassunto del diario, riepilogo settimanale, rifusione del profilo, scelta della
categoria di una spesa e lettura degli scontrini. Gli altri compiti della
tabella hanno il provider già deciso e il client pronto, ma nessun modulo li
chiama ancora.

Perché la categoria di una spesa va a Claude e non a DeepSeek: **assegnare** una
spesa a una categoria che già esiste viaggia nella stessa chiamata che
interpreta il messaggio, e non costa niente in più; **crearne una nuova** è la
riga di §6 che chiede di «evitare categorie duplicate o incoerenti», e un
doppione creato oggi resta lì per sempre.

Quella divisione è applicata dal codice, non affidata al prompt: una categoria
che l'interprete propone ma che non esiste ancora viene **scartata**, e la
decisione passa a Claude. Lo schema chiede già di copiare dall'elenco e di non
inventare, ma la descrizione di uno schema è una richiesta — «150 euro da
Bricoman» diventava una categoria «Bricoman», e il prompt di Claude che
l'avrebbe evitata non girava nemmeno.

Nota sul tetto dei token: DeepSeek e Claude ne hanno due distinti
(`max_token_risposta` e `max_token_risposta_claude`). Su `claude-opus-5` il
ragionamento adattivo è attivo di default e i suoi token rientrano in
`max_tokens`: col tetto basso che basta a DeepSeek, la risposta arriverebbe
troncata invece che in JSON.

La lettura degli scontrini passa da `chiedi_json_con_immagine`, non da
`chiedi_json`: sono due strade separate apposta, e chiedere un compito con
immagini per la strada sbagliata (o viceversa) solleva `CompitoNonSupportato`
invece di mandare al modello una domanda senza la cosa da guardare.

§6 dice anche cosa **non** passa di qui: valutare una regola di contesto già
approvata è logica pura, costo zero, e va tenuta così.

## Chiavi

`ROUTER_DEEPSEEK_API_KEY` e `ROUTER_ANTHROPIC_API_KEY` nel `.env` (vedi
`.env.example`). Senza DeepSeek si perde il linguaggio libero; senza Anthropic
si perde il riassunto del diario. In entrambi i casi comandi e bottoni
continuano a funzionare, il bot dice cosa manca invece di fallire in silenzio, e
**il materiale già raccolto resta sul disco**: un guasto del modello non deve
costare quello che hai già raccontato.
