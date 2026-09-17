-- Le auto-proposte di regole (ARCHITECTURE.md §6, §8.10) — l'altra metà di §8.10.
--
-- La 011 ha fatto posto alle regole che **detti tu**, e ha lasciato pronti
-- `stato = 'proposta'` e `origine = 'ia'` che nessun codice sapeva raggiungere.
-- Questa migrazione dà a quelle righe le due cose che gli mancavano per essere
-- mostrate: **quanto Custode ci crede** e **perché te l'ha proposta**.
--
-- Le vuole il contratto della dashboard da prima che ci fosse un motore:
-- `RegolaProposta` in `dashboard/src/types/api.ts` ha `confidenza` e
-- `motivazione` fra i suoi cinque campi, e finché non esistevano in tabella la
-- rotta poteva solo rispondere con una lista vuota.
--
-- **Una proposta è una regola concreta, non un tipo di trigger nuovo.**
-- §8.10 elenca un quarto trigger `pattern` e qui continua a non esserci, adesso
-- per una ragione più forte di quella della 011: una proposta nasce già come
-- `orario`, `prima_evento` o `dopo_evento`, quindi il valutatore che la farà
-- scattare il giorno che l'approvi è lo stesso `dovute()` già scritto e già
-- provato. Quello che §8.10 chiamava «trigger pattern» è in realtà la colonna
-- `origine`: il pattern è **come la regola è nata**, non come scatta. Un quarto
-- trigger sarebbe un secondo valutatore da costruire e da mantenere per
-- ottenere lo stesso promemoria.
--
-- **Perché si rientra la tabella invece di due `ALTER TABLE ADD COLUMN`.**
-- I due campi nuovi non sono indipendenti né da loro né dal resto della riga:
-- una proposta senza motivazione è una proposta che la pagina non sa disegnare,
-- e una regola che hai dettato tu con dentro una confidenza sarebbe un giudizio
-- attribuito a un modello che non l'ha mai vista. Sono esattamente i due
-- vincoli che `ADD COLUMN` non sa esprimere, perché un CHECK che guarda due
-- colonne insieme sta a livello di tabella. La 009 ha già rientrato
-- `calendar_events` per la stessa ragione, ed è lo stesso ragionamento della
-- 011 sul trigger: se il database può dirlo da sé, lo dice lui.
--
-- Tutte le istruzioni stanno nell'unica transazione con cui `migrazioni.migra`
-- applica il file (BEGIN IMMEDIATE): o passano tutte o non è successo niente.
-- `PRAGMA foreign_keys = ON` (db.py) non è un ostacolo, e vale la pena dire
-- perché: **nessuna tabella punta a `context_rules`**, quindi il DROP non viola
-- niente e il RENAME non deve riscrivere riferimenti altrui. La chiave esterna
-- va nell'altra direzione — da qui verso `calendar_tags` — ed è soddisfatta
-- perché le righe copiate avevano già uno slug valido.
CREATE TABLE context_rules_nuova (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,

    origine      TEXT    NOT NULL DEFAULT 'utente' CHECK (origine IN ('ia', 'utente')),

    trigger_tipo TEXT    NOT NULL
                 CHECK (trigger_tipo IN ('orario', 'prima_evento', 'dopo_evento')),

    ora          TEXT,
    giorni       TEXT    NOT NULL DEFAULT '',

    tipo_evento  TEXT    REFERENCES calendar_tags (slug)
                 ON DELETE RESTRICT ON UPDATE RESTRICT,

    minuti       INTEGER CHECK (minuti IS NULL OR minuti >= 0),

    messaggio    TEXT    NOT NULL,

    -- — le due colonne nuove —

    -- Quanto Custode ci crede, a parole e non come numero. Il contratto la
    -- vuole `string` da sempre, ed è la forma giusta: «0.82» sarebbe una
    -- precisione che non c'è dietro — nessuno ha calibrato niente — e da
    -- leggere a colpo d'occhio in una riga di pagina «alta» dice esattamente
    -- quanto serve a decidere se guardarla adesso o dopo.
    confidenza   TEXT    CHECK (confidenza IS NULL
                                OR confidenza IN ('alta', 'media', 'bassa')),

    -- Perché te l'ha proposta, nelle parole di chi l'ha proposta: «negli
    -- ultimi due mesi hai segnato la creatina in 7 delle 8 giornate con
    -- palestra, e quasi mai negli altri giorni». Senza, «Approva» sarebbe un
    -- bottone da premere al buio, ed è la stessa ragione per cui
    -- `habit_proposals.motivazione` è NOT NULL dalla 006.
    motivazione  TEXT,

    stato        TEXT    NOT NULL DEFAULT 'attiva'
                 CHECK (stato IN ('proposta', 'attiva', 'pausa', 'scartata')),

    creata_il    TEXT    NOT NULL,

    -- Il vincolo della 011, invariato: ogni trigger porta le sue colonne e
    -- solo quelle.
    CHECK (
        (trigger_tipo = 'orario'
             AND ora IS NOT NULL AND tipo_evento IS NULL AND minuti IS NULL)
        OR (trigger_tipo IN ('prima_evento', 'dopo_evento')
             AND ora IS NULL AND tipo_evento IS NOT NULL AND minuti IS NOT NULL)
    ),

    -- Le due colonne nuove viaggiano insieme: sono le due metà della stessa
    -- frase, e una proposta con la confidenza ma senza il perché è una riga che
    -- la pagina disegnerebbe mezza vuota.
    CHECK ((confidenza IS NULL) = (motivazione IS NULL)),

    -- E ci sono **se e solo se** la regola l'ha proposta Custode. Una regola
    -- che hai dettato tu non ha una confidenza perché nessuno l'ha stimata:
    -- l'hai scritta, quindi la vuoi. Metterle un «alta» di comodo vorrebbe dire
    -- un giudizio attribuito a un modello che quella frase non l'ha mai letta.
    -- Nell'altro verso, una proposta senza motivazione non si può mostrare.
    --
    -- Le due restano addosso alla regola anche dopo che l'hai approvata, e non
    -- si azzerano: «questa te l'aveva proposta Custode a settembre, per questo
    -- motivo» è la risposta a «e questa da dove salta fuori?» sei mesi dopo.
    CHECK ((origine = 'ia') = (confidenza IS NOT NULL))
);

