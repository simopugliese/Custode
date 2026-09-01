-- Registro delle esecuzioni dei job schedulati (§5, worker/).
--
-- Il worker si sveglia ogni pochi minuti e chiede «cosa è dovuto adesso?». Per
-- non rifare ogni volta la stessa cosa serve sapere cos'è già stato fatto, e
-- non basta guardare il risultato: il riepilogo di una settimana senza voci
-- approvate non produce nessuna riga in `diary_weekly_summary`, e il job
-- ripartirebbe ad ogni giro all'infinito.
--
-- `chiave` è il periodo a cui l'esecuzione si riferisce (per il riepilogo
-- settimanale, il lunedì della settimana). Insieme al nome è unica, quindi un
-- job già fatto per quel periodo non si ripete nemmeno se il worker riparte.
CREATE TABLE job_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL,
    chiave      TEXT NOT NULL,
    eseguito_il TEXT NOT NULL,
    UNIQUE (nome, chiave)
);
