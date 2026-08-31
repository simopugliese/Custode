"""Backend FastAPI di Custode (ARCHITECTURE.md §4).

Espone il contratto REST consumato dalla dashboard, documentato in
`dashboard/API.md`. In questa fase esiste solo l'health check: gli endpoint
di pagina arrivano con i moduli funzionali di §8.
"""

from custode_api.main import app

__all__ = ["app"]
