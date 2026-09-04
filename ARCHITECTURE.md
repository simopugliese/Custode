# Custode — Assistente IA Personale — Documento di Progettazione

## 1. Visione e principi guida

Un assistente personale, raggiungibile via Telegram (testo o vocale), che gestisce task quotidiani, spese, diario, abitudini e — in futuro — integrazioni con Spotify, Samsung Health ed email. Governato da questi principi non negoziabili:

- **Privacy first**: i dati vivono sul Raspberry Pi 5 di proprietà, non su servizi cloud terzi. Cloudflare è solo un "tramite" sicuro, non un depositario di dati.
- **Massima resa, minima spesa**: i task banali (todo, lista spesa, log abitudini) usano DeepSeek (economico); solo i task che richiedono qualità/ragionamento/vision usano Claude.
- **Sicurezza per design**: nulla è esposto pubblicamente senza autenticazione forte; niente porte aperte sul router di casa.
- **Riproducibilità**: tutto dockerizzato, env replicabile, documentazione di deploy completa.
- **Affidabilità**: ciò che va online deve funzionare al 100% — pipeline di test solida prima di ogni deploy.

## 2. Architettura ad alto livello

```
                         ┌─────────────────────────┐
   Telegram (testo/voce) │                         │
   ────────────────────► │   Raspberry Pi 5        │
                         │   - Bot Telegram         │
                         │   - API backend          │
                         │   - Router DeepSeek/Claude│
                         │   - Whisper locale (STT) │
                         │   - DB (SQLite)          │
                         │   - Docker Compose       │
                         └───────────┬─────────────┘
                                     │ Cloudflare Tunnel
                                     │ (nessuna porta aperta)
                         ┌───────────▼─────────────┐
                         │ Cloudflare Access        │
                         │ (Zero Trust, solo tu)    │
                         └───────────┬─────────────┘
                                     │
                         ┌───────────▼─────────────┐
                         │ Cloudflare Pages         │
                         │ (dashboard, frontend)    │
                         └──────────────────────────┘
```

**Perché questa combinazione:**
- **Cloudflare Tunnel** (`cloudflared`) espone il Pi verso internet senza aprire una sola porta sul router: il traffico esce dal Pi verso Cloudflare, mai il contrario.
- **Cloudflare Access** (parte del piano Zero Trust, gratuito fino a 50 utenti) mette un login davanti al tunnel: solo la tua identità (email/Google/GitHub, a scelta) può raggiungere dashboard e API, da qualsiasi rete. Nessun dato esposto pubblicamente, ma accessibile ovunque tu sia.
- **Cloudflare Pages** ospita solo il frontend statico della dashboard; parla con l'API sul Pi attraverso il tunnel.
- Il **database resta fisicamente sul Pi**: nessun dato personale (spese, diario, abitudini, salute) lascia casa tua se non per la singola chiamata API al modello necessario per elaborarlo.

## 3. Database: SQLite

Nessuna preferenza espressa, quindi la scelta è guidata dal caso d'uso: **SQLite**.

- Utente singolo, basso volume di scritture → non serve un DB client/server come Postgres.
- Un solo file da backuppare/testare/ripristinare: superficie di errore minima, perfetto per la tua richiesta di "testato a dovere prima della produzione".
- Modalità WAL per gestire bene le scritture concorrenti (bot + eventuali job schedulati).
- Backup: job giornaliero che copia il file (compresso e cifrato) fuori dal container, conservato localmente sul Pi + una copia su uno storage esterno di tua scelta (non necessariamente Cloudflare, per mantenere la logica "dati privati a casa").
- Se in futuro il progetto crescesse (più utenti, più carico), la migrazione a Postgres resta un'opzione aperta ma non necessaria oggi.

## 4. Stack tecnologico

| Componente | Scelta | Note |
|---|---|---|
| Backend API | Python + FastAPI | tipizzato, veloce da testare, ottimo ecosistema AI |
| Bot Telegram | `python-telegram-bot` | libreria matura, supporta testo e voce |
| Trascrizione vocale | Whisper locale (`whisper.cpp`, modello `base`, quantizzato q5_1) | compromesso accuratezza/carico scelto per Pi 5 condiviso con altri servizi (vedi sezione 13); thread limitati e CPU limit sul container per non "rubare" risorse al bot/API durante la trascrizione |
| DB | SQLite (WAL mode) | vedi sezione 3 |
| Orchestrazione | Docker Compose | un servizio per componente (bot, api, worker cron, db volume) |
| Esposizione | Cloudflare Tunnel + Access | vedi sezione 2 |
| Frontend dashboard | Cloudflare Pages (React o simile) | statico, parla con l'API via tunnel |
| CI/CD | GitHub Actions | test automatici ad ogni push, deploy solo se passano |

## 5. Struttura repository

```
/repo
  /bot            # logica Telegram
  /api            # FastAPI backend
  /router         # logica di scelta DeepSeek/Claude + interprete del testo libero
  /whisper        # trascrizione vocale locale (servizio a sé, §13)
  /worker         # job schedulati (riepilogo settimanale, backup, reminder)
  /core           # codice condiviso: configurazione, accesso SQLite, dominio
  /dashboard      # frontend (build separata, deploy su Pages)
  /tests          # unit + integration test
  /.github/workflows  # CI: lint + test ad ogni push
  pyproject.toml  # dipendenze Python di tutti i servizi
  uv.lock         # versioni bloccate (installazioni riproducibili)
  Dockerfile      # multi-stage: un target per servizio (api, bot, worker, whisper) + test
  docker-compose.yml
  docker-compose.test.yml
  .env.example    # SOLO placeholder, mai valori reali
  .gitignore      # .env, *.db, volumi docker
  .dockerignore
  ARCHITECTURE.md # questo documento
  DEPLOY.md
  README.md
```

Tutto su GitHub tranne: file `.env` reale, il database, e qualunque credenziale. Il `.env.example` documenta ogni variabile richiesta senza esporre segreti.

