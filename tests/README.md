# tests

Unit e integration test (ARCHITECTURE.md §10).

- `unit/` — funzioni pure e componenti isolati: configurazione, parser, logica
  del router, funzioni DB.
- `integration/` — l'API completa contro un DB SQLite reale su disco (mai in
  memoria: si vuole esercitare anche il comportamento WAL).

## I finti sono server HTTP, non oggetti

Dove c'è di mezzo un servizio esterno, il finto è un **server HTTP vero** a cui
si punta il client di produzione cambiandogli l'URL: `finto_google.py` per il
calendario (§8.10) e `finto_anthropic.py` per Claude (§6). Non è pignoleria.
Con un client sostituito in memoria, tutto ciò che sta fra il compito e la
risposta — come la richiesta è costruita, l'SDK, l'HTTP, la rilettura — non lo
prova niente, ed è esattamente la parte che si sbaglia e che non si può provare
sul Pi senza spendere.

Su `finto_anthropic` la deviazione passa da `ANTHROPIC_BASE_URL`, che legge
l'SDK e non il progetto: per questo non c'è niente da cambiare in
`custode_router.config`, e per questo un test che la usa sta esercitando il
client vero. Che stia funzionando lo si vede rompendo la tabella di §6: spostato
`PROPOSTA_REGOLE` su DeepSeek, i quattro test di
`test_proposte_end_to_end.py` cadono tutti.

```bash
uv sync --all-extras               # serve una volta: il bot sta in un extra
uv run pytest                      # tutto
uv run pytest -m "not integration" # solo unit
docker compose -f docker-compose.test.yml run --rm tests   # come in CI, in container
```
