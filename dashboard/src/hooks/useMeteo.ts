import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiConfigured } from '../lib/apiClient';
import { queryKeys } from '../lib/queryKeys';
import type { MeteoData } from '../types/api';

export function useMeteo() {
  return useQuery({ queryKey: queryKeys.meteo, queryFn: () => api.get<MeteoData>('/meteo') });
}

// Due decimali sono circa un chilometro: basta per il meteo e non dice in che
// casa sei. L'API lo ripete, ma la posizione precisa non deve nemmeno partire.
const arrotonda = (n: number) => Math.round(n * 100) / 100;

// Una volta per caricamento della pagina: il browser potrebbe richiedere il
// permesso ad ogni navigazione, e il Layout (che chiama l'hook) resta montato.
let giaChiesta = false;

/**
 * Dice a Custode dove sei, quando apri la dashboard (§8.12).
 *
 * Se il permesso manca, il browser non risponde o l'API non c'è, non succede
 * niente e non si mostra nessun errore: resta l'ultima posizione nota, che è
 * quello che il meteo e il digest del mattino sanno già fare.
 */
export function useAggiornaPosizione() {
  const qc = useQueryClient();
  const { mutate: invia } = useMutation({
    mutationFn: (p: { lat: number; lon: number }) => api.put('/posizione', p),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.meteo }),
  });

  useEffect(() => {
    if (giaChiesta || !apiConfigured() || !('geolocation' in navigator)) return;
    giaChiesta = true;
    navigator.geolocation.getCurrentPosition(
      (pos) => invia({ lat: arrotonda(pos.coords.latitude), lon: arrotonda(pos.coords.longitude) }),
      () => {
        /* permesso negato o nessun segnale: si tiene l'ultima posizione */
      },
      // Bassa precisione: basta la cella o il wifi, e risponde prima. Una
      // posizione di dieci minuti fa va bene, la strada non è cambiata.
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 10 * 60 * 1000 },
    );
  }, [invia]);
}
