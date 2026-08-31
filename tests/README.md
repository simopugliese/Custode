# tests

Unit e integration test (ARCHITECTURE.md §10).

- `unit/` — funzioni pure e componenti isolati: configurazione, parser, logica
  del router, funzioni DB.
- `integration/` — l'API completa contro un DB SQLite reale su disco (mai in
  memoria: si vuole esercitare anche il comportamento WAL).

```bash
uv run pytest                      # tutto
uv run pytest -m "not integration" # solo unit
docker compose -f docker-compose.test.yml run --rm tests   # come in CI, in container
```
