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
| `TELEGRAM_BOT_TOKEN` | il token che dà @BotFather quando crei il bot |
| `TELEGRAM_ALLOWED_USER_ID` | il tuo user ID Telegram numerico — te lo dice @userinfobot |
| `ROUTER_DEEPSEEK_API_KEY` | chiave DeepSeek: serve al linguaggio libero e ai vocali (§6) |
| `ROUTER_ANTHROPIC_API_KEY` | chiave Anthropic: nessun modulo la usa ancora, può restare vuota |

Il token del tunnel resta commentato finché non arriva la sua fase.

Senza le chiavi del router, comandi e bottoni del bot funzionano lo stesso: si
perde solo il linguaggio libero, e il bot lo dice invece di fallire in silenzio.

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

## 7. Backup e restore del database **[da fare]**

Il database è un unico file dentro il volume Docker `custode-data`. Il runbook
completo — cron giornaliero verso il secondo disco, cifratura, retention 7
giornalieri + 4 settimanali (§9) — si scrive insieme al job di backup in
`worker/`, per non documentare una procedura che ancora non esiste.

Nel frattempo, copia manuale coerente (`.backup` non richiede di fermare il
servizio e rispetta il WAL):

```bash
docker compose exec api python -c \
  "import sqlite3; s=sqlite3.connect('/data/custode.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp api:/data/backup.db ./custode-backup-$(date +%F).db
docker compose exec api rm /data/backup.db
```

Per ripristinare: fermare l'API (`docker compose stop api`), rimettere il file
al posto di `custode.db` nel volume, riavviare e controllare `/api/health`.
