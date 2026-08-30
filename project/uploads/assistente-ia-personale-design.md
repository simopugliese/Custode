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
  /router         # logica di scelta DeepSeek/Claude
  /worker         # job schedulati (riepilogo settimanale, backup, reminder)
  /dashboard      # frontend (build separata, deploy su Pages)
  /tests          # unit + integration test
  docker-compose.yml
  docker-compose.test.yml
  .env.example    # SOLO placeholder, mai valori reali
  .gitignore      # .env, *.db, volumi docker
  ARCHITECTURE.md
  DEPLOY.md
  README.md
```

Tutto su GitHub tranne: file `.env` reale, il database, e qualunque credenziale. Il `.env.example` documenta ogni variabile richiesta senza esporre segreti.

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

## 7. Schema dati (bozza)

```
tasks(id, titolo, note, scadenza, stato, creato_il)
shopping_list(id, item, quantita, aggiunto_il, comprato)

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

**Il profilo non si accoda, si riscrive (rifusione).** Se ogni settimana si limitasse ad aggiungere testo, `profile_document` crescerebbe all'infinito: diventerebbe costoso da passare ad ogni chiamata e via via meno utile (rumore che copre segnale). Il job settimanale quindi non accoda: Claude legge la versione attuale del profilo + i candidati approvati della settimana e **produce una nuova versione compatta** che integra le novità e scarta ciò che è superato o ridondante — il profilo resta sempre snello (poche centinaia di parole) e sempre più su misura per te, non un log infinito. Ogni versione resta comunque salvata (`profile_document` versionato), quindi è sempre possibile tornare indietro se una riscrittura perde qualcosa di importante.

### 8.5 Tracciamento spese
Due canali:
- **Testo libero**: "ho pagato 8€ la colazione da Bar Rossi" → estrazione strutturata (importo, luogo, categoria proposta).
- **Foto scontrino**: Claude (vision) legge lo scontrino, estrae voci e totale, propone una sintesi. **Prima di salvare sul Pi, il bot ti manda la sintesi per conferma/modifica** (esattamente come chiesto) — solo dopo la tua approvazione i dati entrano nel DB.

Le categorie sono **proposte e adattate dinamicamente da Claude nel tempo**: quando propone una categoria nuova, la confronta con quelle esistenti per evitare doppioni semantici (es. "Cibo" vs "Alimentari"), e resta comunque modificabile/unibile da dashboard.

### 8.6 Tracciatore abitudini
- Definisci abitudini dinamiche con una frequenza target (es. "palestra, almeno 3 volte/settimana").
- Ogni giorno puoi scrivere in linguaggio libero cosa hai fatto/non fatto ("ho fatto x,y,z ma non a,b,c") → il parser (DeepSeek, task semplice di matching) aggiorna i log.
- Vista settimanale/mensile con aderenza (%) per abitudine, sia in dashboard che a richiesta via bot.
- **Report narrativo settimanale + mensile**: oltre ai numeri grezzi (calcolati in codice, senza LLM), un job genera un riepilogo testuale (Claude) che incrocia abitudini con diario/spese/sonno quando disponibili — il settimanale per un check ravvicinato, il mensile per i trend più lenti (es. un'abitudine che regge le prime settimane e poi cala).
- Tutto modificabile: puoi aggiungere, disattivare o cambiare target di un'abitudine in qualsiasi momento.

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
- **Backup del DB**: cron giornaliero automatico verso il secondo disco del Pi, cifrato, con retention 7 copie giornaliere + 4 settimanali.
- **Resilienza elettrica**: un UPS/power bank per il Pi è la protezione con miglior rapporto costo/beneficio contro la causa di disservizio più comune (blackout), prima ancora di pensare a hardware di backup.

## 10. Testing & CI/CD

- **Unit test**: parser (spese, abitudini, lista spesa), logica del router DeepSeek/Claude, funzioni DB.
- **Integration test**: endpoint API contro un DB di test in container dedicato (`docker-compose.test.yml`).
- **GitHub Actions**: ad ogni push → lint + test; il deploy sul Pi parte solo se la pipeline è verde.
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
3. **Diario** (flusso trascrizione → riassunto → approvazione → salvataggio, + job settimanale).
4. **Tracciamento spese** (testo + foto scontrino con conferma prima del salvataggio).
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
