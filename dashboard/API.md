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
  (compatibile con FastAPI di default).
- **Le voci "piano di ripasso" sono task**: come da §8.11 del documento di
  progettazione, i task generati da un piano di ripasso sono normali righe
  di `tasks` collegate al corso — stesso endpoint `PATCH /api/task/:id`
  usato ovunque, nessun endpoint dedicato.

I tipi TypeScript esatti di ogni payload sono in `src/types/api.ts` — questo
file ne descrive solo la forma a endpoint per endpoint.

## Home

`GET /api/home` → `HomeData`
Riepilogo "di oggi": task, calendario, abitudini, spese della settimana,
lista della spesa, conteggio automazioni proposte.

## Diario

`GET /api/diario?vista=timeline|settimane|mesi` → `DiarioData`
`POST /api/diario/:id/approva` → `VoceDiario`
`POST /api/diario/:id/scarta` → `204`
(la modifica testo di una voce non ha endpoint dedicato in questa v1 della
dashboard: il pulsante "Modifica" apre un'interazione da rifinire più avanti)

## Lezioni e corsi

`GET /api/lezioni?vista=settimana|mese` → `LezioniData`
`POST /api/lezioni/piani/:id/rigenera` → `PianoRipasso`
`POST /api/lezioni/piani/:id/manda-al-bot` → `204`

## Task

`GET /api/task?vista=scadenza|progetto|completati` → `TaskData`
`PATCH /api/task/:id` body `{ fatto?: boolean, rinviaGiorni?: number }` → `TaskItem`
`POST /api/task` body `{ titolo: string, scadenza?: string }` → `TaskItem`

## Lista della spesa

`GET /api/lista-spesa?ordina=reparto|aggiunta` → `ListaSpesaData`
`PATCH /api/lista-spesa/:id` body `{ preso: boolean }` → `ShoppingItem`
`POST /api/lista-spesa` body `{ nome: string, quantita?: string, reparto?: string }` → `ShoppingItem`
`POST /api/lista-spesa/svuota-presi` → `204`

## Spese

`GET /api/spese?periodo=settimana|mese|anno` → `SpeseData`
`POST /api/spese/:id/conferma` body `{ categoria?: string }` → `Movimento`
`POST /api/spese` body `{ importo: number, descrizione: string, categoria?: string }` → `Movimento`

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
comando come «segna 8€ colazione al bar» si riflette appena il backend lo
elabora.
