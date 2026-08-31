export const queryKeys = {
  home: ['home'] as const,
  diario: (vista: string) => ['diario', vista] as const,
  lezioni: (vista: string) => ['lezioni', vista] as const,
  task: (vista: string) => ['task', vista] as const,
  listaSpesa: (ordina: string) => ['lista-spesa', ordina] as const,
  spese: (periodo: string) => ['spese', periodo] as const,
  abitudini: (vista: string) => ['abitudini', vista] as const,
  regole: ['regole'] as const,
  impostazioni: ['impostazioni'] as const,
};
