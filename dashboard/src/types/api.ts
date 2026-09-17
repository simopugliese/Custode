/**
 * Tipi condivisi per le risposte dell'API di Custode.
 * Rispecchiano lo schema dati in ARCHITECTURE.md (§7), alla radice del repo.
 * Il contratto REST completo è documentato in /API.md.
 */

// — entità condivise fra più pagine —

export interface TaskItem {
  id: string;
  titolo: string;
  fatto: boolean;
  scadenzaLabel?: string; // es. "18:00", "domani", "26 ago" — già formattata dal backend
  meta?: string; // testo secondario neutro, es. "ripasso", "da piano di ripasso"
  tag?: string; // es. "rinviato 3×", "ricorrente"
  rinvii?: number;
}

export interface ShoppingItem {
  id: string;
  nome: string;
  preso: boolean;
  quantita?: string;
  reparto: string;
  tag?: string;
}

export interface HabitRow {
  id: string;
  nome: string;
  giorni: boolean[]; // 7 voci, lunedì -> domenica
  progressoLabel: string; // "2 / 3", "5 di fila"
  evidenziata?: boolean; // streak in evidenza (verde)
}

export interface CalendarEventItem {
  id: string;
  ora: string; // "09:00", oppure "—" per chi un'ora non ce l'ha
  titolo: string;
  luogo?: string;
  meta?: string; // es. "tutto il giorno", "in corso"
}

export interface CategoriaSpesa {
  nome: string;
  importo: number;
  quota: number; // 0-1, quota sul totale/budget per il grafico a barre
}

// — Home —

/**
 * Riepilogo di oggi. I campi opzionali appartengono a moduli che possono non
 * essere ancora attivi: in quel caso il backend li **omette** invece di
 * mandare zero o lista vuota, e la pagina non disegna il blocco. Una lista
 * vuota significa invece "il modulo c'è e oggi non ha niente da dire".
 */
export interface HomeData {
  dataLabel: string; // "sabato 30 agosto, 08:41"
  titolo: string; // frase-riepilogo
  proposteAutomazioni?: number;
  stats: {
    taskAperti: number;
    listaSpesaDaPrendere: number;
    spesaSettimana?: number;
    streakPiuLunga?: number;
  };
  taskOggi: TaskItem[];
  listaSpesa: ShoppingItem[];
  calendarioOggi?: CalendarEventItem[];
  // Cosa scrivere quando `calendarioOggi` è una lista vuota: una giornata
  // libera e un calendario non ancora sincronizzato danno la stessa lista, e
  // non vogliono dire la stessa cosa. Assente quando c'è almeno un evento.
  calendarioNotaVuoto?: string;
  abitudini?: HabitRow[];
  speseSettimana?: {
    categorie: CategoriaSpesa[];
    budget: number;
    speso: number;
    scontriniInAttesa: number;
  };
}

// — Diario —

export type StatoVoceDiario = 'da_approvare' | 'approvata' | 'assente';

export interface VoceDiario {
  id: string;
  dataLabel: string; // "Ven 29 agosto"
  stato: StatoVoceDiario;
  approvataAlleLabel?: string;
  testo?: string;
  tag: string[];
  fonteLabel?: string; // "da 3 vocali e 11 messaggi"
}

export interface TemaRicorrente {
  nome: string;
  occorrenze: number;
  quota: number; // 0-1
}

export interface DiarioData {
  periodoLabel: string; // "agosto 2026"
  titolo: string;
  vociApprovate: number;
  giorniTotali: number;
  vociInAttesa: number;
  stats: {
    vociDelMese: number;
    giorniConsecutivi: number;
    paroleMedia: number;
    temaPiuRicorrente: string;
  };
  voci: VoceDiario[];
  altreVociVecchie: number;
  riepilogoSettimanale?: { label: string; testo: string; generatoLabel: string };
  riepilogoMensile?: { label: string; testo: string };
  temiDelMese: TemaRicorrente[];
  coperturaMese: boolean[]; // un valore per giorno del mese
  coperturaNota: string;
}

// — Calendario (§8.10) —

/**
 * Un tipo di evento, adesso che li decidi tu (§8.10, pezzo 6). Le etichette
 * arrivano dal backend, come già quando i tipi erano quattro e fissi.
 *
 * `tipi` porta **anche gli archiviati** (`attivo: false`): un impegno di marzo
 * può portarne uno, e la sua etichetta va comunque mostrata. Il menu di
 * correzione offre gli attivi più, se c'è, quello che l'evento ha già addosso.
 */
