import { useMeteo } from '../hooks/useMeteo';
import { messaggioErrore } from '../lib/apiClient';

/**
 * Il meteo in Home (§8.12). Ha una query sua e **non** passa da `AsyncState`:
 * un servizio meteo giù non deve sostituire la pagina con un errore, quindi
 * l'errore resta una riga qui dentro.
 */
export function BloccoMeteo() {
  const { data, isLoading, error } = useMeteo();

  if (isLoading) return null;
  if (error) {
    return (
      <div className="cu-muted" style={{ fontSize: 12, marginBottom: 14 }} role="status">
        Meteo non disponibile — {messaggioErrore(error)}
      </div>
    );
  }
  if (!data) return null;
  if (!data.previsioni) {
    return data.notaLabel ? (
      <div className="cu-muted" style={{ fontSize: 12, marginBottom: 14 }}>
        {data.notaLabel}
      </div>
    ) : null;
  }

  return (
    <div style={{ marginBottom: 14 }}>
      <div className="row" style={{ gap: 16, flexWrap: 'wrap' }}>
        <h5>Meteo</h5>
        {data.previsioni.map((p) => (
          <span key={p.giornoLabel} style={{ fontSize: 13 }}>
            <b>{p.giornoLabel}</b> {p.descrizione} {p.minima}–{p.massima}°
            {p.probPioggia !== undefined && <span className="cu-muted"> · {p.probPioggia}%</span>}
          </span>
        ))}
        {data.posizioneLabel && (
          <span className="cu-muted" style={{ fontSize: 12 }}>
            ({data.posizioneLabel})
          </span>
        )}
      </div>
      {data.consiglioLabel && <div style={{ fontSize: 13, marginTop: 4 }}>{data.consiglioLabel}</div>}
    </div>
  );
}
