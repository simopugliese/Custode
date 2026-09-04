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
`/api/abitudini` (+ `POST`, `PATCH`, `log`, `proposta/accetta|rifiuta`), e
`GET /api/health` per lo smoke test post-deploy (§10).

Tutto il resto risponde `501` finché non arriva il suo modulo (§8.10-§8.13).

Le abitudini (§8.6) sono l'unico modulo che si *gestisce* da qui e non da
Telegram: aggiungerne una vuole un nome e un numero scelti con calma, segnarla
capita ogni giorno e costa una frase al bot. Nessun numero della pagina passa da
un modello — aderenza, strisce e costanza sono aritmetica su insiemi di date,
in `custode_core.dominio.abitudini`.

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
