import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type {
  CategoriaSpesaGestione,
  ModificaSpesa,
  Movimento,
  NuovaSpesa,
  SpeseData,
} from '../types/api';

export function useSpese(periodo: 'settimana' | 'mese' | 'anno') {
  return useQuery({
    queryKey: queryKeys.spese(periodo),
    queryFn: () => api.get<SpeseData>(`/spese?periodo=${periodo}`),
  });
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
