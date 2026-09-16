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
**Diario**, **Spese**, **Abitudini**, **Calendario** — con i suoi tipi di evento,
che da §8.10 pezzo 6 si creano e si modificano da lì — **Impostazioni** e la
barra **«A Custode»**.
Restano a `501` le **regole di contesto** (§8.10) e i **corsi** (§8.11) — vedi
la roadmap in `../ARCHITECTURE.md` §12.

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

`calendarioOggi` compare **solo** se il calendario è collegato, cioè se ci sono
`CALENDARIO_CLIENT_ID`, `CALENDARIO_CLIENT_SECRET` e `CALENDARIO_REFRESH_TOKEN`
(§8.10). Contiene gli eventi che **toccano** oggi, non solo quelli che
cominciano oggi: un viaggio partito venerdì è un impegno anche di sabato.

`ora` è `"09:00"` per un evento con un orario che comincia oggi. Per chi un'ora
non ce l'ha è `"—"`, e `meta` dice perché: `"tutto il giorno"` per un evento di
giornata, `"in corso"` per uno cominciato prima di oggi e non ancora finito —
lì l'ora d'inizio è di un altro giorno e mostrarla direbbe una cosa falsa.

`calendarioNotaVuoto` è la frase da scrivere al posto della lista quando la
lista è **vuota**, ed è omessa quando c'è almeno un evento. Esiste perché una
giornata davvero libera e un calendario che non ha ancora sincronizzato danno
entrambi una lista vuota, ma non vogliono dire la stessa cosa: la prima è
`"Nessun evento oggi."`, la seconda `"Non ho ancora sincronizzato gli eventi di
oggi."` — dirla sbagliata a calendario appena collegato sarebbe semplicemente
falso, visto che il worker sincronizza ogni cinque minuti.

`meta` non porta il tipo dell'evento (lezione, palestra, viaggio) nemmeno ora
che il tagging esiste: in Home la riga dice *quando* e *dove*, e il tipo si
vede — e si corregge — nella pagina Calendario. `CalendarEventItem` resta
quindi il blocco comune, e `EventoCalendario` è la stessa riga più il tag.

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

## Calendario

`GET /api/calendario?vista=settimana|mese|da_rivedere` → `CalendarioData`
`PATCH /api/calendario/:id` body `{ tipo: string }` → `CorrezioneTag`
`POST /api/calendario/tipi` body `{ nome, descrizione }` → `TipoEventoSalvato`
`PATCH /api/calendario/tipi/:slug` body `{ nome?, descrizione?, attivo? }` → `TipoEventoSalvato`
`DELETE /api/calendario/tipi/:slug` → `204`

La pagina risponde a due domande diverse, ed è la ragione delle tre viste:
*«cosa ho questa settimana»* (`settimana`, `mese`) e *«cosa ha capito Custode»*
(`da_rivedere`).

- `vista=settimana` → la settimana **corrente**, lunedì–domenica, con tutti e
  sette i giorni anche vuoti: sette righe si leggono, e un giorno libero è
  un'informazione. Un giorno vuoto porta la sua `notaVuoto`.
- `vista=mese` → il mese corrente, e **solo** i giorni che hanno qualcosa:
  trenta righe «niente in programma» non direbbero niente.
- `vista=da_rivedere` → non eventi ma **serie**: le proposte dell'IA che non
  hai mai confermato, dalla prossima in poi. Una riga per ricorrenza, perché
  correggere un'occorrenza le corregge tutte — dodici righe sarebbero dodici
  volte la stessa correzione. Solo ciò che deve ancora succedere: un tag
  sbagliato su una lezione di marzo non produce più niente di sbagliato.

Un evento compare in **ogni giorno che tocca**, non solo in quello in cui
comincia; `ora` e `meta` seguono le stesse regole del blocco della Home
(`"—"` e `"tutto il giorno"` / `"in corso"` per chi un'ora non ce l'ha).

`statoTag` è la ragione d'essere della pagina, e vale `"da_guardare"` |
`"proposto"` | `"corretto"` — con `statoTagLabel` già in italiano. `tipo` da
solo non basterebbe: `"altro"` è sia il default di un evento appena
sincronizzato sia un esito legittimo del modello (§8.10), quindi senza un
secondo segnale «l'IA ha detto altro» e «nessuno l'ha ancora guardato»
sarebbero la stessa cosa.

