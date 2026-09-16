-- I tag del calendario diventano tuoi (§8.10, pezzo 6).
--
-- Fino a qui i tipi erano quattro e fissi, scritti in tre posti che dovevano
-- restare d'accordo fra loro: il CHECK della migrazione 007, la StrEnum `Tipo`
-- del dominio e l'elenco dentro il prompt del modello. §8.10 li dà per
-- scontati («lezione, palestra, viaggio, altro») ma non dice da nessuna parte
-- che debbano essere quelli e solo quelli: sono un esempio diventato uno
-- schema. Da qui in poi stanno in una tabella, e i quattro di prima ci entrano
-- come dati iniziali — nessun evento cambia tipo, nessuna pagina cambia forma.
--
-- **Perché adesso e non dopo il pezzo 7.** I tag serviranno alle regole di
-- contesto («prima di una lezione»): una regola punterà a uno slug di qui, e
-- farla puntare prima a una StrEnum e poi a una tabella vorrebbe dire
-- riscriverne il riferimento con le regole già in archivio.

-- Un tag ha **due nomi** e non uno, ed è la decisione che tiene in piedi tutto
-- il resto:
--
-- - `slug` è l'identificatore, deciso alla creazione e mai più toccato. È ciò
--   che esce dal database: sta in `calendar_events.tipo`, nel campo `tipo` del
--   contratto REST, nell'enum dello schema che riceve il modello, e domani nel
--   riferimento di una regola di contesto. Un identificatore che cambia è un
--   identificatore da rincorrere in tutti quei posti insieme.
-- - `nome` è l'etichetta che leggi, e si cambia quando vuoi. Rinominare
--   «Palestra» in «Allenamento» tocca **questa riga sola e zero eventi**.
--
-- `descrizione` non è documentazione: è la riga che il modello legge per
-- decidere. Il prompt di oggi non dice «viaggio», dice «treni, voli,
-- trasferte; non il luogo di un altro impegno» — ed è quella frase a fare il
-- lavoro. Un tag senza descrizione è un tag che il modello sbaglia, e lo
-- sbaglio si vede solo dopo, come promemoria fuori posto. Per questo è
-- NOT NULL e l'API la pretende: è anche la manopola con cui aggiusti il tiro
-- quando classifica male, senza dover rinominare niente.
CREATE TABLE calendar_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Minuscole, cifre e trattino basso: è la forma che regge come valore di
    -- un enum JSON, come segmento di URL e come chiave in tabella senza
    -- doversi far virgolettare da nessuna parte.
    slug        TEXT    NOT NULL UNIQUE
                CHECK (slug GLOB '[a-z0-9][a-z0-9_]*'),
    nome        TEXT    NOT NULL,
    descrizione TEXT    NOT NULL,

    -- `altro` è speciale e la colonna lo dice invece di lasciarlo sapere solo
    -- al codice: è il tipo con cui nasce ogni evento appena sincronizzato
    -- (`calendar_events.tipo` ha lì il suo default) ed è il ripiego di una
    -- risposta del modello illeggibile. Toglierlo — o anche solo archiviarlo —
    -- lascerebbe senza casa ogni evento nuovo. Nome e descrizione restano
    -- modificabili anche per lui: è ciò che *fa* a essere di sistema, non come
    -- si chiama.
    di_sistema  INTEGER NOT NULL DEFAULT 0 CHECK (di_sistema IN (0, 1)),

    -- Si archivia, non si cancella — è la stessa scelta di `habits.attivo`
    -- (migrazione 006) e qui la ragione è persino più forte: `tipo` è NOT NULL
    -- e ha una FK dietro, quindi cancellare un tag userebbe per forza qualcosa
    -- agli eventi che ce l'hanno. Un tag archiviato sparisce dal menu di
    -- correzione e dal prompt del modello, ma gli impegni di marzo se lo
    -- tengono: la storia di cos'era un impegno non si riscrive perché oggi hai
    -- cambiato idea. La cancellazione vera resta possibile solo per un tag che
    -- nessun evento usa, e a impedirla non è una convenzione — è la FK qui
    -- sotto.
    attivo      INTEGER NOT NULL DEFAULT 1 CHECK (attivo IN (0, 1)),

    creato_il   TEXT    NOT NULL
);

