# DEPLOY — dal Pi appena acceso al sistema raggiungibile da fuori

Procedura per mettere in piedi Custode da zero. Copre quello che esiste oggi
(API + database); le sezioni marcate **[da fare]** si riempiono quando arriva
il pezzo corrispondente. Riferimenti a [ARCHITECTURE.md](./ARCHITECTURE.md).

## 0. Cosa serve

- Raspberry Pi 5 con Raspberry Pi OS a 64 bit (arm64), SSD o microSD affidabile.
- Un dominio gestito da Cloudflare (piano gratuito) — serve per Tunnel e Access.
- Account Cloudflare con Zero Trust attivo (gratuito fino a 50 utenti).
- Un UPS o power bank per il Pi: è la protezione col miglior rapporto
  costo/beneficio contro i blackout (§13).

## 1. Preparare il Pi

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git curl
```

Docker Engine + plugin Compose (script ufficiale, poi utente non-root):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"    # riconnettiti perché abbia effetto
docker compose version
```

Fuso orario coerente con i job schedulati:

```bash
sudo timedatectl set-timezone Europe/Rome
```

## 2. Clonare e configurare

```bash
git clone https://github.com/simopugliese/custode.git ~/custode
cd ~/custode
cp .env.example .env
```

Apri `.env` e compila le variabili. Quelle già usate oggi:

| Variabile | Valore sul Pi |
|---|---|
| `CUSTODE_AMBIENTE` | `production` |
| `CUSTODE_DB_PATH` | `/data/custode.db` (percorso **dentro** il container) |
| `CUSTODE_TIMEZONE` | `Europe/Rome` |
| `CUSTODE_CORS_ORIGINS` | l'indirizzo della dashboard su Pages, es. `https://custode.pages.dev` |
| `CUSTODE_BUDGET_SETTIMANALE` | quanto conti di spendere in una settimana, in euro. **Lasciala vuota** se non ne vuoi uno: la Home non disegna il blocco «Spese · settimana», e il totale speso resta comunque visibile |
| `TELEGRAM_BOT_TOKEN` | il token che dà @BotFather quando crei il bot |
| `TELEGRAM_ALLOWED_USER_ID` | il tuo user ID Telegram numerico — te lo dice @userinfobot |
| `ROUTER_DEEPSEEK_API_KEY` | chiave DeepSeek: serve al linguaggio libero e ai vocali (§6) |
| `ROUTER_ANTHROPIC_API_KEY` | chiave Anthropic: riassunto del diario, riepilogo settimanale, profilo (§8.4), categorie e lettura degli scontrini (§8.5) |

Il token del tunnel resta commentato finché non arriva la sua fase.

Senza le chiavi del router, comandi e bottoni del bot funzionano lo stesso: si
perdono il linguaggio libero (DeepSeek) e tutto ciò che passa da Claude —
riassunto del diario, riepilogo settimanale, profilo, e la lettura degli
scontrini — e il bot lo dice invece di fallire in silenzio. Quello che avevi già
raccontato resta comunque salvato, e i segnali approvati aspettano la rifusione
successiva. Le spese scritte a parole continuano a entrare nei conti anche
senza Claude: restano solo senza categoria, e gliene si dà una dalla dashboard.

Il bot non parte senza token **e** senza user ID: lo dice nei log e si ferma,
invece di restare in ascolto con la whitelist vuota.

`.env` non deve mai finire nel repo: è in `.gitignore`, verificalo prima di
ogni commit con `git status`.

## 3. Avviare

```bash
docker compose up --build -d
docker compose ps
curl -s localhost:8000/api/health
```

Risposta attesa:

```json
{"stato":"ok","versione":"0.1.0","ambiente":"production","db":"ok","migrazioni":"ok"}
```

Se qualcosa non va l'endpoint risponde **503** dicendo cosa:

- `"db":"irraggiungibile"` → il volume `custode-data` non è montato, o non è
  scrivibile dall'utente `custode` (uid 10001) del container.
- `"migrazioni":"fallite"` → lo schema non è aggiornato; il motivo preciso è
  nei log (`docker compose logs api`). L'API parte lo stesso, in stato
  degradato, apposta per poterlo dire qui invece di limitarsi a morire.

Le migrazioni dello schema girano da sole ad ogni avvio e sono idempotenti:
non c'è nessun passo manuale da ricordare quando si aggiorna.

L'API è pubblicata solo su `127.0.0.1:8000`: nessun'altra macchina della rete di
casa la vede, e sul router non va aperta nessuna porta (§2, §9). Anche il bot
non espone niente: in long polling è lui a chiamare Telegram.

### Provare il bot

