import { AvvisoRow } from './AvvisoRow';
import { Icon, ICONS, type IconName } from '../lib/icons';
import { useMeteo } from '../hooks/useMeteo';
import { messaggioErrore } from '../lib/apiClient';

// L'API sceglie l'icona; se un giorno ne manda una che la dashboard non
// conosce, una nuvola è meglio di un riquadro vuoto.
const icona = (nome: string): IconName => (nome in ICONS ? (nome as IconName) : 'cloud');

const maiuscola = (testo: string) => testo.charAt(0).toUpperCase() + testo.slice(1);

/**
 * Il meteo in Home (§8.12): oggi in grande, i giorni dopo in righe.
 *
 * Ha una query sua e **non** passa da `AsyncState`: un servizio meteo giù non
 * deve sostituire la pagina con un errore, quindi l'errore resta una riga
 * qui dentro. Finché carica non disegna niente, così la colonna non salta.
 */
export function BloccoMeteo() {
  const { data, isLoading, error } = useMeteo();

  if (isLoading) return null;
  if (error) {
    return (
      <div className="cu-muted" style={{ fontSize: 12 }} role="status">
        Meteo non disponibile — {messaggioErrore(error)}
      </div>
    );
  }
  if (!data) return null;
  if (!data.previsioni?.length) {
    return data.notaLabel ? (
      <div className="cu-muted" style={{ fontSize: 12 }}>
        {data.notaLabel}
      </div>
    ) : null;
  }

  const [oggi, ...seguenti] = data.previsioni;
  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <h5>Meteo</h5>
        {data.posizioneLabel && (
          <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
            {data.posizioneLabel}
          </span>
        )}
      </div>

      <div
        className="row"
        style={{
          gap: 16,
          paddingBottom: 14,
          borderBottom: seguenti.length ? '1px solid var(--color-rule)' : undefined,
        }}
      >
        <span style={{ display: 'flex', color: 'var(--color-accent)' }}>
          <Icon name={icona(oggi.icona)} size={38} />
        </span>
        <div>
          <div className="num" style={{ fontSize: 34 }}>
            {oggi.massima}°
          </div>
          <div className="cu-muted" style={{ fontSize: 12 }}>
            {maiuscola(oggi.descrizione)} · min {oggi.minima}°
            {oggi.probPioggia !== undefined && ` · pioggia ${oggi.probPioggia}%`}
          </div>
        </div>
      </div>

      {seguenti.map((p) => (
        <div key={p.giornoLabel} className="listrow">
          <span style={{ display: 'flex', opacity: 0.7 }}>
            <Icon name={icona(p.icona)} size={16} />
          </span>
          <span style={{ fontSize: 13 }}>{maiuscola(p.giornoLabel)}</span>
          <span className="cu-muted" style={{ fontSize: 12 }}>
            {p.descrizione}
          </span>
          <span className="cu-mono" style={{ marginLeft: 'auto', fontSize: 13 }}>
            {p.massima}° <span className="cu-muted">/ {p.minima}°</span>
          </span>
        </div>
      ))}

      {data.consiglioLabel && <AvvisoRow icon="info">{data.consiglioLabel}</AvvisoRow>}
    </div>
  );
}
