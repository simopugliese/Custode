# api — backend FastAPI

Il backend che serve la dashboard e, più avanti, la logica di dominio comune
al bot (ARCHITECTURE.md §4). Tutti gli endpoint stanno sotto `/api`, come da
contratto in [`../dashboard/API.md`](../dashboard/API.md).

- `custode_api/main.py` — costruzione dell'app, CORS, migrazioni all'avvio,
  `GET /api/health`.
- `custode_api/schemi.py` — i modelli di risposta, in camelCase come il contratto.
- `custode_api/dipendenze.py` — impostazioni, connessione per richiesta, "adesso".
- `custode_api/rotte/` — una rotta per area; `non_attivi.py` raccoglie i moduli
  che ancora non esistono e risponde `501` dicendo quale manca.

La logica di dominio non sta qui ma in `core/custode_core/dominio/`: la userà
identica anche il bot Telegram.

## Stato

Attivi con dati reali su SQLite: `GET /api/home`, `/api/task` (+ `POST`,
`PATCH`), `/api/lista-spesa` (+ `POST`, `PATCH`, `svuota-presi`),
`/api/diario` (+ `approva`, `scarta`), `/api/spese` (+ `POST`, `PATCH`, `DELETE`, `conferma`, `categorie`),
`/api/abitudini` (+ `POST`, `PATCH`, `log`, `proposta/accetta|rifiuta`),
`/api/calendario` (+ `PATCH` per correggere un tag, e `tipi` in `POST`,
`PATCH`, `DELETE`), `/api/impostazioni` (+ `PATCH`), `/api/regole` (+ `PATCH`, `approva`, `scarta`),
`/api/assistente/messaggio`, e `GET /api/health` per lo smoke test post-deploy
(§10).

Resta a `501` solo il modulo dei corsi (`/api/lezioni`, §8.11).

Le regole di contesto (§8.10) non si **creano** da qui: si scrivono a parole,
dalla barra «A Custode» o dal bot, perché è lo stesso interprete. Questa rotta
serve a guardare cosa c'è, metterlo in pausa e toglierlo.

Le abitudini (§8.6) sono l'unico modulo che si *gestisce* da qui e non da
Telegram: aggiungerne una vuole un nome e un numero scelti con calma, segnarla
capita ogni giorno e costa una frase al bot. Nessun numero della pagina passa da
un modello — aderenza, strisce e costanza sono aritmetica su insiemi di date,
in `custode_core.dominio.abitudini`.

I **tipi di evento** del calendario (§8.10, pezzo 6) sono l'altro modulo che si
gestisce da qui: `POST|PATCH|DELETE /api/calendario/tipi`. Stanno sotto
`/api/calendario` e non sotto le impostazioni perché i tipi si guardano dove si
vedono gli impegni — è nel menu di correzione che ci si accorge che ne manca
uno. Lo `slug` nell'URL è l'identificatore, e non cambia mai: rinominare un tipo
è un `PATCH` che tocca una riga sola e nessun evento.

Le **impostazioni** (§8) mandano solo le manopole che girano qualcosa: il
contratto ne ha di più — digest mattutino, ore di silenzio, approvazioni — ma
nessuno di quei moduli esiste, e un interruttore che non interrompe è peggio di
uno assente. Nessun segreto passa di qui: `connessioni` dice cosa è collegato e
quale variabile manca quando non lo è, mai il suo valore.

Diario e spese si *riempiono* da Telegram, non da qui (§8.1): queste rotte
servono a rileggerli e a smaltire quello che è rimasto in sospeso — le bozze da
approvare, gli scontrini letti da confermare. Le bozze si mostrano
sempre, anche fuori dal periodo della vista — altrimenti una lasciata in
sospeso a fine mese diventerebbe irraggiungibile il giorno dopo.

## Avvio locale

```bash
uv run uvicorn custode_api.main:app --reload
curl localhost:8000/api/health
```
