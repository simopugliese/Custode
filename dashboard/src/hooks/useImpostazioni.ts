import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { ImpostazioniData } from '../types/api';

export function useImpostazioni() {
  return useQuery({ queryKey: queryKeys.impostazioni, queryFn: () => api.get<ImpostazioniData>('/impostazioni') });
}

export function useAggiornaImpostazioni() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<ImpostazioniData>) => api.patch<ImpostazioniData>('/impostazioni', patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.impostazioni }),
  });
}
