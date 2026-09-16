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
  `lista_spesa.py`, `diario.py`, `profilo.py`, `spese.py`, `abitudini.py`,
  `calendario.py`, `impostazioni.py`, più `vocabolario.py`.
- `registro_job.py` — `job_runs`, cioè cosa un job schedulato ha già fatto e
  quando. Sta qui e non nel worker perché da §8.10 lo legge anche l'API, per
  sapere se il calendario ha mai sincronizzato.

Da fare, con i moduli funzionali: corsi (§8.11).

`vocabolario.py` è l'unico che attraversa gli altri invece di stare su un
modulo suo: raccoglie i **nomi in uso** — abitudini, categorie di spesa,
reparti, task aperti — perché Whisper li riceva come prompt e smetta di
sbagliarli (§8.1). Sta in `core` e non nel bot perché è conoscenza del dominio,
non un modo di rispondere, ed è pura lettura: non sa niente né di Whisper né di
Telegram, e chi la usa decide cosa farne.

Una nota su `spese.py`: gli importi ci stanno dentro in **centesimi**, come
interi, e diventano euro solo al confine con l'API e col bot. Sommare float per
centinaia di spese produce totali che non tornano per qualche centesimo, e su
dei soldi un totale che non torna è un bug che si nota.

Una nota su `impostazioni.py`: è il confine col `.env`. Nel `.env` restano i
segreti (§9), ciò che serve per partire — dove sta il database non si può
leggere dal database — e la whitelist di §9; qui stanno le preferenze. Non c'è
nessun meccanismo per applicare un cambio senza riavviare, ed è il punto: un
valore caldo si **rilegge nel momento in cui serve**, da un file che tutti e tre
i servizi hanno già aperto. La regola da non rompere è una sola: un'impostazione
calda non finisce mai in una variabile di modulo, perché lì smetterebbe di
essere calda senza che niente lo segnali. Il `.env` resta il valore di partenza:
finché non hai mai salvato una chiave non ha riga, e vale il `default` che chi
legge passa.

Una nota su `calendario.py`: la tabella `calendar_events` è un **archivio** e
non una cache — un evento che esce dalla finestra sincronizzata resta dov'è,
perché il calendario di tre mesi fa è uno degli ingressi del motore di contesto
(§8.10). E i **tipi** di evento non sono più quattro costanti: stanno in
`calendar_tags` (migrazione 009) e li crei tu. Un evento porta lo **slug** del
suo tipo, non l'etichetta, ed è ciò che permette di rinominare un tipo toccando
una riga sola invece che mille: chi deve mostrare l'etichetta la cerca in
`mappa_tag`. Archiviare un tipo lo toglie dal menu e dal prompt del modello ma
lo lascia addosso agli impegni che ce l'hanno; cancellarlo si può solo se non
lo usa nessuno, e a impedirlo è la chiave esterna, non una convenzione.

Una nota su `abitudini.py`: le funzioni che calcolano — `attesi`, `aderenza`,
`striscia`, `presenze` — sono **pure** e prendono insiemi di date, non una
connessione. §8.6 vuole quei numeri «calcolati in codice, senza LLM», e
un'aderenza sbagliata è un bug che si nota mesi dopo: volerla provare su ottanta
combinazioni di giorni non deve costare ottanta database.
