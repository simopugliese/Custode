import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import { useInvalidateShared } from './useHome';
import type { TaskData, TaskItem } from '../types/api';

export function useTaskPage(vista: 'scadenza' | 'provenienza' | 'completati') {
  return useQuery({
    queryKey: queryKeys.task(vista),
    queryFn: () => api.get<TaskData>(`/task?vista=${vista}`),
  });
}

/**
 * Crea un task dalla pagina, senza passare dal modello: `POST /api/task` è
 * nel contratto da sempre, ma nessun bottone lo chiamava.
 */
export function useCreaTask() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: ({ titolo, scadenza }: { titolo: string; scadenza?: string }) =>
      api.post<TaskItem>('/task', scadenza ? { titolo, scadenza } : { titolo }),
    onSuccess: invalidate,
  });
}

export function useRinviaTask() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: ({ id, giorni = 1 }: { id: string; giorni?: number }) =>
      api.patch<TaskItem>(`/task/${id}`, { rinviaGiorni: giorni }),
    onSuccess: invalidate,
  });
}

export { useToggleTask } from './useHome';
