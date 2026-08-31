import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { DiarioData } from '../types/api';

export function useDiario(vista: 'timeline' | 'settimane' | 'mesi') {
  return useQuery({
    queryKey: queryKeys.diario(vista),
    queryFn: () => api.get<DiarioData>(`/diario?vista=${vista}`),
  });
}

export function useApprovaVoceDiario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/diario/${id}/approva`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diario'] }),
  });
}

export function useScartaVoceDiario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/diario/${id}/scarta`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diario'] }),
  });
}
