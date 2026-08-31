/**
 * Tipi condivisi per le risposte dell'API di Custode.
 * Rispecchiano lo schema dati in project/uploads/assistente-ia-personale-design.md (§7).
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
  ora: string;
  titolo: string;
  luogo?: string;
  meta?: string; // es. "automatico"
}

export interface CategoriaSpesa {
  nome: string;
  importo: number;
  quota: number; // 0-1, quota sul totale/budget per il grafico a barre
}

// — Home —

export interface HomeData {
  dataLabel: string; // "sabato 30 agosto, 08:41"
  titolo: string; // frase-riepilogo
  proposteAutomazioni: number;
  stats: {
    taskAperti: number;
    spesaSettimana: number;
    streakPiuLunga: number;
    listaSpesaDaPrendere: number;
  };
  taskOggi: TaskItem[];
  calendarioOggi: CalendarEventItem[];
  abitudini: HabitRow[];
  speseSettimana: {
    categorie: CategoriaSpesa[];
    budget: number;
    speso: number;
    scontriniInAttesa: number;
  };
  listaSpesa: ShoppingItem[];
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

export interface TaskData {
  dataLabel: string;
  titolo: string;
  avviso?: string;
  stats: { aperti: number; oggi: number; inRitardo: number; chiusiSettimana: number };
  inRitardo: TaskItem[];
  oggi: TaskItem[];
  prossimiSetteGiorni: TaskItem[];
  senzaScadenza: TaskItem[];
  chiusiPerGiorno: number[]; // 7 valori, lun -> dom
  ricorrenti: { nome: string; frequenzaLabel: string }[];
  provenienza: { origine: string; conteggio: number }[];
}

// — Lista della spesa —

export interface ListaSpesaData {
  aggiornataAlleLabel: string;
  titolo: string;
  suggerimento?: { testo: string; voci: string[] };
  stats: { daPrendere: number; presi: number; stimaCarrello: number; ultimaSpesaGiorni: number };
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
  descrizione: string;
  categoria: string;
  importo: number;
  daScontrino?: boolean;
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
  rispostaLabel?: string;
}
