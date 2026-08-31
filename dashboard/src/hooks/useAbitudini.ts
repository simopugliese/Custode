import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import { useInvalidateShared } from './useHome';
import type { AbitudiniData, AbitudineDettaglio } from '../types/api';

export function useAbitudiniPage(vista: 'settimana' | 'mese') {
  return useQuery({
    queryKey: queryKeys.abitudini(vista),
    queryFn: () => api.get<AbitudiniData>(`/abitudini?vista=${vista}`),
  });
}

export function useLogAbitudine() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: ({ id, data, fatto }: { id: string; data: string; fatto: boolean }) =>
      api.patch<AbitudineDettaglio>(`/abitudini/${id}/log`, { data, fatto }),
    onSuccess: invalidate,
  });
}

export function useRispondiPropostaAbitudine() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: ({ id, accetta }: { id: string; accetta: boolean }) =>
      api.post(`/abitudini/${id}/proposta/${accetta ? 'accetta' : 'rifiuta'}`),
    onSuccess: invalidate,
  });
}
