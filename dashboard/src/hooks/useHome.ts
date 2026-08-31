import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { HomeData } from '../types/api';

export function useHome() {
  return useQuery({ queryKey: queryKeys.home, queryFn: () => api.get<HomeData>('/home') });
}

/** invalida tutte le pagine che possono mostrare un task o una voce della lista spesa */
export function useInvalidateShared() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ['home'] });
    qc.invalidateQueries({ queryKey: ['task'] });
    qc.invalidateQueries({ queryKey: ['lezioni'] });
    qc.invalidateQueries({ queryKey: ['lista-spesa'] });
    qc.invalidateQueries({ queryKey: ['abitudini'] });
  };
}

export function useToggleTask() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: ({ id, fatto }: { id: string; fatto: boolean }) =>
      api.patch(`/task/${id}`, { fatto }),
    onSuccess: invalidate,
  });
}

export function useToggleShoppingItem() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: ({ id, preso }: { id: string; preso: boolean }) =>
      api.patch(`/lista-spesa/${id}`, { preso }),
    onSuccess: invalidate,
  });
}
