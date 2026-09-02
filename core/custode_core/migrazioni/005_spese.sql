-- Spese e categorie (ARCHITECTURE.md §7, §8.5).

-- Le categorie non hanno un elenco predefinito: la prima spesa ne fa nascere
-- una, e da lì Claude confronta ogni proposta con quelle esistenti per evitare
-- doppioni semantici («Cibo» vs «Alimentari»), come chiede §8.5. Le categorie
-- finiscono così per somigliare a come spendi tu, non a un elenco generico.
CREATE TABLE expense_categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    -- UNIQUE su nome normalizzato: è ciò che impedisce meccanicamente il
    -- doppione identico. Quello *semantico* lo evita il modello, che riceve le
    -- categorie esistenti prima di proporne una nuova.
    nome       TEXT    NOT NULL UNIQUE,
    creata_da  TEXT    NOT NULL DEFAULT 'ia' CHECK (creata_da IN ('utente', 'ia')),
    -- Disattivare invece di cancellare: le spese già registrate restano
    -- attaccate alla loro categoria anche quando smetti di usarla.
    attiva     INTEGER NOT NULL DEFAULT 1 CHECK (attiva IN (0, 1)),
    creata_il  TEXT    NOT NULL
);

CREATE TABLE expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- L'importo in CENTESIMI, non in euro. Sommare centinaia di float porta a
    -- totali che non tornano per qualche centesimo, e su dei soldi un totale
    -- che non torna è un bug che si nota. La conversione a euro avviene una
    -- volta sola, al confine con l'API (§7 dice «importo», non con che tipo).
    importo     INTEGER NOT NULL CHECK (importo > 0),
    descrizione TEXT    NOT NULL,
    categoria_id INTEGER REFERENCES expense_categories (id),
    luogo       TEXT,
    -- Il giorno della spesa, YYYY-MM-DD: quello che conta per i totali del
    -- mese è quando hai speso, non quando l'hai registrata.
    data        TEXT    NOT NULL,
    fonte       TEXT    NOT NULL DEFAULT 'testo' CHECK (fonte IN ('testo', 'scontrino')),
    -- Le voci lette dallo scontrino, come le ha estratte il modello. §8.5 fa
    -- entrare nel database UNA spesa col totale; il dettaglio resta qui, così
    -- non si perde e si può sempre riguardare cosa c'era.
    scontrino_raw_estratto TEXT,
    -- `da_confermare` esiste solo per gli scontrini: §8.5 vuole che la sintesi
    -- letta dalla foto passi da un tuo sì prima di entrare nei conti. Una
    -- spesa in questo stato non compare nei totali. Le spese da testo nascono
    -- già confermate e si disfano con «Annulla», come task, lista e diario.
    stato       TEXT    NOT NULL DEFAULT 'confermata'
                CHECK (stato IN ('confermata', 'da_confermare')),
    creata_il   TEXT    NOT NULL
);

CREATE INDEX idx_spese_data  ON expenses (stato, data);
CREATE INDEX idx_spese_categoria ON expenses (categoria_id);
