import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { Movimento, SpeseData } from '../types/api';

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
