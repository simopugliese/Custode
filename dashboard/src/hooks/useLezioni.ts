import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { LezioniData, PianoRipasso } from '../types/api';

export function useLezioni(vista: 'settimana' | 'mese') {
  return useQuery({
    queryKey: queryKeys.lezioni(vista),
    queryFn: () => api.get<LezioniData>(`/lezioni?vista=${vista}`),
  });
}

export function useRigeneraPiano() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<PianoRipasso>(`/lezioni/piani/${id}/rigenera`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['lezioni'] }),
  });
}

export function useMandaPianoAlBot() {
  return useMutation({
    mutationFn: (id: string) => api.post(`/lezioni/piani/${id}/manda-al-bot`),
  });
}
