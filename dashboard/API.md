# API di Custode — contratto per la dashboard

Questo documento descrive gli endpoint REST che il backend (FastAPI, vedi
`../ARCHITECTURE.md`) deve esporre perché la dashboard in
`dashboard/` funzioni. La dashboard non contiene dati finti: ogni pagina
chiama questi endpoint e mostra uno stato di caricamento/errore/vuoto finché
non rispondono con dati reali.

## Convenzioni

- **Base URL**: valore di `VITE_API_BASE_URL` (vedi `.env.example`), es.
  `https://api.custode.tuodominio.it`. Tutti gli endpoint sotto sono
  prefissati con `/api`.
- **Autenticazione**: nessuna gestita dal frontend. Cloudflare Access
  autentica la richiesta prima che raggiunga il tunnel/l'API (vedi §2 e §9
  del documento di progettazione); l'API può fidarsi dell'header/JWT che
  Access inietta, se vuole verificarlo lato server.
- **Formato**: JSON, nessun involucro (`{ data: ... }`); ogni `GET` di
  pagina restituisce direttamente l'oggetto della pagina. Le mutazioni
  restituiscono la risorsa aggiornata (o `204 No Content`).
- **Errori**: status HTTP non 2xx con corpo `{ "detail": "messaggio" }`
  (compatibile con FastAPI di default). In particolare **`501`** significa "il
  modulo dietro a questo endpoint non esiste ancora", col nome del modulo nel
  `detail`: la dashboard mostra il suo stato d'errore con scritto il motivo.
- **Campi assenti vs vuoti**: un campo opzionale il cui modulo non è ancora
  attivo viene **omesso** dalla risposta, non messo a zero o a lista vuota — la
  pagina non disegna quel blocco. Una lista *vuota* significa invece "il modulo
  c'è e non ha niente da dire" (es. la lista della spesa davvero vuota). Uno
  zero è un dato; l'assenza no.
- **Etichette**: tutte le stringhe `…Label` le compone il backend, in italiano
  e nel fuso di `CUSTODE_TIMEZONE` (es. `scadenzaLabel`: `"18:00"` per oggi,
  `"domani"`, `"giovedì"` entro la settimana, `"26 ago"` oltre). La stessa
  logica serve al bot Telegram, quindi vive una volta sola nel backend.
- **Le voci "piano di ripasso" sono task**: come da §8.11 del documento di
  progettazione, i task generati da un piano di ripasso sono normali righe
  di `tasks` collegate al corso — stesso endpoint `PATCH /api/task/:id`
  usato ovunque, nessun endpoint dedicato.

I tipi TypeScript esatti di ogni payload sono in `src/types/api.ts` — questo
file ne descrive solo la forma a endpoint per endpoint.

## Stato di implementazione

Attivi con dati reali su SQLite: **Home**, **Task**, **Lista della spesa**,
**Diario**, **Spese** e la barra **«A Custode»**. Tutti gli altri endpoint qui sotto
rispondono `501` finché non arriva il loro modulo — vedi la roadmap in
`../ARCHITECTURE.md` §12.

C'è inoltre `GET /api/health`, non consumato dalla dashboard: serve allo smoke
test post-deploy (§10) e risponde `503` se il database non è raggiungibile.

## Home

`GET /api/home` → `HomeData`
Riepilogo "di oggi": task, calendario, abitudini, spese della settimana,
lista della spesa, conteggio automazioni proposte.

`stats.spesaSettimana` è il totale confermato da lunedì a oggi, e c'è sempre
(anche a zero: il modulo esiste, quindi lo zero è un dato). Il blocco
`speseSettimana` invece compare **solo** se è impostato
`CUSTODE_BUDGET_SETTIMANALE`: la sua barra si riempie rispetto al budget, e
senza un tetto non ci sarebbe niente rispetto a cui riempirla. `scontriniInAttesa`
conta le foto lette che aspettano una conferma, che non sono ancora in `speso`.

## Diario

