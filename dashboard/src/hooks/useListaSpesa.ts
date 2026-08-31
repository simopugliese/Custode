import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import { useInvalidateShared } from './useHome';
import type { ListaSpesaData } from '../types/api';

export function useListaSpesaPage(ordina: 'reparto' | 'aggiunta') {
  return useQuery({
    queryKey: queryKeys.listaSpesa(ordina),
    queryFn: () => api.get<ListaSpesaData>(`/lista-spesa?ordina=${ordina}`),
  });
}

export function useSvuotaPresi() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: () => api.post('/lista-spesa/svuota-presi'),
    onSuccess: invalidate,
  });
}

export function useAggiungiVoceSpesa() {
  const invalidate = useInvalidateShared();
  return useMutation({
    mutationFn: (nome: string) => api.post('/lista-spesa', { nome }),
    onSuccess: invalidate,
  });
}

export { useToggleShoppingItem } from './useHome';