**Note di implementazione** (decisioni prese costruendo lo scheletro, non previste dalla bozza originale):
- `/core` non era nell'elenco iniziale. È stato aggiunto perché api, bot, router e worker hanno bisogno della stessa configurazione e dello stesso schema §7: l'alternativa era duplicarli in quattro punti destinati a divergere. Dentro ogni cartella vive un pacchetto Python con prefisso `custode_` (`core/custode_core`, `api/custode_api`, …) per avere import non ambigui.
- Le dipendenze Python sono gestite con **uv** e un `uv.lock` unico per tutti i servizi: un lockfile vero serve alla riproducibilità richiesta in §1, e su Pi 5 arm64 le installazioni restano veloci.
- L'API espone `GET /api/health`, che risponde 503 se SQLite non è raggiungibile: è il segnale su cui lo smoke test post-deploy di §10 fa scattare il rollback.
- Un solo `Dockerfile` multi-stage con un target per servizio, invece di un Dockerfile per cartella: Python, uv e le dipendenze comuni restano pinnati in un posto solo. Ogni dipendenza di servizio è un extra di `pyproject.toml` (`bot`, `router`, `whisper`, `worker`) e ogni target installa solo il suo, così l'immagine dell'API non si porta dietro python-telegram-bot — e nemmeno quella del worker, che su Telegram scrive e basta.
- Le migrazioni dello schema girano all'avvio di ogni servizio, dentro un'unica transazione aperta con `BEGIN IMMEDIATE`: API e bot partono in parallelo sullo stesso file SQLite, e chi arriva secondo trova il registro già aggiornato invece di riapplicare tutto.
- `worker/` non usa una libreria di scheduling: si sveglia ogni pochi minuti e chiede a una funzione pura «cosa è dovuto adesso?». Il vantaggio non è risparmiare una dipendenza su arm64, è che l'unica cosa che può sbagliare — *quando* — si prova in un millesimo di secondo invece che aspettando domenica sera. Il registro `job_runs` tiene il conto di cosa è già stato fatto per quale periodo: serve perché un job può legittimamente non produrre niente (una settimana senza voci approvate), e senza registro ripartirebbe ad ogni giro. Se il Pi era spento all'ora prevista, il job parte appena torna su invece di saltare la settimana.
- Il worker manda i suoi messaggi su Telegram con una sola chiamata HTTP, senza `python-telegram-bot`: i tap sui bottoni li riceve il bot, che è già in long polling. Riusa però `custode_bot.risposte` per comporre i messaggi — è possibile perché quel modulo è fatto di funzioni pure che non sanno cosa sia Telegram, ed è un'invariante da non rompere.
- Il modello non tocca mai il database: l'interprete di §6 gli chiede solo un'*intenzione strutturata*, che il codice traduce in chiamate ai servizi di dominio. Un modello che sbaglia può quindi far fare a Custode una cosa sbagliata fra quelle previste, mai una cosa non prevista.

## 6. Router DeepSeek / Claude

| Task | Modello | Motivo |
|---|---|---|
| Parsing lista della spesa | DeepSeek | task semplice, alto volume |
| CRUD task/promemoria | DeepSeek | task semplice |
| Log abitudini da testo libero | DeepSeek | matching contro lista abitudini esistenti, task semplice |
| Categorizzazione spesa da testo | DeepSeek | classificazione semplice |
| Lettura/estrazione scontrino da foto | **Claude** (vision) | serve qualità nella lettura OCR + comprensione |
| Riassunto/categorizzazione diario giornaliero | **Claude** | qualità del linguaggio, sfumature |
| Riepilogo settimanale diario → aggiornamento profilo | **Claude** | ragionamento su più giorni, sintesi |
| Rilevazione segnale utile per il profilo in un messaggio qualsiasi | DeepSeek | classificazione leggera, alto volume |
| Domanda di chiarimento su segnale ambiguo | DeepSeek | interazione semplice, non serve ragionamento profondo |
| Rifusione (riscrittura, non accodamento) del profile_document | **Claude** | va integrato e sintetizzato con giudizio, non solo concatenato |
| Creazione/adeguamento dinamico categorie spesa | **Claude** | richiede giudizio, evita categorie duplicate/incoerenti |
| Rilevazione pattern e proposta nuove regole di contesto | **Claude** | serve giudizio per capire se un pattern è abbastanza solido da proporre |
| Valutazione/esecuzione di una regola di contesto già approvata | *Nessun LLM* | è logica pura (confronto orari/eventi), gestita da codice/cron, costo zero |
| Piano di ripasso da check-in universitario + syllabus.md | **Claude** | ragionamento su cosa manca, incrociando le tue risposte col syllabus |
| Digest mattutino (meteo + calendario + task del giorno) | DeepSeek | composizione/template, nessun ragionamento complesso |
| Report narrativo settimanale/mensile abitudini | **Claude** | sintesi che incrocia più segnali (abitudini, diario, spese) |
| (futuro) Riassunto email | **Claude** | contenuto sensibile, serve qualità e un solo fornitore fidato |

**Stato attuale.** La tabella è codificata per intero in `router/custode_router/compiti.py`, motivi compresi, e chi chiama nomina il *compito*, mai il modello. Oggi passano di qui il parsing della lista della spesa, il CRUD dei task, il riconoscimento del materiale da diario e dei segnali per il profilo e l'estrazione di una spesa dal testo (tutti DeepSeek, e tutti nella stessa chiamata), più cinque compiti su **Claude**: il riassunto del diario, il riepilogo settimanale, la rifusione del profilo (§8.4), la scelta della categoria di una spesa e **la lettura degli scontrini** (§8.5) — l'unica riga *vision* della tabella, che manda l'immagine al modello con `chiedi_json_con_immagine`. Per gli altri il provider è deciso e il client pronto, ma nessun modulo li chiama ancora.

**Un tetto di token per Claude, separato da quello di DeepSeek.** Costruendo il diario è emerso che `max_token_risposta`, tarato su risposte JSON brevi, non può valere per entrambi: su `claude-opus-5` il ragionamento adattivo è attivo di default e i suoi token rientrano in `max_tokens`, quindi un tetto basso verrebbe consumato dal ragionamento e la risposta arriverebbe troncata invece che in JSON. Da qui `max_token_risposta_claude`, molto più alto, e un errore esplicito quando `stop_reason` è `max_tokens` — così il sintomo dice cosa alzare invece di somigliare a un prompt sbagliato. Il problema esisteva già ma non si era mai visto: a Claude non arrivava traffico.

