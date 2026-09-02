import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { Tag } from '../components/Tag';
import { Bar } from '../components/Bar';
import { Money, Percent } from '../components/Money';
import { Icon } from '../lib/icons';
import { useConfermaScontrino, useSpese } from '../hooks/useSpese';

const PERIODI = [
  { value: 'settimana', label: 'Settimana' },
  { value: 'mese', label: 'Mese' },
  { value: 'anno', label: 'Anno' },
] as const;

export default function Spese() {
  const [periodo, setPeriodo] = useState<'settimana' | 'mese' | 'anno'>('mese');
  const { data, isLoading, error, refetch } = useSpese(periodo);
  const conferma = useConfermaScontrino();

  return (
    <>
      <PageHeader kicker={`Spese${data ? ` · ${data.periodoLabel}` : ''}`} title={data?.titolo ?? 'Spese'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {data.scontrinoInAttesa && (
              <AvvisoRow
                icon="receipt"
                actionLabel="Conferma"
                actionIcon="check"
                onAction={() => conferma.mutate({ id: data.scontrinoInAttesa!.id })}
              >
                Uno scontrino letto da foto aspetta conferma: <b>{data.scontrinoInAttesa.luogo}, {data.scontrinoInAttesa.importo.toFixed(2)} €</b> — Custode l'ha messo in {data.scontrinoInAttesa.categoriaProposta}.
              </AvvisoRow>
            )}

            <StatsBar
              items={[
                { label: 'Totale periodo', value: <Money value={data.stats.totaleMese} /> },
                { label: 'Media al giorno', value: <Money value={data.stats.mediaGiorno} /> },
                { label: 'Categoria maggiore', value: <span style={{ fontSize: 34, paddingTop: 8, display: 'block' }}>{data.stats.categoriaMaggiore}</span> },
                { label: 'Su periodo prec.', value: <Percent value={data.stats.variazioneMesePrecedente} /> },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div className="row" style={{ gap: 6 }}>
                  <span className="cu-kicker" style={{ flex: 'none' }}>Periodo</span>
                  <div style={{ marginLeft: 6 }}>
                    <SegmentedControl name="vSpese" options={[...PERIODI]} value={periodo} onChange={(v) => setPeriodo(v as typeof periodo)} />
                  </div>
                  <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                    <Icon name="plus" size={14} />
                    Registra spesa
                  </button>
                </div>

                {data.andamentoGiorni.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 14 }}>Andamento del periodo</h5>
                    <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height: 120, borderBottom: '1px solid var(--color-divider)', paddingBottom: 2 }}>
                      {data.andamentoGiorni.map((pct, i) => (
                        <div
                          key={i}
                          style={{
                            flex: 1,
                            height: `${Math.max(pct, 2)}%`,
                            background: i === data.andamentoGiorni.length - 1 ? 'var(--color-accent)' : 'var(--color-accent-300)',
                          }}
                        />
                      ))}
                    </div>
                    <div className="row" style={{ marginTop: 8 }}>
                      <span className="cu-kicker">Inizio periodo</span>
                      <span className="cu-kicker" style={{ marginLeft: 'auto' }}>oggi</span>
                    </div>
                  </div>
                )}

                <div>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <h5>Movimenti recenti</h5>
                    <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                      Esporta CSV
                      <Icon name="download" size={14} />
                    </button>
                  </div>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Data</th>
                        <th>Descrizione</th>
                        <th>Categoria</th>
                        <th style={{ textAlign: 'right' }}>Importo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.movimenti.map((m) => (
                        <tr key={m.id}>
                          <td className="cu-mono">{m.dataLabel}</td>
                          <td>
                            {m.descrizione}
                            {m.daScontrino && <span className="cu-muted"> · da scontrino</span>}
                          </td>
                          <td>
                            <Tag variant="neutral">{m.categoria}</Tag>
                          </td>
                          <td className="cu-mono" style={{ textAlign: 'right' }}>{m.importo.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {data.movimenti.length === 0 && <div className="cu-muted" style={{ fontSize: 13, padding: '14px 0' }}>Nessun movimento nel periodo.</div>}
                  <button className="btn btn-secondary" style={{ marginTop: 14 }}>Carica altri movimenti</button>
                </div>
              </div>

              <div className="colR">
                {data.categorie.length > 0 && (
                  <div>
                    <div className="row" style={{ marginBottom: 12 }}>
                      <h5>Categorie</h5>
                      <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>create da Custode</span>
                    </div>
                    <div>
                      {data.categorie.map((c) => (
                        <div className="listrow" style={{ padding: '11px 0' }} key={c.nome}>
                          <span style={{ fontSize: 14 }}>{c.nome}</span>
                          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                            <Bar quota={c.quota} width={70} />
                            <span className="cu-mono" style={{ fontSize: 14, width: 52, textAlign: 'right' }}>{c.importo.toFixed(2)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                    {data.categoriaNota && <div className="cu-muted" style={{ fontSize: 12, marginTop: 10 }}>{data.categoriaNota}</div>}
                  </div>
                )}

                {data.confronto.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Confronto</h5>
                    <div>
                      {data.confronto.map((c) => (
                        <div className="listrow" style={{ padding: '10px 0' }} key={c.label}>
                          <span style={{ fontSize: 14 }}>{c.label}</span>
                          <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 14 }}>{c.importo.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {data.scontrinoInAttesa && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>In attesa</h5>
                    <div style={{ borderTop: '2px solid var(--color-accent)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <div className="row">
                        <span style={{ fontSize: 14, fontWeight: 600 }}>{data.scontrinoInAttesa.luogo}</span>
                        <span className="cu-mono" style={{ marginLeft: 'auto', fontSize: 14, fontWeight: 600 }}>{data.scontrinoInAttesa.importo.toFixed(2)}</span>
                      </div>
                      <div className="cu-muted" style={{ fontSize: 12 }}>
                        Letto da foto del {data.scontrinoInAttesa.dataLabel} · categoria proposta: {data.scontrinoInAttesa.categoriaProposta}
                      </div>
                      <div className="row" style={{ gap: 6 }}>
                        <button className="btn btn-primary" onClick={() => conferma.mutate({ id: data.scontrinoInAttesa!.id })} disabled={conferma.isPending}>
                          Conferma
                        </button>
                        <button className="btn btn-ghost">Cambia categoria</button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«segna 8€ colazione al bar», «quanto ho speso in ristoranti questo mese?»" />
    </>
  );
}
