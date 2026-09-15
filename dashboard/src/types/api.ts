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

/** Uno dei quattro tipi di §8.10. Le etichette arrivano dal backend. */
export interface TipoEvento {
  valore: string; // 'lezione' | 'palestra' | 'viaggio' | 'altro'
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

export interface RegolaProposta {
  id: string;
  triggerTipo: string;
  confidenza: string;
  testo: string;
  motivazione: string;
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

// — Impostazioni —

export interface ImpostazioniData {
  botStatoLabel: string; // "@custode_bot · ultimo messaggio 22 minuti fa"
  apiStatoLabel: string; // "API online · sync 08:40"
  orari: {
    digestMattutino: string;
    checkInMinutiDopo: number;
    voceDiarioOra: string;
    riepilogoSettimanaleGiorno: 'domenica' | 'lunedi';
    oreSilenzio: { inizio: string; fine: string };
  };
  approvazioni: {
    vociDiario: 'chiedi' | 'automatico';
    nuoveRegole: 'chiedi' | 'automatico';
    categorieSpesa: 'chiedi' | 'automatico';
    scontrini: 'chiedi' | 'automatico';
  };
  connessioni: { nome: string; dettaglio: string; stato: 'collegato' | 'attiva' | 'non_collegato' }[];
  primaSettimana: 'lunedi' | 'domenica';
  budget: { settimanale: number; mensile: number; sogliaAvvisoPercento: number };
  dati: { vociDiario: number; speseRegistrate: number; messaggiBot: number; ultimoBackupLabel: string };
  sistema: { apiOnline: boolean; ultimoSyncCalendarioLabel: string; versione: string };
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