## 7. Schema dati (bozza)

```
tasks(id, titolo, note, scadenza, stato, origine, rinvii, creato_il, completato_il)
shopping_list(id, item, quantita, reparto, comprato, aggiunto_il, comprato_il)

diary_entries(id, data, trascrizione_raw, riassunto_approvato, tag[], stato_approvazione)
diary_weekly_summary(id, settimana_inizio, testo, generato_il)
profile_document(id, versione, testo, aggiornato_il)   -- il "profilo" cumulativo, riscritto (non accodato) ad ogni aggiornamento
profile_candidates(id, messaggio_origine, estratto, stato[in_coda|chiarito|scartato], chiarimento_risposta, creato_il)

expenses(id, importo, descrizione, categoria_id, luogo, data, fonte[testo|scontrino], scontrino_raw_estratto)
expense_categories(id, nome, creata_da[utente|ia], attiva)

habits(id, nome, frequenza_target_settimanale, attivo, creato_il)
habit_logs(id, habit_id, data, fatto)

spotify_history(id, traccia, artista, ascoltato_il)
health_sleep(id, data, ore_sonno, qualita, dettagli_json)
health_activity(id, data, tipo, dettagli_json)

calendar_events(id, titolo, tipo[lezione|palestra|viaggio|altro], corso_id, inizio, fine, fonte)
context_rules(id, origine[ia|utente], trigger_tipo[orario|prima_evento|dopo_evento|pattern], trigger_valore, messaggio, stato, creata_il)

corsi(id, nome, syllabus_path, data_esame)
lezioni_log(id, corso_id, data, seguita, appunti_presi)
```

## 8. Moduli funzionali

### 8.1 Bot Telegram (testo + voce)
Funziona identico via testo o audio. L'audio passa da Whisper locale → testo → stessa pipeline del testo. Nessuna differenza di funzionalità tra le due modalità, solo di input.

**Stato attuale.** Il bot copre task, lista della spesa, diario e spese (§8.2, §8.3, §8.4, §8.5) in quattro modi che convivono: comandi espliciti con bottoni inline, testo libero interpretato dal router (§6), vocali trascritti da Whisper locale che imboccano lo stesso percorso del testo, e **foto**, che sono scontrini da leggere. Gira in long polling, con la whitelist di §9 applicata a comandi, testo libero e tap sui bottoni. Ogni azione decisa da un modello lascia un bottone «Annulla»: l'interpretazione è automatica, quindi disfare deve costare un tap.

**Colonne aggiunte alla bozza, costruendo i moduli** (le migrazioni reali sono in `core/custode_core/migrazioni/`):
- `tasks.origine` — dashboard, Telegram, piano di ripasso o regola di contesto: serve a raggruppare i task per provenienza e a etichettare la riga ("da piano di ripasso", §8.11).
- `tasks.rinvii` — quante volte un task è stato rinviato; è ciò che permette di accorgersi dei task che si trascinano invece di essere fatti.
- `tasks.completato_il` — data di chiusura, senza la quale non si può dire quanti task sono stati chiusi in una settimana.
- `shopping_list.reparto` — raggruppa la lista per reparto del supermercato; finché non c'è il router (§6) lo scrive chi aggiunge la voce, altrimenti resta "Altro".
- `shopping_list.comprato_il` — quando una voce è stata spuntata.
- `schema_migrations` — tabella di servizio del runner delle migrazioni.

Col diario si aggiungono `diary_entries` e `diary_fragments`: la loro forma, e perché si discosta dalla bozza di §7, è spiegata in §8.4.

Le scadenze stanno in un'unica colonna in ISO-8601: dieci caratteri (`2026-09-04`) significano "per tutto il giorno", una forma più lunga (`2026-09-04T18:00`) un'ora precisa.

### 8.2 Task / promemoria
CRUD via linguaggio naturale ("ricordami di...", "segna fatto..."). Un job cron controlla le scadenze e scrive su Telegram se qualcosa non è stato segnato come fatto.

### 8.3 Lista della spesa
Aggiunta dinamica ("sto finendo il latte" → aggiunge "latte"). Vista anche nella dashboard, spuntabile da lì o dicendolo al bot.

### 8.4 Diario (flusso concordato)
1. Una volta al giorno mandi un vocale (o testo).
2. Whisper locale trascrive.
3. Claude genera un riassunto + categorizzazione (tag: lavoro, salute, umore, ecc.).
4. Il bot ti rimanda il riassunto proposto su Telegram.
5. Tu approvi così com'è o lo modifichi.
6. Solo la versione approvata viene salvata (mai la bozza non confermata) — questo evita di "salvare dati sbagliati", come giustamente volevi anche per le spese.
7. Una volta a settimana, un job legge le 7 entry approvate e genera un riepilogo settimanale, che aggiorna il `profile_document` (il documento cumulativo che poi userai come contesto senza doverlo rispiegare ogni volta).

**Canale passivo (oltre al vocale di fine giornata).** Non tutto quello che è utile per il profilo passa dal diario strutturato — a volte è una frase buttata lì in chat ("oggi ho fatto un sito, che palle il frontend, a me piace il backend"). Per questo, ogni messaggio (non solo il vocale serale) passa da un controllo leggero (DeepSeek): "c'è un segnale utile per il profilo (preferenze, modo di lavorare, opinioni ricorrenti)?".
- Segnale **chiaro** → finisce silenziosamente in `profile_candidates`, nessuna interruzione della chat, va in revisione nel batch settimanale insieme al resto.
- Segnale **ambiguo** (es. uno sfogo del momento vs una preferenza reale) → il bot fa una domanda breve, lì per lì ("lo segno come preferenza generale o era solo la giornata storta?"), e la risposta chiarisce subito il candidato prima che entri in coda — così il grosso del lavoro di disambiguazione è già fatto quando arrivi alla revisione settimanale.