-- I quattro di prima, con le descrizioni copiate parola per parola dal prompt
-- che gira oggi (`custode_router.calendario.SISTEMA`): il tagging automatico
-- deve comportarsi esattamente come ieri: cambia da dove legge l'elenco, non
-- cosa c'è scritto.
INSERT INTO calendar_tags (slug, nome, descrizione, di_sistema, creato_il) VALUES
    ('lezione', 'Lezione',
     'l''università: lezioni, laboratori, esercitazioni, seminari, esami, appelli.',
     0, datetime('now')),
    ('palestra', 'Palestra',
     'allenamento e sport: palestra, corsa, piscina, partite, qualunque attività fisica.',
     0, datetime('now')),
    ('viaggio', 'Viaggio',
     'spostamenti che occupano l''impegno stesso: treni, voli, «rientro a casa», trasferte. Non il luogo di un altro impegno: una lezione non diventa un viaggio perché ci si arriva in treno.',
     0, datetime('now')),
    ('altro', 'Altro',
     'tutto il resto: visite mediche, ricevimenti, cene, compleanni, scadenze, impegni personali.',
     1, datetime('now'));

-- — e ora il CHECK della 007, che SQLite non sa togliere sul posto —
--
-- Si ricostruisce la tabella: sono le mosse che la documentazione di SQLite
-- prescrive per un vincolo che non si può alterare. Girano tutte dentro
-- l'unica transazione con cui `migrazioni.migra` applica il file (BEGIN
-- IMMEDIATE), quindi o passano tutte o non è successo niente.
--
-- `PRAGMA foreign_keys = ON` (db.py) non è un ostacolo, e vale la pena dire
-- perché: **nessuna tabella punta a `calendar_events`**, quindi il RENAME non
-- deve riscrivere riferimenti altrui e il DROP non viola niente. La FK nuova
-- va invece nell'altra direzione — da qui verso `calendar_tags` — ed è
-- soddisfatta perché i quattro tag sono già stati inseriti qui sopra e ogni
-- riga esistente ha per forza uno di quei quattro valori: glielo imponeva il
-- CHECK che stiamo togliendo.
CREATE TABLE calendar_events_nuova (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte      TEXT    NOT NULL DEFAULT 'google',
    id_esterno TEXT    NOT NULL,
    titolo     TEXT    NOT NULL,
    inizio     TEXT    NOT NULL,
    fine       TEXT    NOT NULL,
    tutto_il_giorno INTEGER NOT NULL DEFAULT 0 CHECK (tutto_il_giorno IN (0, 1)),
    luogo      TEXT    NOT NULL DEFAULT '',
    serie_id   TEXT    NOT NULL DEFAULT '',

    -- Resta la stessa colonna di testo di prima, con lo stesso default: il
    -- contratto REST espone `tipo` come stringa da quando esiste, e passare a
    -- un intero avrebbe voluto dire una JOIN ad ogni lettura del calendario
    -- per riottenere la stringa da mandare comunque. Cambia solo chi la
    -- custodisce: non più un CHECK inciso nello schema, ma una riga che puoi
    -- aggiungere.
    --
    -- RESTRICT su entrambi i lati, e nessuno dei due è un ripensamento:
    -- ON DELETE perché un tag ancora in uso non si cancella (si archivia), e
    -- ON UPDATE perché lo slug non cambia mai — se un giorno qualcuno provasse
    -- a cambiarlo, deve trovare un errore e non un aggiornamento silenzioso di
    -- mille righe.
    tipo       TEXT    NOT NULL DEFAULT 'altro'
               REFERENCES calendar_tags (slug) ON DELETE RESTRICT ON UPDATE RESTRICT,

    sincronizzato_il TEXT NOT NULL,
    tag_proposto_il  TEXT,
    tag_confermato_da_te INTEGER NOT NULL DEFAULT 0
               CHECK (tag_confermato_da_te IN (0, 1)),

    UNIQUE (fonte, id_esterno)
);

INSERT INTO calendar_events_nuova
    (id, fonte, id_esterno, titolo, inizio, fine, tutto_il_giorno, luogo,
     serie_id, tipo, sincronizzato_il, tag_proposto_il, tag_confermato_da_te)
SELECT
    id, fonte, id_esterno, titolo, inizio, fine, tutto_il_giorno, luogo,
    serie_id, tipo, sincronizzato_il, tag_proposto_il, tag_confermato_da_te
FROM calendar_events;

DROP TABLE calendar_events;

ALTER TABLE calendar_events_nuova RENAME TO calendar_events;

-- Gli indici se ne sono andati con la tabella vecchia: si rifanno identici a
-- come li hanno scritti la 007 (i primi due) e la 008 (il terzo), commenti
-- compresi nel senso che le ragioni non sono cambiate — ogni lettura è «cosa
-- c'è fra questo istante e quello», il tag si decide una volta per serie, e la
-- coda di chi non ha ancora un tag si interroga ad ogni giro del worker.
CREATE INDEX idx_calendario_inizio ON calendar_events (inizio);

CREATE INDEX idx_calendario_serie ON calendar_events (serie_id) WHERE serie_id <> '';

CREATE INDEX idx_calendario_da_taggare ON calendar_events (fonte)
    WHERE tag_proposto_il IS NULL;
