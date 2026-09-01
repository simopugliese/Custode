-- Profilo cumulativo e riepilogo settimanale del diario (§7, §8.4).
--
-- È la seconda metà di §8.4: il canale passivo che raccoglie segnali utili dai
-- messaggi di tutti i giorni, e il job settimanale che li rifonde nel profilo.

-- I segnali raccolti dai messaggi, in attesa di finire nel profilo.
CREATE TABLE profile_candidates (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Il messaggio da cui è stato ricavato, per intero: alla revisione
    -- settimanale serve poter vedere il contesto e non solo l'estratto.
    messaggio_origine    TEXT    NOT NULL,
    -- Il segnale vero e proprio, come lo userà la rifusione.
    estratto             TEXT    NOT NULL,
    -- §7 prevedeva in_coda | chiarito | scartato. `approvato` si aggiunge
    -- perché §8.4 parla dei «candidati approvati della settimana» e di una
    -- «revisione nel batch settimanale»: senza uno stato per il sì, quella
    -- revisione non lascerebbe traccia di essere avvenuta.
    stato                TEXT    NOT NULL DEFAULT 'in_coda'
                         CHECK (stato IN ('in_coda', 'chiarito', 'approvato', 'scartato')),
    -- La domanda che il bot ha fatto lì per lì su un segnale ambiguo, e la
    -- risposta. La domanda non era in §7, ma senza di essa la risposta è
    -- incomprensibile a distanza di giorni — e alla revisione settimanale si
    -- guardano entrambe.
    chiarimento_domanda  TEXT,
    chiarimento_risposta TEXT,
    -- La versione del profilo che ha assorbito questo candidato. NULL = non
    -- ancora rifuso. Serve a non ridarlo in pasto al modello ogni settimana, e
    -- a poter rispondere a «perché il profilo dice questo?».
    versione_profilo     INTEGER REFERENCES profile_document (versione),
    creato_il            TEXT    NOT NULL
);

CREATE INDEX idx_candidati_stato ON profile_candidates (stato, versione_profilo);

-- Il profilo cumulativo, versionato: ogni rifusione aggiunge una riga, non
-- sostituisce quella prima. §8.4 lo chiede esplicitamente — è ciò che permette
-- di tornare indietro se una riscrittura perde qualcosa di importante.
CREATE TABLE profile_document (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    versione      INTEGER NOT NULL UNIQUE,
    testo         TEXT    NOT NULL,
    aggiornato_il TEXT    NOT NULL
);

-- Il riepilogo settimanale del diario (§8.4 punto 7). Una riga per settimana,
-- con `settimana_inizio` = il lunedì: è la chiave, e impedisce di generare due
-- volte il riepilogo della stessa settimana se il job gira due volte.
CREATE TABLE diary_weekly_summary (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    settimana_inizio TEXT NOT NULL UNIQUE,
    testo            TEXT NOT NULL,
    generato_il      TEXT NOT NULL
);
