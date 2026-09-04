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
  `lista_spesa.py`, `diario.py`, `profilo.py`, `spese.py`, `abitudini.py`.

Da fare, con i moduli funzionali: calendario, corsi.

Una nota su `spese.py`: gli importi ci stanno dentro in **centesimi**, come
interi, e diventano euro solo al confine con l'API e col bot. Sommare float per
centinaia di spese produce totali che non tornano per qualche centesimo, e su
dei soldi un totale che non torna è un bug che si nota.

Una nota su `abitudini.py`: le funzioni che calcolano — `attesi`, `aderenza`,
`striscia`, `presenze` — sono **pure** e prendono insiemi di date, non una
connessione. §8.6 vuole quei numeri «calcolati in codice, senza LLM», e
un'aderenza sbagliata è un bug che si nota mesi dopo: volerla provare su ottanta
combinazioni di giorni non deve costare ottanta database.
