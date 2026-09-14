-- Il tag degli eventi di calendario, pezzo 5 di §8.10: chi ha guardato cosa.
--
-- `calendar_events.tipo` esiste dalla migrazione 007 e nasce sempre 'altro':
-- nessuno lo riempiva ancora. Il problema che questa migrazione risolve non è
-- "che tipo è", è "qualcuno l'ha già guardato?" — perché 'altro' è anche un
-- tag legittimo (un ricevimento non è né lezione né palestra né viaggio), e
-- senza un secondo segnale non si distingue "l'IA ha detto altro" da
-- "nessuno l'ha ancora guardato". Senza quella distinzione non si può
-- rispondere a "cosa ha capito", e nemmeno evitare di riproporre la stessa
-- serie ad ogni sincronizzazione.
--
-- `tag_proposto_il` è NULL finché nessuno l'ha guardato; si valorizza appena
-- un tag viene scritto — dal job di tagging o da una correzione a mano — e da
-- quel momento la serie non viene più riproposta. Le righe già in archivio
-- prima di questa migrazione ricevono NULL: è corretto, nessuna di loro è mai
-- stata guardata da un tagging automatico che ancora non esisteva.
ALTER TABLE calendar_events ADD COLUMN tag_proposto_il TEXT;

-- `tag_confermato_da_te` distingue, quando un tag c'è, chi l'ha scritto per
-- ultimo: l'IA (0, il default) o tu correggendolo dalla pagina Calendario (1).
-- Non è un flusso di approvazione come `habit_proposals` — §8.10 dice "l'IA
-- propone, tu correggi SE serve", non "conferma sempre prima che valga" — è
-- solo un'etichetta per la pagina, che altrimenti mostrerebbe un tag proposto
-- e uno corretto allo stesso modo.
ALTER TABLE calendar_events ADD COLUMN tag_confermato_da_te INTEGER
    NOT NULL DEFAULT 0 CHECK (tag_confermato_da_te IN (0, 1));

-- Le serie/eventi ancora senza tag sono la coda di lavoro del job che li
-- propone: la interroga ad ogni sincronizzazione, quindi conviene un indice.
-- Parziale come quello su `serie_id`: la maggioranza delle righe, una volta
-- che il tagging ha girato, ha questa colonna valorizzata.
CREATE INDEX idx_calendario_da_taggare ON calendar_events (fonte)
    WHERE tag_proposto_il IS NULL;
