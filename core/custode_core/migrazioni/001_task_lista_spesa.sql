-- Task/promemoria e lista della spesa (ARCHITECTURE.md §7, §8.2, §8.3).

CREATE TABLE tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo       TEXT    NOT NULL,
    note         TEXT,
    -- ISO-8601. Dieci caratteri (YYYY-MM-DD) = scadenza per tutto il giorno;
    -- più lunga (YYYY-MM-DDTHH:MM) = scadenza a un'ora precisa. NULL = nessuna.
    scadenza     TEXT,
    stato        TEXT    NOT NULL DEFAULT 'aperto'
                 CHECK (stato IN ('aperto', 'fatto')),
    -- Da dove arriva il task: alimenta il blocco "Da dove arrivano" e la
    -- didascalia della riga. `piano_ripasso` è il caso di §8.11.
    origine      TEXT    NOT NULL DEFAULT 'dashboard'
                 CHECK (origine IN ('dashboard', 'telegram', 'piano_ripasso', 'regola')),
    -- Quante volte è stato rinviato: la dashboard lo mostra come "rinviato 3×".
    rinvii       INTEGER NOT NULL DEFAULT 0 CHECK (rinvii >= 0),
    creato_il    TEXT    NOT NULL,
    completato_il TEXT
);

CREATE INDEX idx_tasks_stato_scadenza ON tasks (stato, scadenza);
CREATE INDEX idx_tasks_completato_il  ON tasks (completato_il);

CREATE TABLE shopping_list (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item        TEXT    NOT NULL,
    quantita    TEXT,
    -- Reparto del supermercato, usato per raggruppare la lista. Finché non c'è
    -- il router (§6) lo scrive chi aggiunge la voce, altrimenti resta 'Altro'.
    reparto     TEXT    NOT NULL DEFAULT 'Altro',
    comprato    INTEGER NOT NULL DEFAULT 0 CHECK (comprato IN (0, 1)),
    aggiunto_il TEXT    NOT NULL,
    comprato_il TEXT
);

CREATE INDEX idx_shopping_comprato ON shopping_list (comprato, aggiunto_il);
