# core — codice condiviso

Il pacchetto `custode_core` contiene ciò che api, bot, router e worker devono
vedere in modo identico: configurazione e accesso al DB. Non è una cartella
prevista da ARCHITECTURE.md §5, è l'alternativa scelta alla duplicazione dello
schema §7 in quattro servizi.

- `config.py` — impostazioni da ambiente/`.env` (prefisso `CUSTODE_`).
- `db.py` — connessione SQLite in WAL con le PRAGMA di §3.

Da fare, con i moduli funzionali: schema e migrazioni di §7, servizi di dominio
(task, lista spesa, spese, abitudini) riusati sia dall'API sia dal bot.