`tipi` porta i tipi di evento con le loro etichette: il menu di correzione li
riceve dal backend invece di scriverli nella pagina, com'è per ogni altra
etichetta del contratto. Erano quattro e fissi; da §8.10 pezzo 6 li crei tu, e
questo campo non ha cambiato forma — ha solo smesso di essere un elenco che si
sapeva a memoria.

Ci sono **anche gli archiviati** (`attivo: false`): un impegno di marzo può
portare un tipo archiviato ieri, e la sua etichetta va comunque mostrata. Il
menu di correzione offre gli attivi più, se c'è, quello che l'evento ha già
addosso — un menu che non contiene il valore selezionato mostrerebbe la prima
voce dell'elenco, cioè direbbe una cosa falsa su cosa c'è in archivio.

`valore` è lo **slug**, deciso alla creazione e mai più toccato: è ciò che si
manda indietro in `PATCH`, ed è ciò che un evento porta scritto. `label` è il
nome, e cambia quando lo rinomini. È la ragione per cui rinominare un tipo non
tocca nessun evento. `descrizione` è la riga che legge il modello per decidere
(«treni, voli, trasferte; non il luogo di un altro impegno»), ed è la manopola
con cui si aggiusta il tiro quando classifica male.

`notaLabel` c'è sempre e dice `eventi` a parole, più cosa se ne può fare: «3
impegni lo usano: si archivia, non si cancella», «Non lo usa nessun impegno: si
può ancora cancellare». Un numero nudo in un angolo non direbbe di cosa è il
conto, e uno `0` ancora meno; detto così, spiega anche perché i bottoni della
riga sono quelli che sono.

### I tipi si gestiscono da qui

E non dalle impostazioni: i tipi si guardano dove si vedono gli impegni. Il menu
di correzione è il posto in cui ci si accorge che un tipo manca, e `da_rivedere`
quello in cui si vede il modello sbagliare perché non ce l'ha.

`POST /api/calendario/tipi` vuole **nome e descrizione**, tutti e due non vuoti.
La descrizione è obbligatoria perché è la riga che legge il modello: un tipo
senza non è un tipo creato più in fretta, è un tipo che il modello sbaglia. Lo
slug si ricava dal nome (minuscole, senza accenti, `_` al posto del resto); un
nome che non contiene nessuna lettera o cifra → `422`, come un nome già usato.
Se lo slug esiste **archiviato**, quello si **riprende** invece di aprirne un
secondo — `palestra` e `palestra_2` spaccherebbero in due gli impegni già
taggati — e `label` lo dice, perché è una cosa diversa da quella che hai chiesto.

`PATCH /api/calendario/tipi/:slug` cambia `nome`, `descrizione` e `attivo`. Lo
slug non c'è nel corpo e non è una dimenticanza: è l'identificatore che esce dal
database — sta negli eventi, nel contratto, nell'enum che riceve il modello —
e cambiarlo vorrebbe dire rincorrerlo in tutti quei posti insieme. `attivo:
false` **archivia**: il tipo esce dal menu e dal prompt del modello, ma resta
addosso agli impegni che ce l'hanno. Un tipo che non esiste → `404`; un nome già
di un altro → `422`; archiviare «Altro» → `409`.

`DELETE /api/calendario/tipi/:slug` cancella davvero, e **solo** un tipo che
nessun impegno usa: il caso dell'hai appena creato e non ti serve. Per tutti gli
altri c'è l'archiviazione, perché cancellare un tipo usato vorrebbe dire
riscrivere il tipo degli impegni che ce l'hanno, cioè riscrivere la storia di
cos'era un impegno perché oggi hai cambiato idea. Un tipo in uso → `409` che
dice **quanti** sono e cosa fare al posto suo; un tipo che non esiste → `404`.

**«Altro» è speciale** (`diSistema: true`): è il tipo con cui nasce ogni evento
appena sincronizzato e il ripiego di una risposta illeggibile del modello. Si
rinomina come gli altri — è ciò che *fa* a essere di sistema, non come si chiama
— ma non si archivia né si cancella: `409` in tutti e due i casi.

