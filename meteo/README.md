# meteo — la previsione, chiesta quando serve

Una chiamata a Open-Meteo (gratuito, nessuna chiave) sulla posizione in cui sei
(ARCHITECTURE.md §8.12). **Non c'è un archivio**: una previsione si butta via
quando è vecchia, e tenerla in una tabella vorrebbe dire una tabella da tenere
allineata per un dato che il servizio rida in un attimo.

- `config.py` — la «casa» di ripiego, per quando la dashboard non ti ha ancora
  detto dove sei.
- `previsione.py` — la `Previsione` di un giorno e l'interfaccia `SorgenteMeteo`.
- `openmeteo.py` — il client, con httpx.
- `errori.py` — il modo di fallire.
- `testo.py` — i codici del meteo in parole, e la frase dell'ombrello. Funzioni
  pure, senza modello.

## httpx

Non c'è un extra `meteo` in `pyproject.toml`: l'immagine dell'API ha già httpx
tramite l'extra `router`, ed è l'unica che chiama questo client. Il giorno che
lo chiamerà anche il worker (il digest, §8.13) l'extra andrà aggiunto.