export interface TipoEvento {
  valore: string; // lo slug: è ciò che si rimanda in PATCH, e non cambia mai
  label: string; // il nome, che cambia quando lo rinomini
  descrizione: string; // la riga che legge il modello per decidere
  attivo: boolean;
  diSistema: boolean; // 'altro': si rinomina, non si archivia né si cancella
  eventi: number; // quanti impegni lo usano, in tutto l'archivio
  eliminabile: boolean; // solo un tipo tuo che nessun impegno usa
  notaLabel: string; // `eventi` a parole, e perché i bottoni sono quelli che sono
}

/** Corpo di `POST /api/calendario/tipi`. La descrizione è obbligatoria. */
export interface NuovoTipoEvento {
  nome: string;
  descrizione: string;
}

/** Corpo di `PATCH /api/calendario/tipi/:slug`. Lo slug non si cambia mai. */
export interface ModificaTipoEvento {
  nome?: string;
  descrizione?: string;
  attivo?: boolean;
}

/** La risposta a una creazione o a una modifica di un tipo. */
export interface TipoEventoSalvato {
  tipo: TipoEvento;
  label: string;
}

/**
 * Un evento nella pagina Calendario: la riga della Home più ciò che Custode
 * ne ha capito. `statoTag` distingue i tre casi che `tipo` da solo confonde —
 * 'altro' è sia il default di un evento appena sincronizzato sia un esito
 * legittimo del modello.
 */
export interface EventoCalendario extends CalendarEventItem {
  tipo: string;
  tipoLabel: string;
  statoTag: 'da_guardare' | 'proposto' | 'corretto';
  statoTagLabel: string;
  serie: boolean; // se vero, correggerlo tocca tutta la ricorrenza
}

export interface GiornoCalendario {
  label: string;
  isOggi?: boolean;
  eventi: EventoCalendario[];
  notaVuoto?: string; // solo nella vista settimana, che manda i sette giorni
}

/** Una proposta dell'IA mai confermata: una riga per serie, non per occorrenza. */
export interface SerieDaRivedere {
  id: string; // l'evento su cui mandare la correzione: la prossima occorrenza
  titolo: string;
  tipo: string;
  tipoLabel: string;
  quandoLabel: string; // "giovedì alle 11:00"
  occorrenzeLabel?: string; // assente per un evento singolo
  propostoLabel: string; // "proposto oggi"
  serie: boolean;
}

export interface CalendarioData {
  periodoLabel: string;
  titolo: string;
  stats: {
    eventiPeriodo: number;
    daRivedere: number;
    daGuardare: number;
  };
  tipi: TipoEvento[];
  giorni: GiornoCalendario[];
  daRivedere: SerieDaRivedere[];
  notaVuoto?: string;
  /**
   * Cosa aspetta gli impegni senza tipo, in parole. Assente quando non ce ne
   * sono. Non è `stats.daGuardare` detto a parole: dice anche **se** qualcuno
   * li guarderà, perché senza la chiave del modello quel numero non scende mai.
   */
  daGuardareLabel?: string;
  orizzonteLabel?: string; // fin dove arriva la finestra sincronizzata
}

/** La risposta a una correzione: l'evento aggiornato e cos'altro è cambiato. */
export interface CorrezioneTag {
  evento: EventoCalendario;
  occorrenze: number;
  label: string;
}

// — Lezioni e corsi —

export interface LezioneSettimana {
  giorno: string;
  isOggi?: boolean;
  lezioni: {
    ora: string;
    nome: string;
    luogo?: string;
    stato?: string;
    statoVariant?: 'accent' | 'outline' | 'neutral';
    evidenziata?: boolean;
  }[];
  notaVuoto?: string;
}

export interface PianoRipasso {
  id: string;
  corso: string;
  argomento: string;
  priorita: boolean;
  motivazione: string;
  task: TaskItem[];
}

export interface Corso {
  id: string;
  nome: string;
  capitoliFatti: number;
  capitoliTotali: number;
  esameLabel: string;
  argomentiArretrato?: number;
}

export interface LezioniData {
  periodoLabel: string;
  titolo: string;
  checkInOra: string;
  stats: {
    corsiAttivi: number;
    lezioniSettimana: { fatte: number; totali: number };
    checkInDiFila: number;
    argomentiDaRipassare: number;
  };
  settimana: LezioneSettimana[];
  pianiRipasso: PianoRipasso[];
  corsi: Corso[];
  checkInRecenti: boolean[]; // ultimi 14 giorni
  checkInNota: string;
  ultimoCheckIn: { label: string; righe: { corso: string; esito: 'chiaro' | 'da_rivedere' }[] };
  argomentiDaRipassare: { argomento: string; corso: string }[];
}

// — Task —

