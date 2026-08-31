import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { TaskRow } from '../components/TaskRow';
import { Icon } from '../lib/icons';
import { useToggleTask } from '../hooks/useHome';
import { useRinviaTask, useTaskPage } from '../hooks/useTask';
import type { TaskItem } from '../types/api';

const VISTE = [
  { value: 'scadenza', label: 'Per scadenza' },
  { value: 'progetto', label: 'Per progetto' },
  { value: 'completati', label: 'Completati' },
] as const;

const GIORNI_INIZIALI = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];

export default function Task() {
  const [vista, setVista] = useState<'scadenza' | 'progetto' | 'completati'>('scadenza');
  const { data, isLoading, error, refetch } = useTaskPage(vista);
  const toggleTask = useToggleTask();
  const rinvia = useRinviaTask();

  function renderTasks(tasks: TaskItem[]) {
    return tasks.map((task) => (
      <TaskRow
        key={task.id}
        task={task}
        onToggle={() => toggleTask.mutate({ id: task.id, fatto: !task.fatto })}
        pending={toggleTask.isPending}
        onPostpone={() => rinvia.mutate({ id: task.id })}
        postponePending={rinvia.isPending}
      />
    ));
  }

  const maxChiuso = data ? Math.max(...data.chiusiPerGiorno, 1) : 1;

  return (
    <>
      <PageHeader kicker={`Task${data ? ` · ${data.dataLabel}` : ''}`} title={data?.titolo ?? 'Task'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {data.avviso && (
              <AvvisoRow icon="rotate-ccw" actionLabel="Decidi" actionIcon="arrow-right">
                {data.avviso}
              </AvvisoRow>
            )}

            <StatsBar
              items={[
                { label: 'Aperti', value: data.stats.aperti },
                { label: 'Oggi', value: data.stats.oggi, accent: true },
                { label: 'In ritardo', value: data.stats.inRitardo },
                { label: 'Chiusi questa settimana', value: data.stats.chiusiSettimana },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div className="row" style={{ gap: 6 }}>
                  <span className="cu-kicker" style={{ flex: 'none' }}>Vista</span>
                  <div style={{ marginLeft: 6 }}>
                    <SegmentedControl name="vTask" options={[...VISTE]} value={vista} onChange={(v) => setVista(v as typeof vista)} />
                  </div>
                  <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                    <Icon name="plus" size={14} />
                    Nuovo task
                  </button>
                </div>

                {data.inRitardo.length > 0 && (
                  <div>
                    <div className="row" style={{ marginBottom: 4 }}>
                      <h5>In ritardo</h5>
                      <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.inRitardo.length}</span>
                    </div>
                    <div>{renderTasks(data.inRitardo)}</div>
                  </div>
                )}

                <div>
                  <div className="row" style={{ marginBottom: 4 }}>
                    <h5>Oggi</h5>
                    <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.oggi.length}</span>
                  </div>
                  <div>{renderTasks(data.oggi)}</div>
                  {data.oggi.length === 0 && <div className="cu-muted" style={{ fontSize: 13, padding: '10px 0' }}>Niente per oggi.</div>}
                </div>

                {data.prossimiSetteGiorni.length > 0 && (
                  <div>
                    <div className="row" style={{ marginBottom: 4 }}>
                      <h5>Prossimi sette giorni</h5>
                    </div>
                    <div>{renderTasks(data.prossimiSetteGiorni)}</div>
                  </div>
                )}

                {data.senzaScadenza.length > 0 && (
                  <div>
                    <div className="row" style={{ marginBottom: 4 }}>
                      <h5>Senza scadenza</h5>
                      <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.senzaScadenza.length}</span>
                    </div>
                    <div>{renderTasks(data.senzaScadenza)}</div>
                  </div>
                )}
              </div>

              <div className="colR">
                <div>
                  <h5 style={{ marginBottom: 12 }}>Chiusi questa settimana</h5>
                  <div style={{ display: 'flex', gap: 5, alignItems: 'flex-end', height: 70 }}>
                    {data.chiusiPerGiorno.map((val, i) => (
                      <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                        <div style={{ width: '100%', height: Math.max(Math.round((val / maxChiuso) * 70), 2), background: 'var(--color-accent-300)' }} />
                        <span className="cu-kicker">{GIORNI_INIZIALI[i] ?? ''}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {data.ricorrenti.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Ricorrenti</h5>
                    <div>
                      {data.ricorrenti.map((r) => (
                        <div className="listrow" style={{ padding: '9px 0' }} key={r.nome}>
                          <span style={{ fontSize: 14 }}>{r.nome}</span>
                          <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{r.frequenzaLabel}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {data.provenienza.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Da dove arrivano</h5>
                    <div>
                      {data.provenienza.map((p) => (
                        <div className="listrow" style={{ padding: '9px 0' }} key={p.origine}>
                          <span style={{ fontSize: 14 }}>{p.origine}</span>
                          <span className="cu-mono" style={{ marginLeft: 'auto', fontSize: 14 }}>{p.conteggio}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«ricordami di chiamare l'officina giovedì mattina»" />
    </>
  );
}
