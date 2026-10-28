import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type {
  CategoriaSpesaGestione,
  ModificaSpesa,
  Movimento,
  NuovaSpesa,
  SpeseData,
} from '../types/api';

export type PeriodoSpese = 'settimana' | 'mese' | 'anno';

// Quanti movimenti chiedere in più ad ogni «Carica altri movimenti». Il primo
// carico è quello di default dell'API (50), poi si cresce di un passo alla volta.
export const PASSO_MOVIMENTI = 50;

export function useSpese(periodo: PeriodoSpese, limite: number = PASSO_MOVIMENTI) {
  return useQuery({
    queryKey: queryKeys.spese(periodo, limite),
    queryFn: () => api.get<SpeseData>(`/spese?periodo=${periodo}&limite=${limite}`),
    // Allargando il limite la lista non deve sparire per rimpiazzarsi: resta
    // quella di prima finché arriva la più lunga.
    placeholderData: keepPreviousData,
  });
}

/** Tutti i movimenti del periodo, per l'export: stesso tetto dell'API. */
export function leggiTuttiIMovimenti(periodo: PeriodoSpese) {
  return api.get<SpeseData>(`/spese?periodo=${periodo}&limite=5000`).then((d) => d.movimenti);
}

export function useConfermaScontrino() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, categoria }: { id: string; categoria?: string }) =>
      api.post<Movimento>(`/spese/${id}/conferma`, { categoria }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['spese'] });
      qc.invalidateQueries({ queryKey: ['home'] });
    },
  });
}

function useInvalidaSpese() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ['spese'] });
    qc.invalidateQueries({ queryKey: ['home'] });
  };
}

export function useRegistraSpesa() {
  const invalida = useInvalidaSpese();
  return useMutation({
    mutationFn: (corpo: NuovaSpesa) => api.post<Movimento>('/spese', corpo),
    onSuccess: invalida,
  });
}

export function useModificaSpesa() {
  const invalida = useInvalidaSpese();
  return useMutation({
    mutationFn: ({ id, ...corpo }: ModificaSpesa & { id: string }) =>
      api.patch<Movimento>(`/spese/${id}`, corpo),
    onSuccess: invalida,
  });
}

export function useEliminaSpesa() {
  const invalida = useInvalidaSpese();
  return useMutation({
    mutationFn: (id: string) => api.del(`/spese/${id}`),
    onSuccess: invalida,
  });
}

export function useCategorieSpesa() {
  return useQuery({
    queryKey: ['spese', 'categorie'],
    queryFn: () => api.get<CategoriaSpesaGestione[]>('/spese/categorie'),
  });
}

export function useModificaCategoria() {
  const invalida = useInvalidaSpese();
  return useMutation({
    mutationFn: ({ id, ...corpo }: { id: string; nome?: string; attiva?: boolean }) =>
      api.patch<CategoriaSpesaGestione>(`/spese/categorie/${id}`, corpo),
    onSuccess: invalida,
  });
}

export function useUnisciCategorie() {
  const invalida = useInvalidaSpese();
  return useMutation({
    mutationFn: ({ id, inId }: { id: string; inId: string }) =>
      api.post(`/spese/categorie/${id}/unisci`, { inId }),
    onSuccess: invalida,
  });
}
