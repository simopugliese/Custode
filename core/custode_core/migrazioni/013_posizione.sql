-- Dove sei, l'ultima volta che la dashboard me l'ha detto (§8.12).
--
-- **Una riga sola, e non un archivio.** Il meteo si chiede a Open-Meteo quando
-- serve, quindi di dove sei stato ieri non c'è niente da ricordare: serve solo
-- l'ultimo punto, per il meteo di adesso e per il digest del mattino, che gira
-- sul Pi quando nessun browser è aperto.
--
-- **Non sta in `impostazioni`.** Quella è la tabella delle preferenze, e la
-- pagina Impostazioni conta quali ne hai salvate: una posizione che si aggiorna
-- ad ogni apertura della dashboard le farebbe sembrare tutte «decise da te».
-- Una posizione è uno stato, non una scelta.
--
-- **Già approssimata.** Il browser arrotonda a due decimali (circa un
-- chilometro) prima di mandarla, e il dominio lo ripete: per il meteo basta,
-- e il database finisce nel backup ogni notte.
CREATE TABLE posizione (
    -- Il CHECK è il modo in cui SQLite dice «una riga sola».
    id            INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    lat           REAL    NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon           REAL    NOT NULL CHECK (lon BETWEEN -180 AND 180),
    aggiornata_il TEXT    NOT NULL
);
