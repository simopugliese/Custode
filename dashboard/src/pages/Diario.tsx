import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { Tag } from '../components/Tag';
import { Bar } from '../components/Bar';
import { DotGrid } from '../components/DotGrid';
import { Icon } from '../lib/icons';
import { useApprovaVoceDiario, useDiario, useScartaVoceDiario } from '../hooks/useDiario';

const VISTE = [
  { value: 'timeline', label: 'Timeline' },
  { value: 'settimane', label: 'Settimane' },
  { value: 'mesi', label: 'Mesi' },
] as const;

export default function Diario() {
  const [vista, setVista] = useState<'timeline' | 'settimane' | 'mesi'>('timeline');
  const { data, isLoading, error, refetch } = useDiario(vista);
  const approva = useApprovaVoceDiario();
  const scarta = useScartaVoceDiario();

  return (
    <>
      <PageHeader kicker={`Diario${data ? ` · ${data.periodoLabel}` : ''}`} title={data?.titolo ?? 'Diario'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {data.vociInAttesa > 0 && (
              <AvvisoRow icon="pen-line" actionLabel="Leggila" actionIcon="arrow-down">
                {data.vociInAttesa === 1 ? (
                  <>
                    La voce di <b>ieri</b> è pronta e aspetta la tua approvazione prima di entrare nel diario.
                  </>
                ) : (
                  <>
                    <b>{data.vociInAttesa} voci</b> aspettano la tua approvazione prima di entrare nel diario.
                  </>
                )}
              </AvvisoRow>
            )}

            <StatsBar
              items={[
                { label: 'Voci del mese', value: <>{data.stats.vociDelMese}<small> / {data.giorniTotali}</small></> },
                { label: 'Giorni consecutivi', value: <>{data.stats.giorniConsecutivi}<small style={{ opacity: 0.55 }}> {data.stats.giorniConsecutivi === 1 ? 'giorno' : 'giorni'}</small></>, accent: true },
                { label: 'Parole in media', value: data.stats.paroleMedia },
                { label: 'Tema più ricorrente', value: <span style={{ fontSize: 34, paddingTop: 8, display: 'block' }}>{data.stats.temaPiuRicorrente}</span> },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div className="row" style={{ gap: 6 }}>
                  <span className="cu-kicker" style={{ flex: 'none' }}>Periodo</span>
                  <div style={{ marginLeft: 6 }}>
                    <SegmentedControl name="perDiario" options={[...VISTE]} value={vista} onChange={(v) => setVista(v as typeof vista)} />
                  </div>
                  <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                    <Icon name="search" size={14} />
                    Cerca nel diario
                  </button>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 30 }}>
                  {data.voci.map((voce, i) => (
                    <article key={voce.id} style={{ borderTop: i === 0 ? '2px solid var(--color-accent)' : '1px solid var(--color-divider)', paddingTop: 16 }}>
                      <div className="row" style={{ marginBottom: 10 }}>
                        <span className="cu-mono" style={{ fontSize: 13, fontWeight: 600 }}>{voce.dataLabel}</span>
                        {voce.stato === 'da_approvare' && <span style={{ marginLeft: 'auto' }}><Tag variant="accent">da approvare</Tag></span>}
                        {voce.stato === 'approvata' && (
                          <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>approvata alle {voce.approvataAlleLabel}</span>
                        )}
                        {voce.stato === 'assente' && (
                          <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>nessuna voce — non hai scritto a Custode</span>
                        )}
                      </div>
                      {voce.testo && <p style={{ fontSize: 16, lineHeight: 1.6, textWrap: 'pretty' }}>{voce.testo}</p>}
                      {voce.tag.length > 0 && (
                        <div className="row" style={{ gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
                          {voce.tag.map((t) => (
                            <Tag key={t} variant="outline">{t}</Tag>
                          ))}
                        </div>
                      )}
                      {voce.stato === 'da_approvare' && (
                        <div className="row" style={{ gap: 6, marginTop: 14 }}>
                          <button className="btn btn-primary" onClick={() => approva.mutate(voce.id)} disabled={approva.isPending}>
                            <Icon name="check" size={15} />
                            Approva
                          </button>
                          <button className="btn btn-secondary">
                            <Icon name="pencil" size={15} />
                            Modifica
                          </button>
                          <button className="btn btn-ghost" onClick={() => scarta.mutate(voce.id)} disabled={scarta.isPending}>
                            Scarta
                          </button>
                          {voce.fonteLabel && (
                            <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>{voce.fonteLabel}</span>
                          )}
                        </div>
                      )}
                    </article>
                  ))}
                </div>

                {data.altreVociVecchie > 0 && (
                  <div className="row">
                    <button className="btn btn-secondary">Carica il mese per intero</button>
                    <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.altreVociVecchie} voci più vecchie</span>
                  </div>
                )}
              </div>

              <div className="colR">
                {data.riepilogoSettimanale && (
                  <div>
                    <div className="row" style={{ marginBottom: 12 }}>
                      <h5>Riepilogo settimanale</h5>
                      <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.riepilogoSettimanale.label}</span>
                    </div>
                    <p style={{ fontSize: 14, lineHeight: 1.6, textWrap: 'pretty' }}>{data.riepilogoSettimanale.testo}</p>
                    <div className="row" style={{ gap: 6, marginTop: 12 }}>
                      <Tag variant="neutral">generato {data.riepilogoSettimanale.generatoLabel}</Tag>
                    </div>
                  </div>
                )}

                {data.riepilogoMensile && (
                  <div>
                    <h5 style={{ marginBottom: 12 }}>Riepilogo mensile</h5>
                    <p style={{ fontSize: 14, lineHeight: 1.6, textWrap: 'pretty' }}>{data.riepilogoMensile.testo}</p>
                    <button className="btn btn-ghost" style={{ marginTop: 8 }}>
                      Tutti i riepiloghi
                      <Icon name="arrow-right" size={14} />
                    </button>
                  </div>
                )}

                {data.temiDelMese.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 12 }}>Temi del mese</h5>
                    <div>
                      {data.temiDelMese.map((tema) => (
                        <div className="listrow" style={{ padding: '9px 0' }} key={tema.nome}>
                          <span style={{ fontSize: 14 }}>{tema.nome}</span>
                          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                            <Bar quota={tema.quota} />
                            <span className="cu-muted cu-mono" style={{ fontSize: 12, width: 22, textAlign: 'right' }}>{tema.occorrenze}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <h5 style={{ marginBottom: 12 }}>Copertura del mese</h5>
                  <DotGrid values={data.coperturaMese} />
                  <div className="cu-muted" style={{ fontSize: 12, marginTop: 10 }}>{data.coperturaNota}</div>
                </div>
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«aggiungi al diario di oggi: pomeriggio in biblioteca»" />
    </>
  );
}
