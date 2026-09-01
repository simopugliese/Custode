"""Trascrizione vocale locale (ARCHITECTURE.md §4, §13).

Whisper gira in un container suo, con thread e CPU limitati, e non esce mai da
casa: i vocali non vengono mandati a nessun servizio esterno — è la parte più
letterale del "privacy first" di §1.

Il servizio espone una sola rotta, `POST /trascrivi`, raggiungibile solo sulla
rete interna di Docker.
"""