La `PATCH` è il «tu correggi se serve» di §8.10 e tocca **tutta la serie**
dell'evento indicato, non la sola occorrenza: la risposta dice quante
occorrenze ha cambiato (`occorrenze`) e come dirlo (`label`). Mandare lo stesso
tipo che c'era è comunque una conferma — «ha indovinato» è una risposta, e
senza di essa l'unico modo di togliere dalla coda una proposta giusta sarebbe
cambiarla in una sbagliata e poi rimetterla a posto. Un tipo che non esiste
risponde `422` (il `404` parlerebbe dell'evento nell'URL, che invece c'è), un id
inesistente `404`.

`stats.daRivedere` e `stats.daGuardare` parlano sempre di tutto l'archivio da
oggi in poi, **non** della vista: se «due da rivedere» sparisse guardando una
settimana che non ne contiene, alla terza vista non ci si arriverebbe mai.
`daGuardare` conta le serie che il tagging non ha ancora guardato, **da oggi in
poi** come la coda: un impegno di marzo rimasto senza tipo non è una cosa da
sbrigare, e tenerlo nel conto lo lascerebbe sopra zero per sempre. Il *lavoro*
del worker resta su tutto l'archivio — lì il passato serve al motore di
contesto — ma questo è un numero mostrato a una persona.

`daGuardareLabel` è la frase che lo accompagna, assente quando `daGuardare` è
zero. Non è il numero detto a parole: dice anche **se** qualcuno li guarderà.
Col compito `tag_calendario` acceso sono minuti d'attesa; senza
`ROUTER_DEEPSEEK_API_KEY` non li guarda nessuno, il numero non scende mai, e la
pagina lo dice invece di promettere un'attesa che non finisce — la differenza
la sa solo il backend, quindi è lui a scrivere la frase.

`notaVuoto` dice *perché* la lista è vuota, come in Home: calendario non
collegato, collegato ma mai sincronizzato, o periodo davvero libero — sono tre
vuoti che si somigliano e non vogliono dire la stessa cosa. Senza credenziali
la pagina non mostra né eventi né numeri, nemmeno se in archivio è rimasto
qualcosa da quando era collegato: mostrarli direbbe che il calendario sta
funzionando, mentre è fermo.

`orizzonteLabel` dice fin dove arriva la finestra sincronizzata (§8.10: sette
giorni indietro, quattordici avanti). Serve al mese: quello che c'è dopo è
vuoto perché nessuno ha ancora guardato là, non perché quei giorni siano
liberi.

## Lezioni e corsi

`GET /api/lezioni?vista=settimana|mese` → `LezioniData`
`POST /api/lezioni/piani/:id/rigenera` → `PianoRipasso`
`POST /api/lezioni/piani/:id/manda-al-bot` → `204`

## Task

`GET /api/task?vista=scadenza|provenienza|completati` → `TaskData`
`PATCH /api/task/:id` body `{ fatto?: boolean, rinviaGiorni?: number }` → `TaskItem`
`POST /api/task` body `{ titolo: string, scadenza?: string }` → `TaskItem` (201)

La colonna principale della pagina arriva come `sezioni: { titolo, task[],
notaVuoto? }[]`: i titoli li decide il backend in base alla vista, così la
pagina non deve sapere quali raggruppamenti esistono.

- `vista=scadenza` → "In ritardo", "Oggi", "Prossimi sette giorni", "Senza
  scadenza"; le sezioni vuote non vengono mandate, tranne "Oggi" che porta una
  `notaVuoto`.
- `vista=completati` → "Chiusi oggi", "Questa settimana", "Prima".
- `vista=provenienza` → raggruppa per **da dove arriva** il task (Dashboard,
  Telegram, Piano di ripasso, Regola di contesto). Si chiamava `progetto`, e il
  nome era sbagliato: un progetto nello schema non esiste, e promettere un
  raggruppamento che non c'è fa cercare qualcosa che non si troverà mai.

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
e la si sistema dopo. Importo non positivo o descrizione vuota → `422`. Il
corpo accetta anche `luogo` e `data` (AAAA-MM-GG): una spesa scritta a mano è
quasi sempre una che ti eri dimenticato di dire al bot, quindi senza `data`
finirebbe a oggi, cioè nel giorno sbagliato proprio nel caso per cui la stai
scrivendo da qui.

### Correggere ed eliminare

`PATCH /api/spese/:id` body `ModificaSpesa` → `Movimento`
`DELETE /api/spese/:id` → `204`

Servono perché una spesa sbagliata la si scopre **dopo**: un importo letto
male, una data che non è quella, la categoria che il modello ha sbagliato.
Prima di queste due rotte l'unica uscita era «Annulla» sul messaggio Telegram
appena ricevuto, e passata quella finestra si sarebbe dovuto aprire `sqlite3`
sul Pi.

`PATCH` tocca **solo i campi passati**; `luogo` e `categoria` a stringa vuota
**tolgono** il valore, che è l'unico modo di correggere un luogo che il modello
si è inventato. Importo non positivo, descrizione vuota, data malformata o
**nel futuro** → `422` (una spesa datata in avanti sparirebbe da ogni vista,
che finisce a oggi, §8.5). Spesa inesistente → `404`.

`Movimento` porta ora anche `data` (AAAA-MM-GG) e `luogo`: `dataLabel` è ciò
che si legge, `data` è ciò che il form rimanda indietro per correggerla.

Sulla pagina Spese restano inerti **«Esporta CSV»** e **«Carica altri
movimenti»**: sono comodità, non rimediano a un errore, e la seconda ha
bisogno di una paginazione che il contratto non prevede. «Registra spesa» e
«Cambia categoria» invece ora funzionano.

### Categorie

`GET /api/spese/categorie` → `CategoriaSpesaGestione[]`
`PATCH /api/spese/categorie/:id` body `{ nome?, attiva? }` → `CategoriaSpesaGestione`
`POST /api/spese/categorie/:id/unisci` body `{ inId }` → `204`

L'elenco comprende anche le categorie **spente**, perché è lì che si fa
ordine, e il conteggio `spese` è su tutto lo storico e non sul periodo della
pagina: quando decidi se unire due categorie conta quante spese ci sono
attaccate in tutto, non quante ne hai fatte questo mese.

`unisci` sposta le spese della categoria `:id` su `inId` e **spegne** la prima
invece di cancellarla, così resta traccia di come si chiamava: è il rimedio ai
doppioni semantici che il modello non ha evitato («Cibo» accanto ad
«Alimentari») e al nome di un negozio finito fra le categorie. Unire una
categoria a sé stessa → `422`; una categoria che non esiste → `404`.
`attiva: false` la toglie dalle proposte dell'interprete (§6) senza toccare le
spese già registrate.

## Abitudini

`GET /api/abitudini?vista=settimana|mese` → `AbitudiniData`
`POST /api/abitudini` body `{ nome, targetSettimanale }` → `AbitudineDettaglio`
`PATCH /api/abitudini/:id` body `{ nome?, targetSettimanale?, attiva? }` → `AbitudineDettaglio`
`PATCH /api/abitudini/:id/log` body `{ data: string, fatto: boolean }` → `AbitudineDettaglio`
`POST /api/abitudini/:id/proposta/accetta` → `204`
`POST /api/abitudini/:id/proposta/rifiuta` → `204`

Le due rotte di **creazione e modifica** non erano nella v1 di questo
contratto, ma §8.6 vuole le abitudini «aggiungibili, disattivabili e
modificabili in qualsiasi momento» e il bot le sa solo segnare: sono quindi il
canale con cui si gestiscono, ed è il bottone «Nuova abitudine» della pagina a
usarle. `targetSettimanale` va da 1 a 7 (7 = tutti i giorni); fuori scala,
nome vuoto o nome già usato da un'altra abitudine → `422`. `attiva: false`
**non cancella**: toglie l'abitudine dalla pagina lasciando i suoi log dove
sono, e riattivarla ne riprende la storia. Creare con un nome che esiste già
riprende quella, invece di aprire un doppione che spezzerebbe la storia in due.

`vista` cambia il **periodo su cui si contano i fatti**, non i pallini: i sette
di ogni riga sono sempre la settimana corrente, lunedì → domenica, perché
l'intestazione della colonna nella pagina è fissa. Con `vista=settimana`
`goalRatioLabel` è «fatte/target» (es. `2/3`); con `vista=mese` il denominatore
è proporzionale ai **giorni trascorsi** del mese, arrotondato e mai sotto 1
(es. `8/13`) — contare i giorni che devono ancora arrivare farebbe apparire
ogni inizio periodo come un disastro. `evidenziata` compare **solo** quando
`fatte >= denominatore`, cioè esattamente quando il rapporto che si legge dice
che l'obiettivo è centrato.

`stats.costanzaMese` è sempre **mensile**, in tutte e due le viste (è quello che
dice il nome): l'aderenza media di tutte le abitudini attive, con il tetto al
100% per ciascuna. `streakMigliore` e `streak[].valoreLabel` sono in **giorni**
consecutivi; se oggi non è ancora segnato la striscia si conta fino a ieri,
altrimenti la mattina sarebbe sempre zero. `meseSingolaAbitudine` è il
calendario a pallini della **sola** abitudine più costante del mese, dal primo
del mese a oggi — una griglia per ognuna sarebbe un muro di pallini.

`PATCH .../log` accetta solo un giorno passato o oggi (`data` in `AAAA-MM-GG`):
un giorno futuro dà `422`, per lo stesso motivo per cui una spesa datata in
avanti viene scartata (§8.5) — ogni vista finisce a oggi. Rimandare lo stesso
giorno **aggiorna** il log invece di accodarne un altro, e `fatto: false` non è
la stessa cosa di un log assente: è un «non l'ho fatta» detto esplicitamente,
che non conta nell'aderenza ma resta scritto.

`avviso` compare **solo** quando c'è un'abitudine che non segni da almeno dieci
giorni, e ne nomina una — la più ferma. Un'abitudine mai segnata non lo fa
scattare: è nuova, non è in calo.

`proposta` è un adeguamento del target proposto dal report mensile (§8.6):
`:id` nelle due rotte `proposta/accetta|rifiuta` è **l'id della proposta**, che
è quello che il campo contiene. «Accetta» applica il nuovo target, «rifiuta»
archivia e basta; in entrambi i casi la proposta sparisce dalle risposte
successive. Decidere due volte la stessa proposta → `409`; una proposta che non
esiste → `404`.

`report` è il racconto scritto da Claude per la vista scelta — il settimanale
per `vista=settimana`, il mensile per `vista=mese` — ed è **assente** finché il
worker non ne ha scritto uno: campo assente ≠ campo vuoto.

## Regole di contesto

`GET /api/regole` → `RegoleData`
`POST /api/regole/:id/approva` → `RegolaAttiva`
`POST /api/regole/:id/scarta` → `204`
`PATCH /api/regole/:id` body `{ stato: "attiva" | "pausa" }` → `RegolaAttiva`

## Impostazioni

`GET /api/impostazioni` → `ImpostazioniData`
`PATCH /api/impostazioni` body `ModificaImpostazioni` → `ImpostazioniData`

**Ci sono solo le manopole che girano qualcosa.** Questo contratto aveva da
sempre più campi di quanti moduli esistessero: il digest mattutino (§8.13),
l'ora della voce di diario, le ore di silenzio, le quattro approvazioni, il
primo giorno della settimana, il tetto mensile e la soglia d'avviso. Nessuno di
quelli è cablato a niente, e mandarli vorrebbe dire un interruttore che non
interrompe — lo giri, non succede nulla, e da lì in poi non ti fidi più nemmeno
di quelli che funzionano. Si omettono, che è la regola scritta in cima a questo
file: un campo il cui modulo non è ancora attivo si **omette**. Torneranno, uno
alla volta, col modulo che li legge.

L'unica eccezione è `orari.checkInMinutiDopo`, il margine di «sei probabilmente
a casa»: §8.10 lo vuole esplicitamente configurabile, e si salva già adesso come
`calendar_events.tipo` esisteva prima del tagging. Chi lo legge arriva dopo.

**Il `.env` del Pi è il punto di partenza, non una seconda fonte di verità.**
Finché non hai mai salvato un campo, quello che vedi è il valore con cui
l'installazione è nata (`CUSTODE_BUDGET_SETTIMANALE`, `WORKER_GIORNO_RIEPILOGO`,
`WORKER_ORA_RIEPILOGO`). Dal primo salvataggio vince il database e la variabile
smette di contare. `notaLabel` dice quante ne vengono ancora da lì, ed è l'unica
domanda a cui il `.env` da solo non sa rispondere — se un valore l'hai scelto tu
o te l'ha dato l'installazione.