`GET /api/diario?vista=timeline|settimane|mesi` → `DiarioData`
`POST /api/diario/:id/approva` → `VoceDiario`
`POST /api/diario/:id/scarta` → `204`
(la modifica testo di una voce non ha endpoint dedicato in questa v1 della
dashboard: il pulsante "Modifica" apre un'interazione da rifinire più avanti.
Da Telegram la riscrittura invece c'è, ed è il «modifichi» di §8.4 punto 5)

Una voce è una **giornata** (§8.4): tutto quello che racconti in un giorno
confluisce sulla stessa voce, e `fonteLabel` dice di cosa è fatta — «da 3
vocali e 11 messaggi». Gli `id` delle voci vere sono numerici come stringa;
quelli sintetici hanno un prefisso (`assente-2026-09-01`, `periodo-2026-08-31`)
e non sono indirizzabili dalle mutazioni.

- `vista=timeline` → una riga per giorno del **mese corrente**, dalla più
  recente. I giorni senza voce compaiono con `stato: "assente"`, ma solo
  *dentro* l'intervallo già coperto (più oggi, se oggi è vuoto): su un diario
  appena avviato, trenta righe "nessuna voce" direbbero solo che è nuovo.
- `vista=settimane` / `vista=mesi` → una riga per periodo (ultime 8 settimane,
  ultimi 6 mesi), che riassume le giornate scritte. Il testo narrativo del
  periodo lo scriverà il job settimanale di §8.4.
- **Le bozze si vedono sempre**, in tutte le viste e fuori dal periodo
  comprese, e `vociInAttesa` le conta tutte: una voce lasciata da approvare il
  31 non deve sparire dalla pagina il primo del mese dopo.

`stato` è `"da_approvare"` finché non l'hai confermata (`testo` è allora la
bozza proposta), `"approvata"` dopo — e da quel momento `testo` è la versione
approvata e `approvataAlleLabel` dice a che ora. `scarta` **cancella anche il
materiale grezzo**: nel diario entra solo ciò che approvi (§8.4), quindi una
bozza rifiutata non resta da nessuna parte e il giorno torna `assente`.

`riepilogoSettimanale` porta l'ultimo riepilogo scritto dal job settimanale in
`worker/` (§8.4 punto 7); è **omesso** finché il job non ne ha scritto uno.
`riepilogoMensile` resta invece sempre omesso: un job mensile non esiste e §8.4
non lo prevede — campo assente ≠ campo vuoto.

Approvare una giornata la cui raccolta è ancora aperta (nessuna bozza) risponde
`409`.

## Lezioni e corsi

`GET /api/lezioni?vista=settimana|mese` → `LezioniData`
`POST /api/lezioni/piani/:id/rigenera` → `PianoRipasso`
`POST /api/lezioni/piani/:id/manda-al-bot` → `204`

## Task

`GET /api/task?vista=scadenza|progetto|completati` → `TaskData`
`PATCH /api/task/:id` body `{ fatto?: boolean, rinviaGiorni?: number }` → `TaskItem`
`POST /api/task` body `{ titolo: string, scadenza?: string }` → `TaskItem` (201)

La colonna principale della pagina arriva come `sezioni: { titolo, task[],
notaVuoto? }[]`: i titoli li decide il backend in base alla vista, così la
pagina non deve sapere quali raggruppamenti esistono.

- `vista=scadenza` → "In ritardo", "Oggi", "Prossimi sette giorni", "Senza
  scadenza"; le sezioni vuote non vengono mandate, tranne "Oggi" che porta una
  `notaVuoto`.
- `vista=completati` → "Chiusi oggi", "Questa settimana", "Prima".
- `vista=progetto` → raggruppa per provenienza (Dashboard, Telegram, Piano di
  ripasso, Regola di contesto): finché nello schema non esiste un concetto di
  progetto, è l'unico raggruppamento che i dati permettono davvero.

`scadenza` in `POST` è ISO-8601: `"2026-09-04"` per tutto il giorno oppure
`"2026-09-04T18:00"` per un'ora precisa. `rinviaGiorni` sposta la scadenza in
avanti e incrementa il contatore dei rinvii (che la riga mostra come
`"rinviato 3×"`); un task senza scadenza ne riceve una a partire da oggi.

## Lista della spesa

`GET /api/lista-spesa?ordina=reparto|aggiunta` → `ListaSpesaData`
`PATCH /api/lista-spesa/:id` body `{ preso: boolean }` → `ShoppingItem`
`POST /api/lista-spesa` body `{ nome: string, quantita?: string, reparto?: string }` → `ShoppingItem` (201)
`POST /api/lista-spesa/svuota-presi` → `204`

Con `ordina=reparto` i gruppi sono i reparti in ordine alfabetico, con "Altro"
in fondo; con `ordina=aggiunta` c'è un solo gruppo, "Da prendere", in ordine di
inserimento. Aggiungere una voce già presente e non ancora presa non ne crea
una seconda: risponde con quella esistente.

`ultimeSpese` e `ultimaSpesaGiorni` arrivano dal modulo spese (§8.5) e contano
solo le spese che hanno un **luogo**: la colonna mostra proprio il posto, e
«8 € di colazione» detto senza dire dove non è un'uscita da ricordare qui.
`stimaCarrello`, `suggeriti` e `repartiFrequenti` restano assenti o vuoti:
stimare il costo di questo carrello vorrebbe i prezzi delle singole voci (di
uno scontrino si conserva solo il totale), e le frequenze di riacquisto
vorrebbero lo storico della *lista*, che oggi `svuota-presi` cancella.

## Spese