Con lo stack in piedi, da Telegram: `/aiuto` deve rispondere con l'elenco dei
comandi, `/nuovo Prova` deve creare un task che compare anche nella dashboard.

```bash
docker compose logs -f bot
```

### Provare il diario

Da Telegram, racconta qualcosa della giornata («stamattina biblioteca, capitolo
3 finalmente chiaro») — il bot risponde «Annotato nel diario di oggi» con un
bottone per annullare. Poi `/diario` chiude la giornata e propone il riassunto
scritto da Claude, con Approva / Modifica / Scarta. Solo dopo **Approva** la
voce compare nella pagina Diario della dashboard.

Se manca `ROUTER_ANTHROPIC_API_KEY`, `/diario` lo dice e il materiale resta
salvato: si riprova dopo aver messo la chiave, senza aver perso niente.

### Provare il profilo e il job settimanale

Il worker (`docker compose logs -f worker`) dice all'avvio quando farà scattare
il riepilogo — di norma la domenica alle 21:00, configurabile con
`WORKER_GIORNO_RIEPILOGO` e `WORKER_ORA_RIEPILOGO`.

`/profilo` mostra cosa Custode ha capito di te e quanti segnali sono in attesa.
All'inizio è vuoto: si riempie da solo con quello che gli racconti.

Per non aspettare domenica, si può spostare l'orario avanti di qualche minuto
nel `.env` e riavviare il solo worker:

```bash
docker compose up -d worker
docker compose logs -f worker
```

Il job si segna come fatto per quella settimana, quindi non si ripete: per
riprovarlo davvero da capo bisogna togliere la riga dal registro.

```bash
docker compose exec api python -c 'import sqlite3; c = sqlite3.connect("/data/custode.db"); c.execute("DELETE FROM job_runs WHERE nome = ?", ("riepilogo_settimanale",)); c.commit()'
```

### Provare i vocali

Il primo `docker compose build` compila whisper.cpp e scarica il modello: su un
Pi 5 richiede diversi minuti, ma succede una volta sola (il layer resta in
cache). Poi:

```bash
docker compose logs -f whisper          # deve dire modello_presente
docker compose exec whisper python -c \
  "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8100/health').read())"
```

Da Telegram, manda un vocale: il bot risponde con la trascrizione fra
virgolette e poi con quello che ha fatto. Se la trascrizione è giusta ma
l'azione no, il problema è nell'interpretazione (router); se è sbagliata la
trascrizione, è Whisper — ed è per questo che il bot le mostra entrambe.

Per cambiare modello (più accurato, più lento):

```bash
docker compose build --build-arg WHISPER_MODEL=small-q5_1 whisper
```

All'avvio il log dice qual è l'unico mittente ammesso. Se scrivi da un altro
account non ricevi risposta — è il comportamento voluto (§9) — e nel log compare
una riga `messaggio ignorato da un mittente non autorizzato`.

## 4. Cloudflare Tunnel + Access **[da fare — fase 8]**

In sintesi, quando ci arriviamo:

1. In Cloudflare Zero Trust → Networks → Tunnels, creare un tunnel e copiarne
   il token in `CLOUDFLARE_TUNNEL_TOKEN` nel `.env`.
2. Aggiungere il servizio `cloudflared` a `docker-compose.yml`, con un public
   hostname (es. `api.tuodominio.it`) che punta a `http://api:8000` sulla rete
   interna di Compose.
3. In Access → Applications, creare un'applicazione self-hosted su quello
   stesso hostname con una policy `Allow` ristretta esattamente alla propria
   email, sessione 24h (§9, §13).
4. Verificare da rete esterna: senza login l'endpoint deve rispondere con la
   pagina di Access, mai con i dati.

## 5. Dashboard su Cloudflare Pages **[da fare — fase 9]**

Build da `dashboard/` (`npm run build`, output in `dist/`), progetto Pages
collegato al repo, variabile d'ambiente `VITE_API_BASE_URL` puntata
all'hostname del tunnel. Dettagli in [`dashboard/README.md`](./dashboard/README.md).

## 6. Aggiornare una versione già in esecuzione

```bash
cd ~/custode
git pull
docker compose up --build -d
curl -sf localhost:8000/api/health || echo "SMOKE TEST FALLITO"
```

Se lo smoke test fallisce, tornare alla versione precedente:

```bash
git checkout <commit-precedente>
docker compose up --build -d
```

L'automazione di questo passaggio (deploy solo a pipeline verde + rollback
automatico) arriva con la fase CI/CD, §10.

## 7. Backup e restore del database

Il job gira ogni notte dentro il worker (§9): copia coerente del database,
compressione, cifratura se gli hai dato una chiave, e pulizia dei vecchi con
retention **7 giornalieri + 4 settimanali**.