INSERT INTO context_rules_nuova
    (id, origine, trigger_tipo, ora, giorni, tipo_evento, minuti, messaggio,
     confidenza, motivazione, stato, creata_il)
SELECT
    id, origine, trigger_tipo, ora, giorni, tipo_evento, minuti, messaggio,
    -- Tutto ciò che esiste oggi l'hai dettato tu (`origine = 'utente'`, l'unico
    -- valore che il codice della 011 sapeva scrivere), quindi NULL su entrambe
    -- soddisfa per costruzione il CHECK qui sopra.
    NULL, NULL, stato, creata_il
FROM context_rules;

DROP TABLE context_rules;

ALTER TABLE context_rules_nuova RENAME TO context_rules;

-- L'indice va ricreato: il DROP se l'è portato via con la tabella vecchia.
-- Stessa forma della 011 — il worker chiede «quali regole possono scattare
-- adesso?» ad ogni giro, e le proposte, le in pausa e le scartate non devono
-- nemmeno essere lette.
CREATE INDEX idx_regole_attive ON context_rules (trigger_tipo)
    WHERE stato = 'attiva';

-- Nuovo, e serve al job delle proposte: ad ogni giro chiede «quante ce ne sono
-- in attesa?» (il tetto) e «quali sono scadute?» (la data), e insieme alle
-- scartate sono l'elenco di ciò che non va riproposto. Sono tre domande sulle
-- righe che quasi sempre non ci sono: senza indice, tre scansioni complete di
-- una tabella che cresce con tutto quello che ti viene in mente.
CREATE INDEX idx_regole_per_stato ON context_rules (stato, creata_il);
