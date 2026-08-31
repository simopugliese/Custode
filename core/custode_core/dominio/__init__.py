"""Logica di dominio, indipendente da FastAPI.

Ogni modulo qui dentro parla solo di SQLite e di tipi Python: l'API lo usa per
servire la dashboard, il bot Telegram userà gli stessi identici servizi (§8.1),
così una regola come "rinviare aumenta il contatore dei rinvii" vive in un
posto solo e non può divergere fra i due canali.
"""