La copia usa l'API `.backup()` di SQLite e **non ferma nessun servizio**: in
modalità WAL le scritture stanno in un file a parte, e un `cp` a mano potrebbe
cogliere il database a metà di una transazione.

### Configurare

| Variabile | Cosa fa |
|---|---|
| `CUSTODE_BACKUP_HOST` | **Dove finiscono i backup sul Pi.** Default `./backup`, che sta sulla stessa scheda del database: va bene per provare, non protegge dal guasto che conta. Puntalo al secondo disco, es. `/mnt/backup` |
| `WORKER_ORA_BACKUP` | Ora locale, default `03:30` |
| `WORKER_BACKUP_CHIAVE` | Chiave Fernet. **Vuota = backup in chiaro** |

Generare la chiave:

```bash
docker compose run --rm worker python -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Mettila in `.env` come `WORKER_BACKUP_CHIAVE=...` **e conservane una copia
fuori dal Pi** — in un gestore di password, non accanto ai backup. Un backup
che non sai aprire non è un backup, e se perdi la chiave non c'è niente da
fare: i file cifrati diventano rumore.

Senza chiave il backup si fa lo stesso, non cifrato: il rischio più probabile
in casa è la scheda che si rompe, e da quello protegge anche una copia in
chiaro. Lo riconosci dall'estensione (`.db.gz` invece di `.db.gz.enc`) e il
worker te lo ripete ad ogni avvio:

```
WARNING  WORKER_BACKUP_CHIAVE non impostata: i backup del database NON sono cifrati
```

### Controllare che ci siano

```bash
docker compose exec worker python -m custode_worker.ripristino --elenco
```

```
Backup in /backup, dal più recente:

  2026-09-06     124.3 kB  cifrato     custode-2026-09-06.db.gz.enc
  2026-09-05     123.8 kB  cifrato     custode-2026-09-05.db.gz.enc
  ...
Spazio libero: 28114 MB
```

Un backup riuscito **non manda notifiche**: se ne arrivasse una ogni giorno,
smetterebbe di voler dire qualcosa. Uno fallito finisce nei log come `WARNING`
e non viene segnato come fatto, quindi al giro dopo si riprova.

### Ripristinare

Il restore **non tocca il database in esercizio**: scrive dove gli dici, e sei
tu a metterlo al suo posto a servizi fermi. Ci pensa il comando a decifrare,
decomprimere e verificare l'integrità di quello che esce.

**1.** Scegli il backup e scrivilo da qualche parte:

```bash
docker compose exec worker python -m custode_worker.ripristino \
  /backup/custode-2026-09-06.db.gz.enc /data/ripristinato.db
```

Se dice `integrità ok`, il file è un database valido. Se dice altro, **fermati
qui**: prova un backup più vecchio invece di andare avanti.

**2.** Ferma i servizi che scrivono e metti il file al suo posto:

```bash
docker compose stop api bot worker
docker compose run --rm --entrypoint sh worker -c \
  "rm -f /data/custode.db /data/custode.db-wal /data/custode.db-shm \
   && mv /data/ripristinato.db /data/custode.db"
```

I file `-wal` e `-shm` vanno tolti insieme al database: sono le scritture non
ancora consolidate di quello *vecchio*, e lasciarli accanto a uno nuovo lo
corromperebbe.

**3.** Riparti e verifica:

```bash
docker compose up -d
curl -s localhost:8000/api/health
```

Deve rispondere `"stato":"ok"` con `"migrazioni":"ok"`. Le migrazioni girano da
sole: se il backup era di una versione più vecchia dello schema, viene portato
in pari all'avvio.

### Provalo prima di averne bisogno

Un restore non provato non è un piano. Una volta, subito:

```bash
docker compose exec worker python -m custode_worker.ripristino \
  /backup/<l-ultimo>.db.gz.enc /data/prova.db
docker compose exec worker python -c \
  "import sqlite3; c = sqlite3.connect('/data/prova.db'); \
   print(c.execute('SELECT count(*) FROM diary_entries').fetchone())"
docker compose exec worker rm /data/prova.db
```

Se quel conteggio è quello che ti aspetti, il backup funziona davvero.

### Portarne una copia fuori casa

§3 suggerisce anche una copia su uno storage esterno a tua scelta. I file sono
già cifrati (se hai messo la chiave), quindi possono stare ovunque:

```bash
rsync -av /mnt/backup/ altrove:/custode-backup/
```

Non c'è un job che lo fa: è una scelta tua su *dove*, e inchiodarla nel codice
significherebbe decidere al posto tuo.
