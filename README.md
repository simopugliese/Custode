# Custode

Assistente personale self-hosted: si usa da **Telegram** (testo o vocale) e si
controlla da una **dashboard web**. Gira su un Raspberry Pi 5 di casa; i dati
restano lì e non finiscono su servizi cloud di terzi — Cloudflare fa solo da
tramite sicuro, non da depositario.

Il progetto completo — visione, architettura, schema dati, moduli, sicurezza,
roadmap — è in **[ARCHITECTURE.md](./ARCHITECTURE.md)**, che resta la fonte di
verità per ogni decisione. I riferimenti tipo "§8.2" nel codice e nei README di
cartella puntano lì.

## Com'è fatto

```
/api          backend FastAPI — il contratto REST è in dashboard/API.md
/bot          bot Telegram (testo + voce)                    — da fare, fase 3
/router       scelta del modello DeepSeek / Claude (§6)      — da fare, fase 4
/worker       job schedulati: scadenze, riepiloghi, backup   — da fare
/core         codice condiviso: configurazione e accesso SQLite
/dashboard    frontend React + Vite (deploy su Cloudflare Pages)
/tests        unit + integration test
```

`core/` non è nell'elenco di §5: è la risposta al fatto che api, bot, router e
worker devono vedere lo stesso schema e la stessa configurazione, e duplicarli
in quattro punti sarebbe l'errore più facile da fare.

## Stato

| Pezzo | Stato |
|---|---|
| Dashboard (9 pagine, tema giorno/notte, chiamate API reali) | fatto |
| Contratto REST (`dashboard/API.md`) | fatto |
| Scheletro repo, configurazione, SQLite in WAL, `GET /api/health`, CI | fatto |
| Endpoint API con persistenza reale (task, lista spesa) | prossimo |
| Bot Telegram, router DeepSeek/Claude, Whisper, diario, spese, abitudini | da fare |

La dashboard oggi mostra stato di caricamento/errore finché il backend non
espone gli endpoint di pagina: è il comportamento previsto, non un bug.

## Sviluppo locale

Serve [uv](https://docs.astral.sh/uv/) (gestisce Python e dipendenze).

```bash
cp .env.example .env          # riempi i valori locali; .env non è versionato
uv sync                       # crea .venv dalle versioni bloccate in uv.lock
uv run uvicorn custode_api.main:app --reload
curl localhost:8000/api/health
```

Controlli, gli stessi che girano in CI:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

In container, come sul Pi:

```bash
docker compose up --build -d          # API su 127.0.0.1:8000
docker compose -f docker-compose.test.yml run --rm tests
```

La dashboard si avvia a parte, vedi [`dashboard/README.md`](./dashboard/README.md):
punta `VITE_API_BASE_URL` a `http://localhost:8000` e aggiungi la stessa origine
a `CUSTODE_CORS_ORIGINS` nel `.env`.

## Deploy

Passo passo in **[DEPLOY.md](./DEPLOY.md)**: Pi, Docker, Cloudflare Tunnel e
Access, dashboard su Pages.

## Segreti

Nulla di segreto entra nel repo: `.env`, database e credenziali sono in
`.gitignore`. `.env.example` documenta ogni variabile con soli placeholder
(§5, §9).

## Cartelle di origine

`project/` e `chats/` contengono il bundle esportato da Claude Design (i
prototipi HTML/CSS della dashboard e la conversazione da cui sono nati). Sono
materiale di riferimento storico: il codice vivo della dashboard è in
`dashboard/`.
