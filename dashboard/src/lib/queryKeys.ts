export const queryKeys = {
  home: ['home'] as const,
  meteo: ['meteo'] as const,
  diario: (vista: string) => ['diario', vista] as const,
  calendario: (vista: string) => ['calendario', vista] as const,
  lezioni: (vista: string) => ['lezioni', vista] as const,
  task: (vista: string) => ['task', vista] as const,
  listaSpesa: (ordina: string) => ['lista-spesa', ordina] as const,
  spese: (periodo: string, limite: number) => ['spese', periodo, limite] as const,
  abitudini: (vista: string) => ['abitudini', vista] as const,
  regole: ['regole'] as const,
  impostazioni: ['impostazioni'] as const,
};