/**
 * Una sezione della colonna principale della pagina Task. I titoli li decide
 * il backend in base alla vista richiesta (per scadenza: "In ritardo", "Oggi",
 * …; completati: per data di chiusura; provenienza: Dashboard, Telegram,
 * piano di ripasso, regola), così la
 * pagina non deve sapere quali raggruppamenti esistono.
 */
export interface SezioneTask {
  titolo: string;
  task: TaskItem[];
  notaVuoto?: string; // testo da mostrare quando la sezione è vuota ma va comunque mostrata
}

export interface TaskData {
  dataLabel: string;
  titolo: string;
  avviso?: string;
  stats: { aperti: number; oggi: number; inRitardo: number; chiusiSettimana: number };
  sezioni: SezioneTask[];
  chiusiPerGiorno: number[]; // 7 valori, lun -> dom
  ricorrenti: { nome: string; frequenzaLabel: string }[];
  provenienza: { origine: string; conteggio: number }[];
}

// — Lista della spesa —

export interface ListaSpesaData {
  aggiornataAlleLabel: string;
  titolo: string;
  suggerimento?: { testo: string; voci: string[] };
  // stimaCarrello e ultimaSpesaGiorni dipendono dallo storico spese (§8.5):
  // assenti finché quel modulo non esiste.
  stats: { daPrendere: number; presi: number; stimaCarrello?: number; ultimaSpesaGiorni?: number };
  reparti: { nome: string; voci: ShoppingItem[] }[];
  presi: ShoppingItem[];
  suggeriti: { nome: string; frequenzaLabel: string }[];
  ultimeSpese: { dataLabel: string; luogo: string; importo: number }[];
  repartiFrequenti: { nome: string; quota: number }[];
}

// — Spese —

export interface Movimento {
  id: string;
  dataLabel: string;
  data: string; // AAAA-MM-GG: dataLabel si legge, questa si rimanda indietro
  descrizione: string;
  categoria: string;
  importo: number;
  luogo?: string;
  daScontrino?: boolean;
}

export interface NuovaSpesa {
  importo: number;
  descrizione: string;
  categoria?: string;
  luogo?: string;
  data?: string; // assente = oggi
}

/** Solo i campi passati vengono toccati. `luogo` e `categoria` a stringa vuota
 *  tolgono il valore. */
export interface ModificaSpesa {
  importo?: number;
  descrizione?: string;
  categoria?: string;
  luogo?: string;
  data?: string;
}

export interface CategoriaSpesaGestione {
  id: string;
  nome: string;
  attiva: boolean;
  daUtente?: boolean;
  spese: number;
  totale: number;
}

export interface SpeseData {
  periodoLabel: string;
  titolo: string;
  scontrinoInAttesa?: { id: string; luogo: string; importo: number; categoriaProposta: string; dataLabel: string };
  stats: { totaleMese: number; mediaGiorno: number; categoriaMaggiore: string; variazioneMesePrecedente: number };
  andamentoGiorni: number[]; // percentuali 0-100 per il grafico a barre del mese
  movimenti: Movimento[];
  categorie: CategoriaSpesa[];
  categoriaNota?: string;
  confronto: { label: string; importo: number }[];
}

// — Abitudini —

export interface AbitudineDettaglio extends HabitRow {
  frequenzaLabel: string;
  goalRatioLabel: string; // "2/3"
  segnataOggi: boolean;
}

export interface AbitudiniData {
  periodoLabel: string;
  titolo: string;
  avviso?: string;
  stats: { attive: number; obiettiviCentrati: { fatti: number; totali: number }; streakMigliore: number; costanzaMese: number };
  abitudini: AbitudineDettaglio[];
  meseSingolaAbitudine: { nome: string; giorni: boolean[]; nota: string };
  streak: { nome: string; valoreLabel: string; evidenziata?: boolean; mutedValue?: boolean; mutedRow?: boolean }[];
  proposta?: { id: string; titolo: string; motivazione: string };
  report?: { periodoLabel: string; testo: string }; // il racconto scritto da Claude (§8.6)
}

export interface NuovaAbitudine {
  nome: string;
  targetSettimanale: number; // da 1 a 7
}

export interface ModificaAbitudine {
  nome?: string;
  targetSettimanale?: number;
  attiva?: boolean;
}

// — Regole di contesto —

/**
 * Una regola che Custode ha trovato da sé e che aspetta una tua risposta (§8.10).
 *
 * I cinque campi c'erano da prima che esistesse un motore; `descrizione` è
 * arrivata con lui, e senza di lei una proposta si approverebbe senza sapere
 * quando parlerà.
 */
