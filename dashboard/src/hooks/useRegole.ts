import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { RegolaAttiva, RegoleData } from '../types/api';

export function useRegole() {
  return useQuery({ queryKey: queryKeys.regole, queryFn: () => api.get<RegoleData>('/regole') });
}

export function useApprovaRegola() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<RegolaAttiva>(`/regole/${id}/approva`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.regole });
      qc.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}

export function useScartaRegola() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/regole/${id}/scarta`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.regole }),
  });
}

export function useImpostaStatoRegola() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, stato }: { id: string; stato: 'attiva' | 'pausa' }) =>
      api.patch<RegolaAttiva>(`/regole/${id}`, { stato }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.regole }),
  });
}