**Un cambio è attivo senza riavviare niente.** Non c'è nessun meccanismo, ed è il
punto: l'API apre una connessione per richiesta, quindi la Home vede un budget
nuovo al ricaricamento successivo; il worker rilegge giorno e ora **in cima a
ogni giro**, quindi al più tardi fra cinque minuti. Nessun segnale, nessuna
cache, nessun `docker compose restart`.

**Nei segreti non si entra** (§9). `connessioni` dice cosa è collegato e — quando
non lo è — **quale variabile manca**, che è la sola cosa che permette di
rimetterla a posto senza cercare nei log del Pi. Il valore di quella variabile
non esce mai da qui, e `PATCH` non ne accetta nessuno: le credenziali stanno nel
`.env`, come ogni altra del progetto.

`PATCH` accetta **solo i blocchi che vuoi cambiare**, e guarda quali chiavi
arrivano invece del loro valore. La differenza conta per il budget:
`{"budget": {"settimanale": null}}` **cancella** il budget — e la Home smette di
disegnare il blocco delle spese — mentre un `budget` che non arriva è un budget
che non volevi toccare. Se i due casi si confondessero, cambiare un orario
cancellerebbe il budget. Una stringa vuota vale come `null`, perché è quello che
manda un campo di testo svuotato a mano.

