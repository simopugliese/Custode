import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type {
  CalendarioData,
  CorrezioneTag,
  ModificaTipoEvento,
  NuovoTipoEvento,
  TipoEventoSalvato,
} from '../types/api';

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

/**
 * I tipi di evento si gestiscono da qui, non dalle impostazioni (§8.10, pezzo
 * 6): si guardano dove si vedono gli impegni, ed è nel menu di correzione che
 * ci si accorge che ne manca uno.
 *
 * Tutte e tre le mutazioni invalidano l'intera pagina Calendario e la Home: un
 * tipo rinominato cambia l'etichetta di ogni evento che ce l'ha, senza che
 * nessun evento sia stato toccato — e se la pagina non si rileggesse, quelle
 * etichette resterebbero vecchie fino a un ricaricamento a mano.
 */
function useInvalidaCalendario() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ['calendario'] });
    qc.invalidateQueries({ queryKey: queryKeys.home });
  };
}

export function useCreaTipoEvento() {
  const invalida = useInvalidaCalendario();
  return useMutation({
    mutationFn: (corpo: NuovoTipoEvento) =>
      api.post<TipoEventoSalvato>('/calendario/tipi', corpo),
    onSuccess: invalida,
  });
}

export function useModificaTipoEvento() {
  const invalida = useInvalidaCalendario();
  return useMutation({
    mutationFn: ({ slug, ...corpo }: ModificaTipoEvento & { slug: string }) =>
      api.patch<TipoEventoSalvato>(`/calendario/tipi/${slug}`, corpo),
    onSuccess: invalida,
  });
}

export function useEliminaTipoEvento() {
  const invalida = useInvalidaCalendario();
  return useMutation({
    mutationFn: (slug: string) => api.del(`/calendario/tipi/${slug}`),
    onSuccess: invalida,
  });
}
