-- Tracciatore abitudini (ARCHITECTURE.md §7, §8.6).

-- Le abitudini sono **dinamiche**: §8.6 chiede di poterle aggiungere,
-- disattivare e cambiare di target in qualsiasi momento. Nessun elenco
-- predefinito, quindi, e nessuna cancellazione: disattivare invece di
-- eliminare tiene in piedi i log già raccolti, che sono la storia di com'è
-- andata e non vanno persi perché oggi hai smesso di andare in palestra.
CREATE TABLE habits (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    -- UNIQUE sul nome: due «Palestra» renderebbero ambiguo il matching del
    -- testo libero, che è il modo principale in cui si segnano (§8.6).
    nome      TEXT    NOT NULL UNIQUE,
    -- Quante volte a settimana vuoi farla, da 1 a 7. §7 la chiama così, e una
    -- frequenza settimanale copre sia «almeno 3 volte» sia «tutti i giorni»
    -- (che è 7): l'aderenza mensile si ricava da qui in proporzione ai giorni
    -- trascorsi, senza bisogno di un secondo target da tenere allineato.
    frequenza_target_settimanale INTEGER NOT NULL
              CHECK (frequenza_target_settimanale BETWEEN 1 AND 7),
    attivo    INTEGER NOT NULL DEFAULT 1 CHECK (attivo IN (0, 1)),
    creato_il TEXT    NOT NULL
);

CREATE TABLE habit_logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id  INTEGER NOT NULL REFERENCES habits (id) ON DELETE CASCADE,
    data      TEXT    NOT NULL,
    -- `fatto = 0` non è la stessa cosa di una riga assente: «non ho fatto
    -- meditazione» è una cosa che hai detto, e l'assenza è solo silenzio.
    -- L'aderenza conta le righe con `fatto = 1`, quindi ai numeri non cambia
    -- niente; a poter tornare indietro su ciò che hai appena detto sì.
    fatto     INTEGER NOT NULL DEFAULT 1 CHECK (fatto IN (0, 1)),
    creato_il TEXT    NOT NULL,
    -- Un giorno, un log per abitudine: ridirlo aggiorna, non accoda.
    UNIQUE (habit_id, data)
);

CREATE INDEX idx_abitudini_log_data ON habit_logs (data);

-- Le proposte di §8.6 lette dalla dashboard («Custode propone»): il report
-- narrativo di Claude è l'unico punto in cui si guarda un trend lungo, ed è lì
-- che può accorgersi che un target non regge — «Palestra: 3 volte a settimana
-- → 2», con la motivazione che l'ha fatta nascere. Non tocca niente da sola:
-- il target cambia se premi «Accetta», come ogni azione decisa da un modello.
CREATE TABLE habit_proposals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id        INTEGER NOT NULL REFERENCES habits (id) ON DELETE CASCADE,
    -- Oggi c'è solo `target`, ma la colonna esiste perché una proposta di
    -- tipo diverso (un'abitudine nuova suggerita dal diario) possa arrivare
    -- senza una migrazione che tocchi una tabella già piena di dati.
    tipo            TEXT    NOT NULL DEFAULT 'target' CHECK (tipo IN ('target')),
    target_proposto INTEGER NOT NULL CHECK (target_proposto BETWEEN 1 AND 7),
    motivazione     TEXT    NOT NULL,
    stato           TEXT    NOT NULL DEFAULT 'in_attesa'
                    CHECK (stato IN ('in_attesa', 'accettata', 'rifiutata')),
    creata_il       TEXT    NOT NULL,
    decisa_il       TEXT
);

CREATE INDEX idx_abitudini_proposte ON habit_proposals (stato, creata_il);

-- Il report narrativo settimanale e mensile (§8.6): lo scrive Claude, che
-- incrocia le abitudini con diario e spese. Si conserva perché §8.6 lo vuole
-- «settimanale per un check ravvicinato, mensile per i trend più lenti»: un
-- testo che vive solo nella notifica Telegram non permette né di rileggere il
-- mese scorso né di mostrarlo in dashboard.
CREATE TABLE habit_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo     TEXT NOT NULL CHECK (periodo IN ('settimana', 'mese')),
    -- Il primo giorno del periodo: il lunedì per la settimana, il primo del
    -- mese per il mese. Con `periodo` è unica, quindi un job rifatto a mano
    -- non paga una seconda chiamata per riscrivere lo stesso testo.
    chiave      TEXT NOT NULL,
    testo       TEXT NOT NULL,
    generato_il TEXT NOT NULL,
    UNIQUE (periodo, chiave)
);