La `PATCH` è **atomica**: con due campi di cui il secondo storto non si salva
niente e la risposta è `422` col motivo in italiano. Senza, il riepilogo
resterebbe spostato a un giorno che non hai scelto mentre la risposta dice che
non è cambiato nulla.

`sistema.ultimoSyncCalendarioLabel` è il caso che §8.10 lascia scoperto: a worker
fermo la pagina Calendario dice «niente in programma», che rispetto all'archivio
è pure vero — solo che l'archivio è di tre giorni fa. Qui si legge «3 giorni fa»,
o «mai» se non ha mai sincronizzato. Stessa scala per `dati.ultimoBackupLabel`.

`botStatoLabel` dice se il bot è **configurato**, non se è vivo — e la frase lo
dice. Vivo non si può sapere da qui: il bot non lascia una traccia periodica come
fa il worker con `job_runs`, e contare i frammenti di diario darebbe un numero
che sembra una risposta senza esserlo (una giornata in cui non hai raccontato
niente si leggerebbe come un bot morto). Per la stessa ragione `dati` non porta
`messaggiBot`.

## Assistente ("A Custode")

Ogni pagina ha una barra di input in stile chat, in cima allo stesso canale
usato dal bot Telegram (§8.1 del documento di progettazione).

`POST /api/assistente/messaggio` body `{ testo: string }` → `{ risposteLabel: string[] }`

