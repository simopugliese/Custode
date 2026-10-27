"""Il deploy automatico sul Pi (ARCHITECTURE.md §10, DEPLOY.md §6).

Gira **sull'host**, non in un container, e usa solo la libreria standard: il Pi
non ha un ambiente `uv` e non deve averlo per ricevere un aggiornamento. Per lo
stesso motivo la cartella non è tra i pacchetti del wheel in `pyproject.toml`:
le immagini Docker non la copiano, e una voce in più nell'elenco romperebbe
`uv sync` dentro l'immagine.
"""
