import { Fragment, useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { Tag } from '../components/Tag';
import { Bar } from '../components/Bar';
import { DotGrid } from '../components/DotGrid';
import { TaskRow } from '../components/TaskRow';
import { Icon } from '../lib/icons';
import { useToggleTask } from '../hooks/useHome';
import { useLezioni, useMandaPianoAlBot, useRigeneraPiano } from '../hooks/useLezioni';

const VISTE = [
  { value: 'settimana', label: 'Settimana' },
  { value: 'mese', label: 'Mese' },
] as const;

export default function Lezioni() {
  const [vista, setVista] = useState<'settimana' | 'mese'>('settimana');
  const { data, isLoading, error, refetch } = useLezioni(vista);
  const toggleTask = useToggleTask();
  const rigenera = useRigeneraPiano();
  const mandaAlBot = useMandaPianoAlBot();

  return (
    <>
      <PageHeader kicker={`Lezioni e corsi${data ? ` · ${data.periodoLabel}` : ''}`} title={data?.titolo ?? 'Lezioni e corsi'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            <AvvisoRow icon="clipboard-check" actionLabel="Fallo adesso" actionIcon="arrow-right">
              Il <b>check-in serale</b> di oggi arriva alle {data.checkInOra} — ti chiederà cosa hai capito delle lezioni di oggi.
            </AvvisoRow>

            <StatsBar
              items={[
                { label: 'Corsi attivi', value: data.stats.corsiAttivi },
                { label: 'Lezioni questa settimana', value: <>{data.stats.lezioniSettimana.fatte}<small> / {data.stats.lezioniSettimana.totali}</small></> },
                { label: 'Check-in fatti', value: <>{data.stats.checkInDiFila}<small style={{ opacity: 0.55 }}> di fila</small></>, accent: true },
                { label: 'Argomenti da ripassare', value: data.stats.argomentiDaRipassare },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <h5>Settimana di lezioni</h5>
                    <div style={{ marginLeft: 12 }}>
                      <SegmentedControl name="perLez" options={[...VISTE]} value={vista} onChange={(v) => setVista(v as typeof vista)} />
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '64px 1fr' }}>
                    {data.settimana.map((day, i) => {
                      const borderTop = day.isOggi ? '2px solid var(--color-accent)' : i === 0 ? 'none' : '1px solid var(--color-rule)';
                      return (
                        <Fragment key={day.giorno}>
                          <div className="cu-kicker" style={{ padding: '14px 0', borderTop, color: day.isOggi ? 'var(--color-accent)' : undefined }}>
                            {day.giorno}
                          </div>
                          <div style={{ padding: '10px 0', borderLeft: '1px solid var(--color-rule)', borderTop, paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {day.lezioni.map((les, j) => (
                              <div className="row" style={{ gap: 12 }} key={j}>
                                <span className="tm">{les.ora}</span>
                                <span style={{ fontSize: 14, fontWeight: les.evidenziata ? 600 : undefined }}>{les.nome}</span>
                                {les.luogo && <span className="cu-muted" style={{ fontSize: 12 }}>{les.luogo}</span>}
                                {les.stato && (
                                  <span style={{ marginLeft: 'auto' }}>
                                    <Tag variant={les.statoVariant ?? 'neutral'}>{les.stato}</Tag>
                                  </span>
                                )}
                              </div>
                            ))}
                            {day.lezioni.length === 0 && day.notaVuoto && (
                              <span className="cu-muted" style={{ fontSize: 13 }}>{day.notaVuoto}</span>
                            )}
                          </div>
                        </Fragment>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <h5>Piani di ripasso generati</h5>
                    <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>dai tuoi check-in</span>
                  </div>
                  {data.pianiRipasso.map((piano, i) => (
                    <div
                      key={piano.id}
                      style={{
                        borderTop: i === 0 ? '2px solid var(--color-accent)' : '1px solid var(--color-divider)',
                        paddingTop: 14,
                        marginTop: i === 0 ? 0 : 20,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 10,
                      }}
                    >
                      <div className="row">
                        <span style={{ fontSize: 15, fontWeight: 600 }}>
                          {piano.corso} — {piano.argomento}
                        </span>
                        {piano.priorita && (
                          <span style={{ marginLeft: 'auto' }}>
                            <Tag variant="accent">priorità</Tag>
                          </span>
                        )}
                      </div>
                      <p className="cu-muted" style={{ fontSize: 13, lineHeight: 1.55, textWrap: 'pretty' }}>{piano.motivazione}</p>
                      {piano.task.length > 0 && (
                        <div>
                          {piano.task.map((task) => (
                            <TaskRow
                              key={task.id}
                              task={task}
                              onToggle={() => toggleTask.mutate({ id: task.id, fatto: !task.fatto })}
                              pending={toggleTask.isPending}
                              padding="9px 0"
                            />
                          ))}
                        </div>
                      )}
                      <div className="row" style={{ gap: 6 }}>
                        <button className="btn btn-secondary" onClick={() => mandaAlBot.mutate(piano.id)} disabled={mandaAlBot.isPending}>
                          Manda i task al bot
                        </button>
                        <button className="btn btn-ghost" onClick={() => rigenera.mutate(piano.id)} disabled={rigenera.isPending}>
                          Rigenera il piano
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="colR">
                <div>
                  <div className="row" style={{ marginBottom: 12 }}>
                    <h5>Corsi</h5>
                    <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                      <Icon name="plus" size={14} />
                      Aggiungi
                    </button>
                  </div>
                  <div>
                    {data.corsi.map((corso, i) => (
                      <div key={corso.id} style={{ padding: '12px 0', borderBottom: i === data.corsi.length - 1 ? 'none' : '1px solid var(--color-rule)' }}>
                        <div className="row">
                          <span style={{ fontSize: 14, fontWeight: 600 }}>{corso.nome}</span>
                          <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>
                            {corso.capitoliFatti} / {corso.capitoliTotali} capitoli
                          </span>
                        </div>
                        <div style={{ marginTop: 8 }}>
                          <Bar quota={corso.capitoliTotali ? corso.capitoliFatti / corso.capitoliTotali : 0} width="100%" />
                        </div>
                        <div className="cu-muted" style={{ fontSize: 12, marginTop: 6 }}>
                          {corso.esameLabel}
                          {corso.argomentiArretrato ? ` · ${corso.argomentiArretrato} argomenti in arretrato` : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="row" style={{ marginBottom: 12 }}>
                    <h5>Check-in serali</h5>
                    <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>ultimi {data.checkInRecenti.length} giorni</span>
                  </div>
                  <DotGrid values={data.checkInRecenti} />
                  <div className="cu-muted" style={{ fontSize: 12, marginTop: 10 }}>{data.checkInNota}</div>
                  {data.ultimoCheckIn && (
                    <div style={{ marginTop: 14, borderTop: '1px solid var(--color-divider)', paddingTop: 12 }}>
                      <div className="cu-kicker" style={{ marginBottom: 8 }}>Ultimo check-in · {data.ultimoCheckIn.label}</div>
                      {data.ultimoCheckIn.righe.map((r) => (
                        <div className="listrow" style={{ padding: '8px 0' }} key={r.corso}>
                          <span style={{ fontSize: 14 }}>{r.corso}</span>
                          <span style={{ marginLeft: 'auto' }}>
                            <Tag variant={r.esito === 'chiaro' ? 'accent' : 'outline'}>{r.esito === 'chiaro' ? 'chiaro' : 'da rivedere'}</Tag>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  <h5 style={{ marginBottom: 10 }}>Argomenti da ripassare</h5>
                  <div>
                    {data.argomentiDaRipassare.map((a) => (
                      <div className="listrow" style={{ padding: '9px 0' }} key={a.argomento}>
                        <span style={{ fontSize: 14 }}>{a.argomento}</span>
                        <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>{a.corso}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«oggi Analisi II l'ho capita bene», «sposta il ripasso a domenica»" />
    </>
  );
}