export interface RegolaProposta {
  id: string;
  triggerTipo: string;
  /** 'alta' | 'media' | 'bassa'. A parole: nessuno ha calibrato un numero. */
  confidenza: string;
  /** Il promemoria che riceverai quando scatta. */
  testo: string;
  /** I numeri che l'hanno fatta nascere. Senza, «Approva» è un bottone al buio. */
  motivazione: string;
  /** Quando scatterebbe, detto a parole — la stessa frase della riga di una
   *  regola attiva e del promemoria su Telegram. */
  descrizione: string;
}

export interface RegolaAttiva {
  id: string;
  triggerTipo: string;
  nome: string;
  stato: 'attiva' | 'pausa';
  descrizione: string;
  attenuata?: boolean;
}

export interface RegoleData {
  titolo: string;
  spiegazione: string;
  stats: { attive: number; daApprovare: number; scattateSettimana: number; inPausa: number };
  proposte: RegolaProposta[];
  regoleAttive: RegolaAttiva[];
  attivitaSettimana: { nome: string; conteggio: number }[];
  attivitaNota?: string;
  tipiTrigger: { tipo: string; descrizione: string }[];
  scartate: { nome: string; dataLabel: string }[];
}

// — Impostazioni (§8) —

/**
 * Le impostazioni che si cambiano senza riavviare niente.
 *
 * **Ci sono solo le manopole che girano qualcosa.** Il contratto aveva da
 * sempre più campi di quanti moduli esistessero — digest mattutino (§8.13), ora
 * della voce di diario, ore di silenzio, le quattro approvazioni, il primo
 * giorno della settimana — e nessuno di quelli è cablato a niente. Si omettono,
 * che è la regola già scritta in cima ad API.md: un campo il cui modulo non è
 * ancora attivo si **omette**, non si mette a zero. Torneranno, uno alla volta,
 * col modulo che li legge.
 *
 * I **segreti** non passano di qui (§9): restano nel `.env` del Pi, e da questa
 * pagina si vede solo se ci sono.
 */
export interface ImpostazioniData {
  botStatoLabel: string; // se il bot è configurato — vivo non è osservabile da qui
  apiStatoLabel: string; // "API online · 08:41"
  orari: {
    riepilogoSettimanaleGiorno: 'domenica' | 'lunedi';
    riepilogoSettimanaleOra: string; // HH:MM
    /**
     * Quando Custode cerca pattern e ti propone una regola (§8.10). HH:MM.
     *
     * Finché non la sposti vale l'ora del riepilogo, e quello che arriva qui è
     * già il valore risolto: la pagina mostra l'ora a cui il job **parte
     * davvero**, non un campo vuoto da interpretare.
     */
    proposteRegoleOra: string; // HH:MM
    /**
     * Il margine dopo l'ultima lezione prima di considerarti a casa (§8.10).
     * Si salva già adesso e lo leggerà l'inferenza «sei probabilmente a casa»,
     * come `calendar_events.tipo` esisteva prima del tagging.
     */
    checkInMinutiDopo: number;
  };
  /**
   * `settimanale` è **assente** finché non l'hai mai impostato, né qui né nel
   * `.env`: allora la Home omette il blocco delle spese, perché una barra ha
   * bisogno di un tetto (§8.5).
   */
  budget: { settimanale?: number };
  connessioni: { nome: string; dettaglio: string; stato: 'collegato' | 'non_collegato' }[];
  dati: { vociDiario: number; speseRegistrate: number; ultimoBackupLabel: string };
  sistema: { apiOnline: boolean; ultimoSyncCalendarioLabel: string; versione: string };
  /** Cosa vale ancora dal `.env` perché non l'hai mai deciso da qui. */
  notaLabel?: string;
}

/**
 * Corpo di `PATCH /api/impostazioni`: solo i blocchi che vuoi cambiare.
 *
 * `budget.settimanale: null` **cancella** il budget; un campo che non mandi è
 * un campo che non volevi toccare. Sono due cose diverse, e il backend le
 * distingue da quali chiavi arrivano, non dal loro valore.
 */
export interface ModificaImpostazioni {
  orari?: Partial<ImpostazioniData['orari']>;
  budget?: { settimanale?: number | string | null };
}

// — assistente ("A Custode") —

export interface MessaggioAssistenteInput {
  testo: string;
}

export interface MessaggioAssistenteOutput {
  /**
   * Una frase per ogni cosa fatta, nell'ordine in cui è stata fatta. Un
   * messaggio può chiederne più d'una («giornata pesante, devo ricordarmi di
   * mandare la mail» è insieme una nota di diario e un task), e il diario è
   * sempre l'ultima. Mai vuota.
   */
  risposteLabel: string[];
}