**Stato attuale.** §8.4 è completo: il ciclo dei punti 1-6, il canale passivo e il job settimanale del punto 7. Il ciclo quotidiano: si racconta la giornata a parole (scritte o dettate), `/diario` la chiude e chiede a Claude il riassunto, il bot lo rimanda con tre uscite — approva, modifica, scarta — e **solo la versione approvata** finisce in `riassunto_approvato`, l'unica che dashboard, statistiche e job settimanale leggeranno. `GET /api/diario` e le sue due mutazioni non rispondono più `501`.

È il primo modulo che manda traffico vero a Claude (§6): l'interpretazione del messaggio resta su DeepSeek — decide solo *dove va* quello che hai detto — mentre il riassunto, che è il pezzo dove servono qualità e sfumature, va a Claude.

**Una voce per giorno, fatta di frammenti.** La bozza di §7 prevedeva `diary_entries(… trascrizione_raw …)`, un campo di testo solo. Nel costruirlo sono emerse due cose che quel campo non regge:
- La voce è **del giorno**, non del messaggio: il punto 7 parla di «7 entry approvate» per una settimana, la dashboard conta le giornate (`coperturaMese`) e attribuisce una voce a più fonti insieme («da 3 vocali e 11 messaggi»). Quindi `data` è chiave unica, e tutto ciò che racconti quel giorno confluisce lì.
- §8.1 vuole che ogni azione decisa da un modello si possa disfare con un tap, e capire che un messaggio è materiale da diario è una decisione di un modello. Con un unico campo concatenato, «Annulla» potrebbe solo tagliare testo a occhio. Il materiale grezzo sta quindi in una tabella figlia `diary_fragments(id, entry_id, testo, da_vocale, creato_il)`: «Annulla» toglie esattamente la frase che aveva aggiunto, e `n_vocali`/`n_messaggi` si contano da lì invece di essere contatori da tenere allineati a mano. `trascrizione_raw` non sparisce: è la concatenazione di quei frammenti, ed è ciò che viene passato al modello.

