import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import { useInvalidateShared } from './useHome';
import type { TaskData, TaskItem } from '../types/api';

export function useTaskPage(vista: 'scadenza' | 'progetto' | 'completati') {
  return useQuery({
    queryKey: queryKeys.task(vista),
    queryFn: () => api.get<TaskData>(`/task?vista=${vista}`),
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
