-- Regole di contesto, la metà dettata da te (ARCHITECTURE.md §7, §8.10).
--
-- §8.10 dà due origini alle regole: quelle che **detti tu** («questa cosa
-- dimmela alle 19», «dimmelo prima di lezione»), che diventano attive subito
-- perché scrivendole le hai già approvate, e quelle **auto-proposte** da un job
-- che cerca pattern nello storico. Questa migrazione fa posto solo alle prime:
-- le seconde hanno bisogno di Claude e di uno storico su cui ragionare, e §12
-- le mette dopo apposta.
--
-- **Il trigger ha più di una colonna, invece dell'unico `trigger_valore` della
-- bozza di §7.** Con una stringa sola, «alle 19 del lunedì e del giovedì» e
-- «trenta minuti prima di una lezione» finirebbero nello stesso campo in due
-- formati diversi, da spacchettare a mano ad ogni lettura — e da sbagliare in
-- silenzio, perché una stringa storta è una stringa valida. Separati, il
-- database può dire da sé quali combinazioni hanno senso (il CHECK in fondo), e
-- `tipo_evento` può essere una chiave esterna vera invece di un pezzo di testo
-- che spera che quel tag esista ancora.
CREATE TABLE context_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,

    -- §7 prevede le due origini. Oggi solo `utente` è raggiungibile: nessun
    -- codice scrive `ia`, perché chi lo scriverà è il job delle auto-proposte.
    -- Sta qui lo stesso perché è la colonna che distingue «l'hai voluta tu» da
    -- «te l'ha proposta Custode», e aggiungerla dopo vorrebbe dire decidere
    -- retroattivamente l'origine delle regole già in archivio.
    origine      TEXT    NOT NULL DEFAULT 'utente' CHECK (origine IN ('ia', 'utente')),

    -- §8.10 elenca anche `pattern`, e qui **non c'è**. Non è una dimenticanza:
    -- un `pattern` è il trigger di una regola che il motore genera da sé, e la
    -- sua forma la si conoscerà costruendo quel motore. Ammetterlo adesso
    -- vorrebbe dire permettere una regola `attiva` che nessun valutatore sa far
    -- scattare — cioè un interruttore che non interrompe, che è esattamente ciò
    -- che il progetto evita altrove omettendo i campi invece di metterli a
    -- zero. Entrerà con la migrazione che porta le auto-proposte.
    trigger_tipo TEXT    NOT NULL
                 CHECK (trigger_tipo IN ('orario', 'prima_evento', 'dopo_evento')),

    -- — per `orario` —

    -- HH:MM locali, nel fuso di CUSTODE_TIMEZONE come ogni altro orario del
    -- progetto. La forma la garantisce il dominio, che normalizza «9:5» in
    -- «09:05» con lo stesso controllo delle impostazioni (§8): un CHECK che
    -- sappia leggere un orario in SQLite sarebbe una GLOB illeggibile, e
    -- direbbe comunque meno di quella funzione.
    ora          TEXT,

    -- I giorni della settimana in cui vale, numerati come li numera Python
    -- (`isoweekday`: 1 = lunedì … 7 = domenica), in ordine e separati da una
    -- virgola: `1,4` è «lunedì e giovedì».
    --
    -- **Vuoto vuol dire tutti i giorni**, e non «nessuno»: è il caso normale
    -- («dimmi alle 19»), e scrivere `1,2,3,4,5,6,7` per dirlo renderebbe la
    -- riga più difficile da leggere proprio nel caso più frequente. Quello che
    -- non esiste è una regola senza nessun giorno: il dominio la rifiuta,
    -- perché una regola che non può scattare mai è un modo silenzioso di
    -- perdere quello che hai chiesto.
    giorni       TEXT    NOT NULL DEFAULT '',

    -- — per `prima_evento` e `dopo_evento` —

    -- Lo **slug di un tipo**, non l'id di un evento: «prima di ogni lezione».
    -- È la direzione che §8.10 annunciava già al pezzo 6 — «una regola punterà
    -- a uno slug di qui» — ed è il motivo per cui i tipi sono finiti in tabella
    -- prima che le regole esistessero. Un id di `calendar_events` non
    -- reggerebbe: una lezione ricorrente cambia riga ad ogni sincronizzazione,
    -- e la regola resterebbe attaccata a un'occorrenza sola.
    --
    -- RESTRICT su entrambi i lati, come `calendar_events.tipo`: un tipo che una
    -- regola usa non si cancella (si archivia), e lo slug non cambia mai.
    tipo_evento  TEXT    REFERENCES calendar_tags (slug)
                 ON DELETE RESTRICT ON UPDATE RESTRICT,

    -- Quanti minuti prima dell'inizio, o dopo la fine. Zero è legittimo
    -- («appena finisce»); il tetto sta nel dominio, insieme al resto delle
    -- forme che una regola può avere.
    minuti       INTEGER CHECK (minuti IS NULL OR minuti >= 0),

    -- — cosa succede quando scatta —

    -- Il messaggio che ti arriva su Telegram, e per ora è tutto ciò che una
    -- regola sa fare. §8.10 non le chiede altro: creare un task o segnare
    -- un'abitudine sarebbe un motore diverso.
    messaggio    TEXT    NOT NULL,

    -- `proposta` esiste per il job che ancora non c'è, come `origine = 'ia'`;
    -- `scartata` invece serve già, perché la pagina Regole mostra le scartate e
    -- promette che Custode non ne riproponga una due volte — una promessa che
    -- si può mantenere solo se la riga resta.
    stato        TEXT    NOT NULL DEFAULT 'attiva'
                 CHECK (stato IN ('proposta', 'attiva', 'pausa', 'scartata')),

    creata_il    TEXT    NOT NULL,

    -- Ogni tipo di trigger porta le sue colonne e **solo** quelle. Senza questo
    -- vincolo esisterebbe una regola a orario con dentro un `tipo_evento`, e
    -- nessuno saprebbe dire quale dei due conta: il valutatore ne guarderebbe
    -- uno e la pagina mostrerebbe l'altro.
    CHECK (
        (trigger_tipo = 'orario'
             AND ora IS NOT NULL AND tipo_evento IS NULL AND minuti IS NULL)
        OR (trigger_tipo IN ('prima_evento', 'dopo_evento')
             AND ora IS NULL AND tipo_evento IS NOT NULL AND minuti IS NOT NULL)
    )
);

-- Il worker interroga «quali regole possono scattare adesso?» ad ogni giro,
-- cioè ogni cinque minuti per sempre: le regole in pausa, scartate e le
-- proposte non devono nemmeno essere lette.
CREATE INDEX idx_regole_attive ON context_rules (trigger_tipo)
    WHERE stato = 'attiva';
