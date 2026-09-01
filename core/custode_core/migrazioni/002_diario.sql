-- Diario (ARCHITECTURE.md §7, §8.4).
--
-- Una voce per GIORNO, non per messaggio: §8.4 parla di "7 entry approvate" per
-- una settimana, la dashboard conta le voci per giorno (`coperturaMese`) e le
-- attribuisce a più fonti insieme ("da 3 vocali e 11 messaggi"). Il materiale
-- della giornata si accumula quindi sulla stessa voce, e il riassunto si
-- propone quando la giornata viene chiusa.

CREATE TABLE diary_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    -- YYYY-MM-DD nel fuso di CUSTODE_TIMEZONE. UNIQUE: è la chiave vera della
    -- tabella, ed è ciò che impedisce due voci per lo stesso giorno.
    data                TEXT    NOT NULL UNIQUE,
    -- La bozza proposta da Claude: sta in una colonna sua, separata da quella
    -- approvata, perché §8.4 vuole che nel diario entri solo ciò che hai
    -- confermato. La dashboard mostra le bozze come "da approvare" (contratto
    -- in dashboard/API.md), quindi vanno persistite: tenerle solo in memoria
    -- le farebbe sparire ad ogni riavvio del bot.
    riassunto_proposto  TEXT,
    -- L'unica versione che conta come diario. Il job settimanale (§8.4) legge
    -- solo questa.
    riassunto_approvato TEXT,
    -- Tag di categorizzazione (studio, salute, umore, …) come array JSON.
    tag                 TEXT    NOT NULL DEFAULT '[]',
    stato_approvazione  TEXT    NOT NULL DEFAULT 'in_raccolta'
                        CHECK (stato_approvazione IN
                              ('in_raccolta', 'da_approvare', 'in_modifica', 'approvata')),
    creata_il           TEXT    NOT NULL,
    approvata_il        TEXT
);

CREATE INDEX idx_diary_stato ON diary_entries (stato_approvazione, data);

-- Il materiale grezzo della giornata, un frammento per messaggio o vocale.
--
-- La bozza di §7 prevedeva una sola colonna `trascrizione_raw` sulla voce. Non
-- basta: §8.1 vuole che ogni azione decisa da un modello si possa disfare con
-- un tap, e il riconoscimento del materiale da diario è deciso da un modello.
-- Con un unico campo concatenato, «Annulla» potrebbe solo tagliare del testo a
-- occhio; con un frammento per riga toglie esattamente la frase che aveva
-- aggiunto. In più `n_vocali` e `n_messaggi` di `fonteLabel` si contano da qui
-- invece di essere due contatori da tenere allineati a mano.
--
-- `trascrizione_raw` non sparisce: è la concatenazione di queste righe, ed è
-- ciò che viene passato al modello per il riassunto.
CREATE TABLE diary_fragments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL REFERENCES diary_entries (id) ON DELETE CASCADE,
    testo     TEXT    NOT NULL,
    -- Dettato o scritto: è la differenza fra "da 3 vocali" e "da 11 messaggi".
    da_vocale INTEGER NOT NULL DEFAULT 0 CHECK (da_vocale IN (0, 1)),
    creato_il TEXT    NOT NULL
);

CREATE INDEX idx_diary_fragments_entry ON diary_fragments (entry_id, id);