**Colonne aggiunte alla bozza:** `riassunto_proposto` (la bozza, in una colonna separata da quella approvata: la dashboard mostra le voci «da approvare», quindi le bozze vanno persistite, altrimenti sparirebbero ad ogni riavvio del bot — resta però vero che nel *diario* entra solo l'approvato); `creata_il` e `approvata_il` (senza il secondo non si può scrivere `approvataAlleLabel`). Lo `stato_approvazione` ha quattro valori invece di due: `in_raccolta` → `da_approvare` → `approvata`, più `in_modifica` mentre il bot aspetta la tua riscrittura. Quello stato sta sul database e non nella memoria del processo apposta: se il bot riparte a metà, la conversazione riprende da dov'era invece di scambiare la riscrittura per una frase qualsiasi.

**Una giornata si può raccontare in ritardo.** «Ti racconto la giornata di ieri» va sul diario di **ieri**: una voce è del giorno raccontato, non del momento in cui lo racconti, ed è la stessa regola per cui una spesa è del giorno in cui hai speso (§8.5). A risolvere «ieri» è il modello, con lo stesso campo `data` delle spese e delle abitudini. Ne segue che serve anche un modo di **chiudere** un giorno che non è oggi, altrimenti quel racconto resterebbe grezzo per sempre: subito dopo l'annotazione il bot offre «Chiudi la giornata di ieri», dove la cosa è ancora in mente, e `/diario ieri` (o `/diario 2 set`) fa lo stesso quando ci ripensi dopo. L'argomento del comando lo interpreta il **codice** e non il modello — al contrario del linguaggio libero: è un insieme chiuso di forme che decido io, e pagare una chiamata per capire «ieri» sarebbe assurdo. Se quel giorno era già approvato non si perde niente: il dominio riporta la voce in raccolta e tiene leggibile l'approvazione precedente finché non ne approvi una nuova.

**Il «modifichi» del punto 5 è una riscrittura tua, verbatim.** «Modifica» chiede il testo corretto e quel testo diventa la voce approvata parola per parola, senza passare da nessun modello: ciò che resta nel diario è tuo, e non c'è un secondo giro in cui il modello possa reinterpretare la correzione.

**Scartare butta anche il grezzo.** «Solo la versione approvata viene salvata» letto fino in fondo: scartare significa «questo non deve restare», quindi non si conserva una bozza rifiutata da nessuna parte e il giorno torna vuoto.

**Il canale passivo, in una sola chiamata.** Il controllo «c'è un segnale utile per il profilo?» viaggia dentro la **stessa** risposta strutturata con cui DeepSeek interpreta il messaggio. Sono due righe distinte di §6, ma entrambe instradate a DeepSeek, quindi la scelta del modello non cambia: cambia solo che un compito già suo viaggia nello stesso pacchetto, invece di raddoppiare latenza e costo su ogni singolo messaggio. Un segnale chiaro finisce in coda in silenzio; uno ambiguo aggiunge la domanda alla risposta che il bot stava già dando — una notifica sola, e resta chiaro che è una parentesi rispetto a quello che Custode ha appena fatto. **Una domanda alla volta**: se ce n'è già una senza risposta, il segnale nuovo entra in coda e lo si guarda alla revisione. Due domande sospese in chat sono peggio di un candidato da guardare fra qualche giorno.

**La revisione settimanale funziona per sottrazione.** §8.4 parla di «candidati approvati della settimana» ma lo schema §7 non aveva uno stato per il sì: è stato aggiunto `approvato`. Il job non conferma i candidati uno per uno — te li mostra e tu butti quelli sbagliati, perché §8.4 stessa dice che il grosso della disambiguazione è già stato fatto al momento della domanda. Ogni candidato porta con sé il messaggio da cui è nato e l'eventuale chiarimento, così alla revisione si capisce di cosa si sta parlando.

**Il job propone la rifusione, non la impone.** §8.4 chiede una revisione dei candidati *prima* della rifusione, e una revisione senza di te non è una revisione: il job settimanale arriva fino a metterti l'elenco davanti, e il profilo si riscrive quando premi «Aggiorna il profilo». Se non lo premi non si perde niente — i candidati restano in attesa e ricompaiono nella revisione della settimana dopo.

**Il profilo non si accoda, si riscrive (rifusione).** Se ogni settimana si limitasse ad aggiungere testo, `profile_document` crescerebbe all'infinito: diventerebbe costoso da passare ad ogni chiamata e via via meno utile (rumore che copre segnale). Il job settimanale quindi non accoda: Claude legge la versione attuale del profilo + i candidati approvati della settimana e **produce una nuova versione compatta** che integra le novità e scarta ciò che è superato o ridondante — il profilo resta sempre snello (poche centinaia di parole) e sempre più su misura per te, non un log infinito. Ogni versione resta comunque salvata (`profile_document` versionato), quindi è sempre possibile tornare indietro se una riscrittura perde qualcosa di importante.

Il versionamento **è** la rete di sicurezza, e per questo la nuova versione non aspetta un'approvazione preventiva come una voce di diario: diventa attiva e il bot la manda con un bottone «Torna alla precedente». Tornare indietro è un annullamento e non una revisione — la versione sbagliata sparisce e i candidati che ci erano finiti dentro tornano approvati e non rifusi, così rientrano nella prossima rifusione invece di perdersi con lei. Claude accompagna ogni riscrittura con l'elenco di cosa è cambiato, che è ciò che permette di accorgersi a colpo d'occhio se ha perso qualcosa.

**Colonne aggiunte alla bozza di §7 per il profilo:** `profile_candidates.chiarimento_domanda` (senza la domanda, la risposta è incomprensibile a distanza di giorni) e `profile_candidates.versione_profilo` (quale versione ha assorbito il candidato: impedisce di riproporlo al modello ogni settimana, e permette di risalire dal profilo a ciò che l'ha originato). Lo stato guadagna `approvato`, come detto sopra.

**Dove il profilo viene usato, oggi.** Solo nel prompt del riassunto giornaliero: è l'unico posto in cui conoscere il proprietario cambia davvero l'uscita, e costa una chiamata al giorno invece di una per messaggio. Infilarlo anche nell'interprete vorrebbe dire pagare qualche centinaio di token su ogni messaggio per decidere cose come «aggiungi il latte alla lista», dove sapere che preferisce il backend non serve a niente — contro «minima spesa» di §1. Gli altri moduli lo useranno quando arriveranno (§8.6, §8.11).

### 8.5 Tracciamento spese
Due canali:
- **Testo libero**: "ho pagato 8€ la colazione da Bar Rossi" → estrazione strutturata (importo, luogo, categoria proposta).
- **Foto scontrino**: Claude (vision) legge lo scontrino, estrae voci e totale, propone una sintesi. **Prima di salvare sul Pi, il bot ti manda la sintesi per conferma/modifica** (esattamente come chiesto) — solo dopo la tua approvazione i dati entrano nel DB.

Le categorie sono **proposte e adattate dinamicamente da Claude nel tempo**: quando propone una categoria nuova, la confronta con quelle esistenti per evitare doppioni semantici (es. "Cibo" vs "Alimentari"), e resta comunque modificabile/unibile da dashboard.

**Stato attuale.** Entrambi i canali sono attivi. Una frase con dentro una cifra («ho pagato 8€ la colazione da Bar Rossi») entra **subito** nei conti con un bottone «Annulla», come task, lista e diario: chiedere un sì venti volte al giorno è il modo più sicuro di smettere di registrare le spese piccole. Una **foto** di scontrino passa da Claude vision, che ne estrae totale, luogo, data e voci, e diventa una spesa `da_confermare`: fuori dai totali finché non tocchi «Conferma», perché lì il modello legge dieci numeri da un'immagine. Della foto non si conserva nulla — restano il totale e le voci lette in `scontrino_raw_estratto` (§7). La categoria è una **seconda** chiamata, e solo a Claude, fatta dopo aver salvato la spesa: se non risponde, la spesa resta senza categoria invece di perdersi, e si sistema dalla dashboard.

Gli importi stanno nel database in **centesimi**, come interi: sommare float per centinaia di spese produce totali che non tornano per qualche centesimo, e su dei soldi un totale che non torna è un bug che si nota. La conversione a euro avviene una volta sola, al confine con l'API e col bot.

**Chi decide la categoria.** §6 divide il lavoro, e il codice lo fa rispettare invece di sperarci: *assegnare* una spesa a una categoria che esiste già è classificazione semplice e la fa DeepSeek nella stessa chiamata che interpreta il messaggio, ma una categoria **nuova** la propone solo Claude. Una categoria proposta dall'interprete che non esiste viene scartata: la descrizione dello schema chiede già di non inventarne, ma è una richiesta, non un vincolo, e senza il controllo «150 euro da Bricoman» apre una categoria «Bricoman» che poi resta lì per sempre. Il nome del negozio non è una categoria — sta già nel suo campo.

**La data di una spesa è quella in cui hai speso**, non quella in cui l'hai registrata: è quello che conta per i totali del mese. Vale per **entrambi** i canali: «ieri ho pagato 17 euro la spesa» si registra a ieri esattamente come uno scontrino datato ieri. A risolvere le espressioni relative — «ieri», «l'altro ieri», «sabato scorso», «il 3» — è il **modello**, non il codice: il contesto che riceve dice già che giorno è oggi, nome del giorno della settimana compreso (senza il quale «sabato scorso» non è calcolabile), mentre scrivere qui un parser dell'italiano vorrebbe dire inseguire per sempre le forme che uno può dire a voce e sbagliare in silenzio su quelle non previste. È la stessa strada che la `scadenza` di un task percorre già: una forma sola per la stessa cosa. Il codice però non si fida di ciò che riceve, e ne discendono due regole. Una data **nel futuro** è sempre un errore — di lettura su uno scontrino, di calcolo su una frase — e viene scartata: ogni vista finisce a oggi, quindi una spesa datata in avanti sarebbe scritta sul disco e invisibile ovunque, per sempre. E una spesa registrata adesso ma datata **prima del periodo** che stai guardando non sparisce: `/spese` la elenca a parte dicendo che non è nel totale, e ogni conferma — dello scontrino e della frase — dice sempre a che giorno è finita, quando non è oggi. Sul passato invece non c'è tetto: una spesa di tre mesi fa è legittima, e se il modello sbagliasse l'anno la conferma lo mostrerebbe («del 2 set 2025») con «Annulla» a un tap.

`GET /api/spese` e le sue due mutazioni non rispondono più `501`; sulla Home compaiono `spesaSettimana` e — solo se hai impostato `CUSTODE_BUDGET_SETTIMANALE` — il blocco «Spese · settimana». Senza budget quel blocco resta **assente**: una barra ha bisogno di un tetto, e inventarne uno sarebbe un giudizio su come spendi.

### 8.6 Tracciatore abitudini
- Definisci abitudini dinamiche con una frequenza target (es. "palestra, almeno 3 volte/settimana").
- Ogni giorno puoi scrivere in linguaggio libero cosa hai fatto/non fatto ("ho fatto x,y,z ma non a,b,c") → il parser (DeepSeek, task semplice di matching) aggiorna i log.
- Vista settimanale/mensile con aderenza (%) per abitudine, sia in dashboard che a richiesta via bot.
- **Report narrativo settimanale + mensile**: oltre ai numeri grezzi (calcolati in codice, senza LLM), un job genera un riepilogo testuale (Claude) che incrocia abitudini con diario/spese/sonno quando disponibili — il settimanale per un check ravvicinato, il mensile per i trend più lenti (es. un'abitudine che regge le prime settimane e poi cala).
- Tutto modificabile: puoi aggiungere, disattivare o cambiare target di un'abitudine in qualsiasi momento.

**Stato attuale.** §8.6 è completo: abitudini dinamiche, log da linguaggio libero, aderenza in codice, report narrativo settimanale e mensile. `GET /api/abitudini` e le sue mutazioni non rispondono più `501`, e la pagina della dashboard è viva.

**Le abitudini si creano dalla dashboard, si segnano dal bot.** Sono i due gesti con frequenze diversissime: aggiungere un'abitudine capita una volta ogni tanto e vuole un nome e un numero scelti con calma; segnarla capita ogni giorno e deve costare una frase. Il contratto guadagna quindi `POST /api/abitudini` e `PATCH /api/abitudini/:id` (nome, target, attiva), che la v1 della dashboard non aveva previsto ma che §8.6 richiede — «aggiungibili, disattivabili e modificabili in qualsiasi momento» deve pur succedere da qualche parte. Disattivare non cancella: i log restano, e riprendere un'abitudine ne riprende anche la storia invece di ricominciare da capo.

**Il matching del testo libero viaggia nella chiamata dell'interprete.** «Oggi palestra e lettura, ma niente meditazione» è la riga «log abitudini da testo libero» di §6, su DeepSeek — lo stesso provider che sta già interpretando il messaggio, quindi il compito entra nella stessa risposta strutturata invece di raddoppiare latenza e costo, come già fanno il diario e i segnali per il profilo. Il modello aggancia i nomi all'elenco delle abitudini attive che riceve nel contesto; **un nome che non esiste viene detto, non creato**: creare un'abitudine è una decisione, e prenderla al posto tuo perché hai nominato una cosa a caso riempirebbe l'elenco di righe che non hai voluto.

**Un «non fatto» non è un silenzio.** `habit_logs.fatto` può valere 0: «non ho fatto meditazione» è una cosa che hai detto, l'assenza di una riga è solo silenzio. All'aderenza non cambia niente — conta le righe a 1 — ma «Annulla» sa cosa disfare, e la differenza si vede quando si riguarda un giorno. Per lo stesso motivo annullare **toglie** il log invece di scrivere il contrario: disfare deve rimettere le cose com'erano.

**«Annulla» su un messaggio che segna tre abitudini le toglie tutte e tre.** Il `callback_data` di Telegram sta in 64 byte e non può portarsi dietro una lista di id, quindi il bottone indica l'**istante** di scrittura — uno solo per messaggio — e da lì si risalgono tutti i log nati insieme. Ed è anche la cosa giusta a prescindere dai byte: quella frase è stata un gesto solo, e disfarla a metà non è quello che si intende con «Annulla».

**I numeri sono aritmetica, non un modello** (§8.6 lo chiede). Aderenza = fatte / attese, col tetto al 100% perché una settimana da cinque su tre non deve coprire in media un'abitudine mai fatta; le attese del mese sono proporzionali ai **giorni trascorsi**, non a quelli del mese, altrimenti il 3 del mese direbbe solo che il mese è appena cominciato. La **striscia** è in giorni consecutivi e, se oggi non è ancora segnato, si conta fino a ieri: altrimenti alle nove del mattino ogni striscia sarebbe zero e il numero direbbe che ora è, non come stai andando. E ciò che la dashboard **evidenzia** è esattamente ciò che si legge nella riga: valutare «centrato» su un pro-rata mentre l'etichetta dice «1/3» darebbe una riga verde accanto a un numero che la smentisce.

**Le «proposte» che il contratto già prevedeva sono adeguamenti di target.** `AbitudiniData.proposta` e i suoi due endpoint esistevano nella v1 della dashboard senza che §8.6 li nominasse: sono il posto dove il report può dire «Palestra: da 3 a 2 volte a settimana» con la motivazione che l'ha fatta nascere. Nascono **solo dal mensile** — sette giorni non sono una tendenza, e §8.6 parla proprio di un'abitudine che regge le prime settimane e poi cala — e non cambiano niente da sole: il target si muove quando premi «Accetta», come ogni azione decisa da un modello (§8.1). Dopo un «no» la stessa abitudine non si ripropone per un mese, perché i numeri che l'avevano fatta nascere cambiano lentamente e ripetere la stessa domanda dopo un rifiuto è il modo più rapido perché smetta di essere letta. La colonna `tipo` esiste già in tabella, così una proposta di natura diversa (un'abitudine nuova suggerita dal diario) potrà arrivare senza una migrazione su dati veri.

**Il report è l'unica cosa che passa da Claude, e si conserva.** Riceve i numeri già calcolati più il diario e le spese dello stesso periodo, e il suo valore sta negli incroci — una settimana senza palestra accanto a un diario di serate in biblioteca dice qualcosa che i due elenchi separati non dicono. Il settimanale viaggia **dentro** il messaggio del riepilogo del diario invece che in uno suo: arriverebbe lo stesso giorno alla stessa ora, e due notifiche di fila sono due interruzioni per una cosa sola. Il mensile ha un job suo, il primo del mese. Entrambi restano salvati in `habit_reports` e compaiono nella pagina: un testo che vive solo dentro una notifica non si rilegge, e il mensile è proprio quello che serve rileggere.

**Colonne aggiunte alla bozza di §7:** `habit_logs.creato_il` (è l'istante su cui si aggancia «Annulla»), `habit_proposals` e `habit_reports` per intero — la bozza non prevedeva né le proposte né i resoconti, che sono però nel contratto della dashboard e in §8.6.

### 8.7 Spotify
OAuth una tantum, poi polling periodico su brano corrente / recenti, storico salvato nel DB.

### 8.8 Samsung Health
Samsung non offre un'API cloud pubblica per sviluppatori indipendenti (l'accesso diretto è riservato a partner selezionati). La via pratica: una piccola app companion Android che legge da **Health Connect** (dove Samsung Health scrive i dati) e li invia alla tua API sul Pi. Coerentemente con la tua priorità, i dati restano quindi sotto il tuo controllo: passano dal telefono al Pi, non a server Samsung/terzi aggiuntivi.

### 8.9 Email (rimandato)
Aperto deliberatamente: prima di collegarla vanno decisi scope OAuth minimo (sola lettura), quali mittenti/etichette includere, e se instradare sempre e solo su Claude per limitare a un solo fornitore i contenuti sensibili delle mail.

### 8.10 Calendario + motore di contesto
- **Calendario in sola lettura** (Google Calendar o feed iCal dell'università): sincronizzazione periodica, il bot non scrive mai sul calendario, solo legge. Ogni evento viene taggato per tipo (lezione, palestra, viaggio, altro) — l'IA può proporre il tag la prima volta, tu correggi se serve, resta poi fisso per gli eventi ricorrenti.
- **Regole di contesto** (`context_rules`), due origini:
  1. *Auto-proposte*: un job periodico cerca pattern nei dati storici (calendario, abitudini, orari in cui scrivi) e, appena trova un pattern che regge — anche una cosa semplice, subito, non solo nel report settimanale — ti propone una regola ("vuoi che ti ricordi la creatina quando vai in palestra?"). Approvi, rifiuti o modifichi; solo le approvate diventano attive.
  2. *Dettate da te*: puoi dire "questa cosa dimmela alle 19" o "dimmelo prima di [evento]" — diventa subito una regola attiva, senza bisogno di ulteriore conferma (l'hai già approvata scrivendola).
- **Tipi di trigger supportati**: `orario` (fisso), `prima_evento`, `dopo_evento`, `pattern` (generato dal motore stesso). Le regole già approvate vengono valutate/eseguite con logica pura (nessuna chiamata LLM, costo zero) — solo la *creazione* di nuove regole auto-proposte richiede ragionamento (Claude).
- Le regole restano sempre visibili/modificabili/disattivabili da dashboard, e si possono correggere a parole ("no, dopo lezione ci metto un'ora, non 30 minuti") — il feedback aggiorna la regola invece di crearne una nuova.
- **Inferenza "sei probabilmente a casa"**: fine dell'ultima lezione in calendario + un buffer configurabile (es. 30-45 min), usata ad esempio per non far partire il check-in universitario a lezione appena finita ma con un margine realistico.

### 8.11 Corsi universitari
- Un corso (`corsi`) ha nome, orario (collegato agli eventi calendario taggati "lezione"), data esame ed è collegato a un percorso `syllabus.md` nel tuo repo appunti su GitHub.
- **Sync appunti**: `git pull` schedulata (es. ogni notte) su una cartella montata in sola lettura sul Pi. Il bot non legge tutti i tuoi appunti, solo `syllabus.md` del corso interessato quando serve generare un piano di ripasso — mantiene i costi/tempi bassi.
- **Check-in serale**: quando il motore di contesto stima che sei probabilmente a casa dopo l'ultima lezione del giorno, il bot chiede quali lezioni hai seguito e se hai preso appunti (`lezioni_log`). Puoi comunque scrivere qualcosa anche prima, in qualsiasi momento — il check-in automatico è un promemoria in più, non l'unico modo di registrare le cose.
- In base alle tue risposte + `syllabus.md`, Claude genera un piano di cosa sistemare/ripassare, salvato come task collegate al corso (riuso del modulo 8.2, niente modulo nuovo da zero).

### 8.12 Meteo
Una chiamata al giorno a un servizio gratuito (es. Open-Meteo, nessuna chiave richiesta) — il dato grezzo non richiede LLM, viene solo incrociato col calendario e infilato nel digest mattutino (es. "hai lezione alle 9 e piove, porta l'ombrello"). Costo pressoché nullo.

### 8.13 Digest mattutino
Messaggio automatico la mattina (DeepSeek, composizione semplice) con: impegni/lezioni del giorno dal calendario, meteo, task aperti, eventuali promemoria da abitudini — così non devi chiedere tu ogni mattina.

## 9. Sicurezza

- Nessuna porta aperta sul router: tutto passa da Cloudflare Tunnel.
- Cloudflare Access davanti a dashboard e API: solo la tua identità autorizzata, da qualunque rete.
- Bot Telegram: whitelist sul tuo user ID Telegram, ogni altro mittente viene ignorato.
- Segreti solo in `.env` locale sul Pi, mai nel repo (`.gitignore` su `.env`, `*.db`, volumi).
- Container Docker con utenti non-root dove possibile, immagini pinnate per versione (niente `:latest`).
- **Autenticazione Cloudflare Access**: login OAuth (Google, o provider equivalente già in uso sul telefono) con policy ristretta esattamente alla tua email — un tap per entrare, categoricamente negato a chiunque altro. Durata sessione configurabile (es. 24h) sui dispositivi fidati per evitare login ripetuti. In alternativa resta disponibile l'OTP via email già in uso, equivalente in sicurezza, solo qualche secondo più lento.
- **Backup del DB**: job giornaliero nel worker verso il secondo disco del Pi, cifrato, con retention 7 copie giornaliere + 4 settimanali. **Fatto** (`worker/custode_worker/backup.py`), col runbook di restore in DEPLOY.md §7 che §11 richiede. Tre scelte prese costruendolo: la copia usa l'API `.backup()` di SQLite e non ferma nessun servizio (in WAL un `cp` potrebbe cogliere il database a metà transazione); senza `WORKER_BACKUP_CHIAVE` il backup **si fa lo stesso, in chiaro**, perché il rischio più probabile in casa non è il furto del disco ma la scheda che si rompe — e da quello protegge anche una copia in chiaro, purché si sappia di averla (l'estensione cambia e il worker lo ripete ad ogni avvio); il restore non sovrascrive mai il database in esercizio, scrive dove gli si dice e verifica l'integrità di ciò che esce, lasciando a te il passo di metterlo al suo posto a servizi fermi.
- **Resilienza elettrica**: un UPS/power bank per il Pi è la protezione con miglior rapporto costo/beneficio contro la causa di disservizio più comune (blackout), prima ancora di pensare a hardware di backup.

## 10. Testing & CI/CD

- **Unit test**: parser (spese, abitudini, lista spesa), logica del router DeepSeek/Claude, funzioni DB.
- **Integration test**: endpoint API contro un DB di test in container dedicato (`docker-compose.test.yml`).
- **GitHub Actions**: ad ogni push → lint + test + **build delle immagini**; il deploy sul Pi parte solo se la pipeline è verde. Il job delle immagini costruisce i quattro target del Dockerfile e poi ne *avvia* ciascuno per importare il proprio modulo: costruire dimostra solo che i layer si applicano, non che il servizio abbia le dipendenze che importa. È il buco da cui erano passati tre difetti del Dockerfile arrivati fino al Pi (README fuori dal contesto di build, curl mancante, librerie condivise non copiate), e serve in particolare al target `worker`, che usa `custode_bot.risposte` senza installare `python-telegram-bot`.
- **Smoke test post-deploy**: endpoint di health-check chiamato subito dopo ogni deploy, rollback automatico se fallisce.
- **Staging locale**: un profilo Docker Compose separato per provare le modifiche prima di "andare in produzione" sul tunnel pubblico.

## 11. Documentazione richiesta nel repo

- `README.md`: overview del progetto.
- `ARCHITECTURE.md`: questo documento, mantenuto aggiornato.
- `DEPLOY.md`: passo-passo per configurare Pi, Docker, Cloudflare Tunnel e Access da zero.
- `.env.example`: ogni variabile richiesta, senza valori reali.
- Runbook di backup/restore del database.

## 12. Roadmap a fasi

1. **Scheletro**: bot Telegram (testo+voce) + Whisper locale + router DeepSeek/Claude + DB SQLite + Docker Compose + Cloudflare Tunnel/Access + CI base.
2. **Task/promemoria + lista della spesa** (moduli semplici, valore d'uso immediato).
3. **Diario** (flusso trascrizione → riassunto → approvazione → salvataggio, + job settimanale). *Fatta, canale passivo e job settimanale compresi.*
4. **Tracciamento spese** (testo + foto scontrino con conferma prima del salvataggio). *Fatta.*
5. **Tracciatore abitudini** (dinamico, log da linguaggio libero, statistiche di aderenza + report settimanale/mensile).
6. **Calendario + motore di contesto** (sync in sola lettura, tagging eventi, regole dettate da te, poi le auto-proposte basate su pattern).
7. **Corsi universitari** (sync appunti da GitHub, check-in serale, piano di ripasso da syllabus.md).
8. **Meteo + digest mattutino**.
9. **Dashboard completa** su Cloudflare Pages.
10. **Spotify.**
11. **Samsung Health** (app companion Health Connect → Pi).
12. **Email** (dopo definizione puntuale di scope e privacy).

## 13. Decisioni di rifinitura

**Cloudflare Access.** Login OAuth (Google o provider equivalente già usato sul telefono) come identity provider, con policy ristretta esattamente alla tua email: un tap per entrare, negazione categorica per chiunque altro. Sessione persistente (es. 24h) sui dispositivi fidati. L'OTP via email attualmente in uso resta un'alternativa equivalente in sicurezza, solo un po' più lenta per l'attesa della mail — nessuna delle due opzione riduce la protezione, solo la comodità.

**Backup DB.** Sul secondo disco già presente sul Pi, cifrato, con retention 7 giornalieri + 4 settimanali (vedi sezione 9).

**Whisper.** Modello `base` quantizzato (q5_1): ~1GB di RAM, trascrizione di un vocale di 30-60s in pochi secondi su Pi 5, thread limitati per non competere con bot/API. Scelto perché con parlato pulito in ambiente silenzioso (il tuo caso) l'accuratezza è già solida, e i modelli più grandi (`small`+) servirebbero soprattutto a compensare rumore di fondo che qui non è un problema. Parametro facilmente cambiabile in futuro se serve più accuratezza.

**Latenza da fuori casa vs disponibilità.** Sono due problemi distinti:
- *Latenza*: con Cloudflare Tunnel la risposta a un comando semplice arriva in meno di un secondo anche con upload di casa modesto; per i vocali il tempo percepito è quasi tutto whisper (pochi secondi), non la rete.
- *Disponibilità*: se internet di casa o il Pi vanno giù, tutto è irraggiungibile — questo è il vero limite dell'architettura "single-Pi".

**Backup device (Pi Zero / mini PC), quando ha senso.** Non ora. Il Pi 5 basta abbondantemente per un utente singolo, e la ridondanza reale richiederebbe una seconda connessione internet indipendente (un secondo device sullo stesso ISP di casa non protegge da un blackout dell'ISP) più sincronizzazione del DB tra primario e backup — complessità sproporzionata per un tool personale. Prima mossa, se in pratica si presentano troppi disservizi: un **UPS/power bank per il Pi**, che copre la causa più comune (blackout elettrico) a costo molto più basso. Un secondo device come cold spare resta un'opzione solo per guasto hardware del Pi primario, un problema diverso.

**Email.** Ancora da decidere — in attesa di approfondimento su scope OAuth e policy privacy prima di collegare il modulo.
