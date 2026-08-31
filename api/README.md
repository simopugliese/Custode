# api — backend FastAPI

Il backend che serve la dashboard e, più avanti, la logica di dominio comune
al bot (ARCHITECTURE.md §4). Tutti gli endpoint stanno sotto `/api`, come da
contratto in [`../dashboard/API.md`](../dashboard/API.md).

- `custode_api/main.py` — costruzione dell'app, CORS, `GET /api/health`.

## Stato

Presente: health check (serve allo smoke test post-deploy, §10).
Da fare: gli endpoint di pagina, a partire da task/promemoria e lista della
spesa (§8.2, §8.3) con persistenza reale su SQLite (§7).

## Avvio locale

```bash
uv run uvicorn custode_api.main:app --reload
curl localhost:8000/api/health
```