`GET /api/spese?periodo=settimana|mese|anno` → `SpeseData`
`POST /api/spese/:id/conferma` body `{ categoria?: string }` → `Movimento`
`POST /api/spese` body `{ importo: number, descrizione: string, categoria?: string }` → `Movimento`

Tutti gli `importo` sono in **euro**, come numeri: nel database stanno in
centesimi interi (§8.5) e la conversione avviene qui, al confine.

`stats` e `andamentoGiorni` seguono il `periodo` scelto, non il mese: i nomi
dei campi dicono «mese» per ragioni storiche, ma un selettore che non cambia
le statistiche non sarebbe un selettore. In particolare:

- `totaleMese` e `mediaGiorno` sono sul periodo, e la media è sui giorni
  **trascorsi** (il 3 del mese si divide per 3, non per 31).
- `variazioneMesePrecedente` è in punti percentuali e confronta tratti della
  **stessa lunghezza**: i primi 12 giorni di questo mese contro i primi 12
  dello scorso. Senza niente prima vale `0`, non un numero enorme calcolato
  su zero.
- `andamentoGiorni` ha una colonna per giorno su `settimana` e `mese`, una per
  **mese** su `anno`; i valori sono percentuali `0-100` sulla colonna più
  alta, e l'ultima colonna è sempre oggi.
- `confronto` elenca solo i periodi già chiusi in cui hai davvero speso
  qualcosa: su un database nuovo è una lista vuota, non una riga a zero.

`scontrinoInAttesa` è la foto letta che aspetta un sì. Le spese in quello
stato **non entrano** in `movimenti` né nei totali: `POST /:id/conferma` è ciò
che le fa entrare, e può correggerne la categoria. Confermare una spesa già
nei conti risponde `409`.

`POST /api/spese` senza `categoria` ne fa proporre una a Claude confrontandola
con quelle già in uso (§6); se il modello non risponde la spesa resta senza,
e la si sistema dopo. Importo non positivo o descrizione vuota → `422`.

## Abitudini

`GET /api/abitudini?vista=settimana|mese` → `AbitudiniData`
`PATCH /api/abitudini/:id/log` body `{ data: string, fatto: boolean }` → `AbitudineDettaglio`
`POST /api/abitudini/:id/proposta/accetta` → `204`
`POST /api/abitudini/:id/proposta/rifiuta` → `204`

## Regole di contesto

`GET /api/regole` → `RegoleData`
`POST /api/regole/:id/approva` → `RegolaAttiva`
`POST /api/regole/:id/scarta` → `204`
`PATCH /api/regole/:id` body `{ stato: "attiva" | "pausa" }` → `RegolaAttiva`

## Impostazioni

`GET /api/impostazioni` → `ImpostazioniData`
`PATCH /api/impostazioni` body `Partial<ImpostazioniData>` → `ImpostazioniData`

## Assistente ("A Custode")

Ogni pagina ha una barra di input in stile chat, in cima allo stesso canale
usato dal bot Telegram (§8.1 del documento di progettazione).

`POST /api/assistente/messaggio` body `{ testo: string }` → `{ rispostaLabel?: string }`

Dopo l'invio la dashboard invalida le query della pagina corrente, così un
comando come «sto finendo il latte» si riflette appena il backend lo elabora.

Il testo passa dal router (§6), che ne ricava un'intenzione strutturata; il
backend la esegue subito e restituisce in `rispostaLabel` la frase da mostrare
(«Aggiunto alla lista: latte»). La stessa risposta del modello porta anche il
controllo passivo di §8.4 sui segnali per il profilo: quello succede in
silenzio, non cambia `rispostaLabel`, e la revisione avviene su Telegram (il
profilo non ha ancora una pagina nella dashboard — si legge con `/profilo`).
Oggi copre task, lista della spesa, diario e spese —
un messaggio che racconta la giornata invece di chiedere qualcosa finisce fra
il materiale del diario di oggi (§8.4), e uno con dentro una cifra già pagata
(«ho pagato 8€ la colazione») diventa una spesa (§8.5). Se la frase dice
**quando** hai speso («ieri ho pagato 17 euro la spesa»), la spesa si registra
a quel giorno e non a oggi, e `rispostaLabel` lo dice in coda («, di ieri»,
«, del 29 ago») — come già fa la conferma di uno scontrino. Una data nel futuro
viene scartata e vale oggi: ogni vista finisce a oggi, quindi una spesa datata
in avanti resterebbe scritta e invisibile (§8.5). Per un messaggio che non chiede nulla
di previsto la risposta lo dice, senza errore.

**Risponde sempre 200**, anche quando il modello non è configurato o non
risponde: il motivo arriva in `rispostaLabel` in italiano, perché è una cosa
che l'utente può semplicemente riprovare, non un errore HTTP da mostrare.
