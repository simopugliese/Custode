-- Le impostazioni modificabili a caldo (§8, `/api/impostazioni`).
--
-- Fino a qui ogni manopola stava nel `.env`, e cambiarne una voleva dire
-- entrare sul Pi, modificare un file e far ripartire i container. Per un
-- segreto va benissimo — si tocca una volta e non si tocca più. Per il budget
-- settimanale no: è un numero che cambia, e con cui la Home decide se
-- disegnare il blocco delle spese.
--
-- **Chiave/valore e non una colonna per impostazione.** Una colonna per
-- impostazione vorrebbe dire una migrazione ogni volta che un modulo nuovo ha
-- una manopola — §8.11 ne porterà, §8.13 anche — e quell'attrito finisce col
-- lasciarle nel `.env` per sempre, che è esattamente il problema da cui si
-- parte. Il prezzo di chiave/valore è che il database non sa più quali chiavi
-- esistono né di che tipo sono: quel sapere sta in
-- `custode_core.dominio.impostazioni`, che è anche l'unico posto da cui si
-- scrive, e una chiave che non è nel registro viene rifiutata.
--
-- **Una riga assente è un dato**, ed è la ragione per cui qui non si semina
-- niente. «Nessuna riga» vuol dire «non l'hai mai deciso tu», e in quel caso
-- vale il valore del `.env` — che resta il punto di partenza di
-- un'installazione, non una seconda fonte di verità: dal primo salvataggio
-- vince il database e il `.env` smette di contare. Seminare i default qui
-- renderebbe indistinguibile «mai deciso» da «deciso, e per caso è il default»,
-- e un'installazione che aggiorna il `.env` non vedrebbe più il cambiamento.
--
-- **I segreti non passano di qui** (§9). Restano nel `.env`, dove stanno tutti
-- gli altri: il database finisce nel backup ogni notte, ed è lo stesso
-- ragionamento con cui §8.10 ha tenuto fuori il refresh token di Google — un
-- ripristino di tre mesi fa rimetterebbe in circolo una chiave che nel
-- frattempo hai revocato.
CREATE TABLE impostazioni (
    -- Il nome nel registro, non quello del contratto REST: `budget_settimanale`
    -- e non `budget.settimanale`. Il contratto è una forma di risposta e può
    -- cambiare; questa è la chiave con cui il valore è stato salvato.
    chiave        TEXT NOT NULL PRIMARY KEY,

    -- JSON, non testo nudo: i valori sono numeri, stringhe e booleani, e un
    -- `"30"` che torna indietro come stringa dove il codice si aspetta un
    -- intero è il tipo di errore che si scopre il giorno in cui il job deve
    -- scattare. Il registro sa che tipo aspettarsi e rifiuta quello che non
    -- torna.
    valore        TEXT NOT NULL,

    -- Quando l'hai cambiata l'ultima volta. Non serve a nessuna logica: serve
    -- a rispondere a «da quando è così?» quando qualcosa non torna.
    aggiornato_il TEXT NOT NULL
);
