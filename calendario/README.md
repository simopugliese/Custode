# calendario — lettura del calendario di Google

Custode **legge e basta**: non crea, non sposta, non cancella niente sul tuo
calendario (ARCHITECTURE.md §8.10). Non è una promessa del codice — il permesso
che chiede è `calendar.readonly`, quindi Google rifiuterebbe una scrittura anche
se qualcuno la scrivesse per sbaglio.

- `config.py` — credenziali, quale calendario, quanta finestra sincronizzare.
- `evento.py` — l'`Evento` come lo vede Custode, e l'interfaccia `SorgenteCalendario`.
- `google.py` — il client: rinnovo del token e `events.list`.
- `autorizza.py` — `custode-autorizza-calendario`, il comando che lanci tu.
- `errori.py` — i modi di fallire, distinti perché vanno trattati diversamente.

## Perché httpx e non l'SDK di Google

Qui si usano **due** chiamate: rinnovare il token e chiedere gli eventi.
`google-api-python-client` più `google-auth` si porterebbero dietro un client
generato per tutte le API di Google, su un arm64 dove ogni ruota in meno è
tempo di build in meno. È la stessa ragione per cui `router/deepseek.py` non usa
l'SDK di OpenAI.

## L'interfaccia, e perché esiste

Il resto di §8.10 ragiona su `Evento` e non sa che dietro c'è Google. Serve
perché il motore di contesto — «dimmelo prima della lezione» — non ha niente a
che vedere con *chi* fornisce gli eventi, e perché aggiungere un feed iCal
dell'università un domani non deve toccarlo.

## Gli orari

Gli `Evento` hanno datetime **naive in ora locale**, come tutto il resto del
progetto (`custode_core.formato.adesso` fa lo stesso). Non è un dettaglio: una
regola di contesto confronta l'orario di un evento con «adesso», e mescolare un
datetime con fuso e uno senza è un errore che Python solleva a runtime, la prima
volta che una regola deve scattare.

Google manda gli orari in due forme, e vanno trattate diversamente:

- `dateTime` è un istante con fuso → si converte nel fuso di casa e si toglie il fuso;
- `date` è un evento di giornata, e la fine che Google manda è **esclusiva**: un
  evento di un giorno solo «finisce» il giorno dopo. Va tirata indietro, o «sei
  impegnato» durerebbe un giorno in più.

La finestra chiesta a Google porta anche lei il fuso: una data nuda verrebbe
letta in UTC, e in Italia sposta gli estremi di una o due ore — un evento delle
8 del primo giorno resterebbe fuori.

## Le ricorrenze

Si chiede `singleEvents=true`, cioè le ripetizioni **espanse** in occorrenze
vere. Senza, «lezione ogni martedì» sarebbe un evento solo con dentro una regola
di ripetizione, e «prima della prossima lezione» non avrebbe nessun istante a cui
riferirsi.

Ogni occorrenza porta `serie_id` (il `recurringEventId` di Google). Non serve
ancora: servirà al passo dopo di §8.10, dove il tipo di un evento si decide una
volta per la serie invece che ogni martedì da capo. Raccoglierlo adesso costa
zero; raccoglierlo dopo vorrebbe dire risincronizzare tutto.

## L'autorizzazione

Il permesso si chiede **una volta sola**, con `custode-autorizza-calendario`.
È l'unico pezzo di Custode che ha bisogno di un browser e di una persona che
clicchi. Il runbook completo è in DEPLOY.md § 3-bis.

Sul Pi non c'è Python: il comando vive dentro l'immagine del **worker** (che è
anche chi sincronizzerà), e si lancia con `docker compose run`. Dentro un
container `127.0.0.1` è l'interno del container, quindi lì va messo
`CALENDARIO_ASCOLTA_SU=0.0.0.0` e va pubblicata la porta, o il browser non
raggiungerebbe il reindirizzamento.

Due cose che costano tempo a chi non le sa:

1. **Se il progetto su Google Cloud resta in «Testing», il refresh token scade
   dopo 7 giorni.** Va messa la schermata di consenso «In production».
   `AutorizzazioneNonValida` lo dice nel messaggio, perché è la causa più
   probabile e la meno intuitiva.
2. **Serve `prompt=consent`**, o alla seconda autorizzazione Google manda solo
   l'access token e sembra un guasto.

## Cosa non è provato qui

Il consenso vero — quello che richiede credenziali di Google e una persona che
clicca — non è mai stato eseguito contro Google. Tutto il resto (costruzione
dell'indirizzo, rifiuto di uno stato che non combacia, scambio del codice,
rinnovo del token, lettura e conversione degli eventi, pagine) gira nei test
contro un **finto Google che è un server HTTP vero**, non un oggetto sostituito:
così si esercita anche come la richiesta è costruita, che è la parte che si
sbaglia.
