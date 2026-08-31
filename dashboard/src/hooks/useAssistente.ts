import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/apiClient';
import type { MessaggioAssistenteOutput } from '../types/api';

/**
 * Barra "A Custode" presente in ogni pagina: manda testo libero allo stesso
 * canale del bot Telegram (§8.1). Dopo l'invio invalida tutte le query così
 * un comando tipo «segna 8€ colazione al bar» si riflette appena elaborato.
 */
export function useAssistente() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (testo: string) => api.post<MessaggioAssistenteOutput>('/assistente/messaggio', { testo }),
    onSuccess: () => qc.invalidateQueries(),
  });
}
