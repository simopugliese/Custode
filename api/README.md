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
`PATCH`), `/api/lista-spesa` (+ `POST`, `PATCH`, `svuota-presi`), e
`GET /api/health` per lo smoke test post-deploy (§10).

Tutto il resto risponde `501` finché non arriva il suo modulo (§8.4-§8.13).

## Avvio locale

```bash
uv run uvicorn custode_api.main:app --reload
curl localhost:8000/api/health
```