Dopo l'invio la dashboard invalida le query della pagina corrente, così un
comando come «sto finendo il latte» si riflette appena il backend lo elabora.

Il testo passa dal router (§6), che ne ricava una o più intenzioni strutturate;
il backend le esegue subito e restituisce in `risposteLabel` **una frase per
ogni cosa fatta**, nell'ordine in cui è stata fatta («Aggiunto alla lista:
latte»). Quasi sempre è una sola.

**Perché una lista e non una stringa.** Un messaggio può chiedere più cose
insieme: «giornata pesante in laboratorio, devo ricordarmi di mandare la mail
al prof» è insieme un racconto per il diario e un promemoria. Unire le due
frasi in una stringa sola lascerebbe alla dashboard il problema di ridividerle,
cioè un'etichetta prodotta a metà dal backend e a metà dal frontend — mentre le
etichette italiane le produce il backend. Su Telegram le stesse frasi diventano
**messaggi separati**, uno per azione, ognuno col suo «Annulla»: così si disfa
la cosa sbagliata senza toccare l'altra. Il diario è sempre l'ultima frase,
perché si legge prima cosa Custode ha fatto e poi che ha preso nota.

La stessa risposta del modello porta anche il controllo passivo di §8.4 sui
segnali per il profilo: quello succede in silenzio, non aggiunge frasi a
`risposteLabel`, e la revisione avviene su Telegram (il profilo non ha ancora
una pagina nella dashboard — si legge con `/profilo`).

Oggi copre task, lista della spesa, diario, spese e abitudini —
un messaggio che racconta la giornata invece di chiedere qualcosa finisce fra
il materiale del diario del giorno che racconta — «ti racconto la giornata di
ieri» finisce su ieri, non su oggi (§8.4) — e uno con dentro una cifra già pagata
(«ho pagato 8€ la colazione») diventa una spesa (§8.5). Se la frase dice
**quando** hai speso («ieri ho pagato 17 euro la spesa»), la spesa si registra
a quel giorno e non a oggi, e la frase lo dice in coda («, di ieri»,
«, del 29 ago») — come già fa la conferma di uno scontrino. Una data nel futuro
viene scartata e vale oggi: ogni vista finisce a oggi, quindi una spesa datata
in avanti resterebbe scritta e invisibile (§8.5). Per un messaggio che non chiede nulla
di previsto la risposta lo dice, senza errore.

`risposteLabel` non è mai vuota: anche un messaggio che non chiede niente e un
guasto del modello producono la loro frase.

**Risponde sempre 200**, anche quando il modello non è configurato o non
risponde: il motivo arriva in `risposteLabel` in italiano, perché è una cosa
che l'utente può semplicemente riprovare, non un errore HTTP da mostrare.
