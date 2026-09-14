-- Gli eventi del calendario, sincronizzati in sola lettura (§7, §8.10).
--
-- La tabella è un **archivio**, non una cache. §8.10 dice che le regole di
-- contesto auto-proposte «cercano pattern nei dati storici (calendario,
-- abitudini, orari in cui scrivi)»: il passato serve, quindi un evento che
-- esce dalla finestra sincronizzata resta qui invece di essere potato. Ciò che
-- si cancella è solo un evento che Google non restituisce più *mentre è dentro
-- la finestra*, cioè disdetto davvero.

CREATE TABLE calendar_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,

    -- La chiave naturale di un evento non è una sola colonna: è «chi lo
    -- fornisce» più «come lo chiama lui». `fonte` esiste perché esiste
    -- l'interfaccia `SorgenteCalendario` (§8.10): il giorno che si aggiunge il
    -- feed iCal dell'università, un suo evento con lo stesso identificativo di
    -- uno di Google non deve sovrascriverlo.
    fonte      TEXT    NOT NULL DEFAULT 'google',
    id_esterno TEXT    NOT NULL,

    titolo     TEXT    NOT NULL,

    -- ISO-8601 naive in ora locale, come tutto il resto del progetto: una
    -- regola di contesto confronta l'orario di un evento con «adesso», e
    -- mescolare un datetime con fuso e uno senza è un errore che Python
    -- solleva la prima volta che una regola deve scattare.
    --
    -- Testo e non un numero perché l'ordinamento lessicografico dell'ISO è già
    -- quello cronologico: `inizio < '2026-09-15'` seleziona tutto ciò che
    -- comincia prima del 15, indice compreso, senza conversioni.
    inizio     TEXT    NOT NULL,
    -- La fine è **inclusiva**: per gli eventi di giornata Google manda il
    -- giorno dopo, e il client l'ha già tirata indietro. Senza, «sei
    -- impegnato» durerebbe un giorno in più.
    fine       TEXT    NOT NULL,

    tutto_il_giorno INTEGER NOT NULL DEFAULT 0 CHECK (tutto_il_giorno IN (0, 1)),

    -- Stringa vuota e non NULL: sono campi che ci sono sempre, solo a volte
    -- non dicono niente. Un NULL costringerebbe ogni lettura a decidere cosa
    -- farne, per una distinzione — «nessun luogo» contro «luogo sconosciuto» —
    -- che non serve a niente qui.
    luogo      TEXT    NOT NULL DEFAULT '',
    -- L'evento ricorrente di cui questo è una ripetizione, se lo è.
    serie_id   TEXT    NOT NULL DEFAULT '',

    -- Il tag di §8.10. Lo riempirà il pezzo successivo (l'IA lo propone, tu
    -- correggi, resta fisso per la serie): oggi ogni evento nasce 'altro'.
    -- La colonna c'è comunque da subito perché aggiungerla dopo vorrebbe dire
    -- una ALTER TABLE su una tabella già piena di eventi veri sul Pi — è la
    -- stessa ragione per cui `habit_proposals.tipo` esiste prima di servire.
    tipo       TEXT    NOT NULL DEFAULT 'altro'
               CHECK (tipo IN ('lezione', 'palestra', 'viaggio', 'altro')),

    -- Quando questa riga è stata vista l'ultima volta da chi la fornisce.
    sincronizzato_il TEXT NOT NULL,

    -- Risincronizzare non accoda: lo stesso evento si aggiorna sul posto,
    -- e il suo `id` interno resta quello. Serve perché il `tipo` deciso una
    -- volta non si perda al sync successivo.
    UNIQUE (fonte, id_esterno)
);

-- Ogni lettura è «cosa c'è fra questo istante e quello»: la Home chiede oggi,
-- una regola chiede le prossime ore.
CREATE INDEX idx_calendario_inizio ON calendar_events (inizio);

-- Parziale: `serie_id` è vuoto per tutti gli eventi che non si ripetono, e
-- indicizzare qualche centinaio di stringhe vuote non aiuterebbe nessuna
-- ricerca. Serve al pezzo del tagging, che decide il tipo una volta per serie.
CREATE INDEX idx_calendario_serie ON calendar_events (serie_id) WHERE serie_id <> '';
