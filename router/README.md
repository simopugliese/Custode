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
su ogni messaggio. Su Claude: riassunto del diario, riepilogo settimanale e
rifusione del profilo. Gli altri compiti della tabella hanno il provider già
deciso e il client pronto, ma nessun modulo li chiama ancora.

Nota sul tetto dei token: DeepSeek e Claude ne hanno due distinti
(`max_token_risposta` e `max_token_risposta_claude`). Su `claude-opus-5` il
ragionamento adattivo è attivo di default e i suoi token rientrano in
`max_tokens`: col tetto basso che basta a DeepSeek, la risposta arriverebbe
troncata invece che in JSON.

L'unica riga di §6 non implementata è **la lettura degli scontrini**, che ha
bisogno di mandare un'immagine al modello: chiederla ora solleva
`CompitoNonSupportato`, e arriverà col modulo spese (§8.5).

§6 dice anche cosa **non** passa di qui: valutare una regola di contesto già
approvata è logica pura, costo zero, e va tenuta così.

## Chiavi

`ROUTER_DEEPSEEK_API_KEY` e `ROUTER_ANTHROPIC_API_KEY` nel `.env` (vedi
`.env.example`). Senza DeepSeek si perde il linguaggio libero; senza Anthropic
si perde il riassunto del diario. In entrambi i casi comandi e bottoni
continuano a funzionare, il bot dice cosa manca invece di fallire in silenzio, e
**il materiale già raccolto resta sul disco**: un guasto del modello non deve
costare quello che hai già raccontato.
