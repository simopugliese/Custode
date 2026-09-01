# core — codice condiviso

Il pacchetto `custode_core` contiene ciò che api, bot, router e worker devono
vedere in modo identico: configurazione e accesso al DB. Non è una cartella
prevista da ARCHITECTURE.md §5, è l'alternativa scelta alla duplicazione dello
schema §7 in quattro servizi.

- `config.py` — impostazioni da ambiente/`.env` (prefisso `CUSTODE_`).
- `db.py` — connessione SQLite in WAL con le PRAGMA di §3.
- `formato.py` — le etichette in italiano (`scadenzaLabel`, `dataLabel`, …),
  scritte a mano invece che col locale di sistema, che nelle immagini slim non
  c'è. Le usano sia l'API sia il bot.
- `migrazioni/` — lo schema di §7, un file `NNN_nome.sql` per volta.
- `dominio/` — i servizi che API, bot e worker usano identici: `task.py`,
  `lista_spesa.py`, `diario.py`, `profilo.py`.

Da fare, con i moduli funzionali: spese, abitudini, calendario, corsi.
