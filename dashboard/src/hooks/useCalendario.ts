import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { CalendarioData, CorrezioneTag } from '../types/api';

export type VistaCalendario = 'settimana' | 'mese' | 'da_rivedere';

export function useCalendario(vista: VistaCalendario) {
  return useQuery({
    queryKey: queryKeys.calendario(vista),
    queryFn: () => api.get<CalendarioData>(`/calendario?vista=${vista}`),
  });
}

/**
 * La correzione di §8.10 ("tu correggi se serve"). Tocca tutta la serie, non
 * la sola occorrenza: per questo la risposta dice quante occorrenze ha
 * cambiato, e si invalida l'intera pagina invece della riga toccata.
 */
export function useCorreggiTagEvento() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, tipo }: { id: string; tipo: string }) =>
      api.patch<CorrezioneTag>(`/calendario/${id}`, { tipo }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calendario'] });
      // La Home mostra gli stessi eventi: un tipo corretto qui non deve
      // restare vecchio là fino al prossimo ricaricamento.
      qc.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}
