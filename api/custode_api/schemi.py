"""Modelli di risposta dell'API.

I nomi dei campi sono in **camelCase** perché è la forma esatta che la
dashboard si aspetta (`dashboard/src/types/api.ts`): scriverli così, invece di
mapparli con degli alias, rende il confronto col contratto una lettura riga per
riga invece di un salto fra due tabelle.

Un campo il cui modulo non esiste ancora viene **omesso** dalla risposta (le
rotte usano `response_model_exclude_none`), non messo a zero: uno zero è un
dato, l'assenza no. Una lista *vuota* significa invece "il modulo c'è e non ha
niente da dire" — es. la lista della spesa davvero vuota.
"""

from __future__ import annotations

from pydantic import BaseModel


class TaskItem(BaseModel):
    id: str
    titolo: str
    fatto: bool
    scadenzaLabel: str | None = None
    meta: str | None = None
    tag: str | None = None
    rinvii: int | None = None


class ShoppingItem(BaseModel):
    id: str
    nome: str
    preso: bool
    quantita: str | None = None
    reparto: str
    tag: str | None = None


class SezioneTask(BaseModel):
    """Una sezione della colonna sinistra della pagina Task.

    Le sezioni sono decise dal backend in base alla vista richiesta: per
    scadenza sono "In ritardo/Oggi/…", per i completati sono per data di
    chiusura. La dashboard le stampa così come arrivano.
    """

    titolo: str
    task: list[TaskItem]
    notaVuoto: str | None = None


class StatsTask(BaseModel):
    aperti: int
    oggi: int
    inRitardo: int
    chiusiSettimana: int


class RicorrenteTask(BaseModel):
    nome: str
    frequenzaLabel: str


class ProvenienzaTask(BaseModel):
    origine: str
    conteggio: int


class TaskData(BaseModel):
    dataLabel: str
    titolo: str
    avviso: str | None = None
    stats: StatsTask
    sezioni: list[SezioneTask]
    chiusiPerGiorno: list[int]
    ricorrenti: list[RicorrenteTask]
    provenienza: list[ProvenienzaTask]


class RepartoListaSpesa(BaseModel):
    nome: str
    voci: list[ShoppingItem]


class SuggerimentoListaSpesa(BaseModel):
    testo: str
    voci: list[str]


class StatsListaSpesa(BaseModel):
    daPrendere: int
    presi: int
    # Richiedono lo storico delle spese (§8.5): finché quel modulo non esiste
    # restano assenti, e la dashboard mostra un trattino.
    stimaCarrello: float | None = None
    ultimaSpesaGiorni: int | None = None


class VoceSuggerita(BaseModel):
    nome: str
    frequenzaLabel: str


class SpesaRecente(BaseModel):
    dataLabel: str
    luogo: str
    importo: float


class RepartoFrequente(BaseModel):
    nome: str
    quota: float


class ListaSpesaData(BaseModel):
    aggiornataAlleLabel: str
    titolo: str
    suggerimento: SuggerimentoListaSpesa | None = None
    stats: StatsListaSpesa
    reparti: list[RepartoListaSpesa]
    presi: list[ShoppingItem]
    suggeriti: list[VoceSuggerita]
    ultimeSpese: list[SpesaRecente]
    repartiFrequenti: list[RepartoFrequente]


class HabitRow(BaseModel):
    id: str
    nome: str
    giorni: list[bool]
    progressoLabel: str
    evidenziata: bool | None = None


class CalendarEventItem(BaseModel):
    id: str
    ora: str
    titolo: str
    luogo: str | None = None
    meta: str | None = None


class CategoriaSpesa(BaseModel):
    nome: str
    importo: float
    quota: float


class SpeseSettimanaHome(BaseModel):
    categorie: list[CategoriaSpesa]
    budget: float
    speso: float
    scontriniInAttesa: int


class StatsHome(BaseModel):
    taskAperti: int
    listaSpesaDaPrendere: int
    # Assenti finché non esistono i moduli spese (§8.5) e abitudini (§8.6).
    spesaSettimana: float | None = None
    streakPiuLunga: int | None = None


class HomeData(BaseModel):
    dataLabel: str
    titolo: str
    stats: StatsHome
    taskOggi: list[TaskItem]
    listaSpesa: list[ShoppingItem]
    # Ognuno di questi blocchi appare solo quando il suo modulo è attivo.
    proposteAutomazioni: int | None = None
    calendarioOggi: list[CalendarEventItem] | None = None
    abitudini: list[HabitRow] | None = None
    speseSettimana: SpeseSettimanaHome | None = None


class VoceDiario(BaseModel):
    id: str
    dataLabel: str
    # 'da_approvare' | 'approvata' | 'assente'
    stato: str
    approvataAlleLabel: str | None = None
    testo: str | None = None
    tag: list[str]
    fonteLabel: str | None = None


class TemaRicorrente(BaseModel):
    nome: str
    occorrenze: int
    quota: float


class StatsDiario(BaseModel):
    vociDelMese: int
    giorniConsecutivi: int
    paroleMedia: int
    temaPiuRicorrente: str


class RiepilogoDiario(BaseModel):
    label: str
    testo: str
    generatoLabel: str


class RiepilogoMensile(BaseModel):
    label: str
    testo: str


class DiarioData(BaseModel):
    periodoLabel: str
    titolo: str
    vociApprovate: int
    giorniTotali: int
    vociInAttesa: int
    stats: StatsDiario
    voci: list[VoceDiario]
    altreVociVecchie: int
    # I riepiloghi li scrive il job settimanale in worker/ (§8.4): finché non
    # esiste restano assenti, e la dashboard non disegna quei due blocchi.
    riepilogoSettimanale: RiepilogoDiario | None = None
    riepilogoMensile: RiepilogoMensile | None = None
    temiDelMese: list[TemaRicorrente]
    coperturaMese: list[bool]
    coperturaNota: str


# — corpi delle richieste —


class NuovoTask(BaseModel):
    titolo: str
    # ISO-8601: "2026-09-04" per tutto il giorno, "2026-09-04T18:00" a un'ora.
    scadenza: str | None = None


class ModificaTask(BaseModel):
    fatto: bool | None = None
    rinviaGiorni: int | None = None


class NuovaVoceSpesa(BaseModel):
    nome: str
    quantita: str | None = None
    reparto: str | None = None


class ModificaVoceSpesa(BaseModel):
    preso: bool


class MessaggioAssistente(BaseModel):
    testo: str


class RispostaAssistente(BaseModel):
    rispostaLabel: str | None = None
