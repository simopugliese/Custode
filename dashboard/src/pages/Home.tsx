import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { TaskRow } from '../components/TaskRow';
import { ShoppingRow } from '../components/ShoppingRow';
import { HabitDotsRow } from '../components/HabitDotsRow';
import { Money } from '../components/Money';
import { Icon } from '../lib/icons';
import { ACCENT_RAMP } from '../lib/palette';
import { useHome, useToggleShoppingItem, useToggleTask } from '../hooks/useHome';

export default function Home() {
  const { data, isLoading, error, refetch } = useHome();
  const toggleTask = useToggleTask();
  const toggleShopping = useToggleShoppingItem();
  const navigate = useNavigate();

  return (
    <>
      <PageHeader kicker={`Custode${data ? ` · ${data.dataLabel}` : ''}`} title={data?.titolo ?? 'Custode'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {data.proposteAutomazioni !== undefined && data.proposteAutomazioni > 0 && (
              <AvvisoRow
                icon="zap"
                actionLabel="Vedi in Regole di contesto"
                actionIcon="arrow-right"
                onAction={() => navigate('/regole')}
              >
                Custode propone <b>{data.proposteAutomazioni} nuove automazioni</b> dedotte dalle tue abitudini — non
                partono senza il tuo sì.
              </AvvisoRow>
            )}

            <StatsBar
              items={[
                { label: 'Task aperti', value: data.stats.taskAperti },
                {
                  label: 'Spesa settimana',
                  // Assente = modulo spese non ancora attivo: un trattino dice
                  // "non lo so", uno zero direbbe "non hai speso niente".
                  value: data.stats.spesaSettimana === undefined ? '—' : <Money value={data.stats.spesaSettimana} />,
                },
                {
                  label: 'Streak più lunga',
                  value:
                    data.stats.streakPiuLunga === undefined ? (
                      '—'
                    ) : (
                      <>
                        {data.stats.streakPiuLunga}
                        <small style={{ opacity: 0.55 }}> giorni</small>
                      </>
                    ),
                  accent: true,
                },
                {
                  label: 'Lista spesa',
                  value: (
                    <>
                      {data.stats.listaSpesaDaPrendere}
                      <small> da prendere</small>
                    </>
                  ),
                },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div>
                  <div className="row" style={{ marginBottom: 4 }}>
                    <h5>Oggi</h5>
                    <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                      <Icon name="plus" size={14} />
                      Aggiungi
                    </button>
                  </div>
                  <div>
                    {data.taskOggi.map((task) => (
                      <TaskRow
                        key={task.id}
                        task={task}
                        onToggle={() => toggleTask.mutate({ id: task.id, fatto: !task.fatto })}
                        pending={toggleTask.isPending}
                      />
                    ))}
                    {data.taskOggi.length === 0 && <div className="cu-muted" style={{ fontSize: 13, padding: '10px 0' }}>Nessun task per oggi.</div>}
                  </div>
                </div>

                {data.calendarioOggi && (
                <div>
                  <h5 style={{ marginBottom: 4 }}>Calendario</h5>
                  <div>
                    {data.calendarioOggi.map((ev) => (
                      <div className="cal" key={ev.id}>
                        <span className="tm">{ev.ora}</span>
                        <span style={{ fontSize: 15 }}>{ev.titolo}</span>
                        {(ev.luogo || ev.meta) && (
                          <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
                            {ev.meta ?? ev.luogo}
                          </span>
                        )}
                      </div>
                    ))}
                    {data.calendarioOggi.length === 0 && <div className="cu-muted" style={{ fontSize: 13, padding: '10px 0' }}>Nessun evento oggi.</div>}
                  </div>
                </div>
                )}

                {data.abitudini && (
                <div>
                  <h5 style={{ marginBottom: 12 }}>Abitudini</h5>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                    {data.abitudini.map((habit) => (
                      <HabitDotsRow key={habit.id} habit={habit} />
                    ))}
                  </div>
                </div>
                )}
              </div>

              <div className="colR">
                {data.speseSettimana && (
                <div>
                  <div className="row" style={{ marginBottom: 12 }}>
                    <h5>Spese · settimana</h5>
                    <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>
                      <Money value={data.speseSettimana.speso} unit="" /> / {data.speseSettimana.budget} €
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 2, height: 14 }}>
                    {data.speseSettimana.categorie.map((cat, i) => (
                      <div key={cat.nome} style={{ flex: cat.importo, background: ACCENT_RAMP[i % ACCENT_RAMP.length] }} />
                    ))}
                    <div
                      style={{
                        flex: Math.max(data.speseSettimana.budget - data.speseSettimana.speso, 0),
                        background: 'color-mix(in srgb, var(--color-text) 9%, transparent)',
                      }}
                    />
                  </div>
                  <div style={{ marginTop: 14 }}>
                    {data.speseSettimana.categorie.map((cat, i) => (
                      <div className="listrow" style={{ padding: '8px 0' }} key={cat.nome}>
                        <div style={{ width: 9, height: 9, background: ACCENT_RAMP[i % ACCENT_RAMP.length] }} />
                        <span style={{ fontSize: 14 }}>{cat.nome}</span>
                        <span className="cu-mono" style={{ marginLeft: 'auto', fontSize: 14 }}>
                          {cat.importo.toFixed(2)}
                        </span>
                      </div>
                    ))}
                    <div className="listrow" style={{ padding: '8px 0' }}>
                      <div style={{ width: 9, height: 9, border: '1px solid var(--color-divider)' }} />
                      <span className="cu-muted" style={{ fontSize: 14 }}>
                        Resta di budget
                      </span>
                      <span className="cu-mono" style={{ marginLeft: 'auto', fontSize: 14 }}>
                        {Math.max(data.speseSettimana.budget - data.speseSettimana.speso, 0).toFixed(2)}
                      </span>
                    </div>
                  </div>
                  {data.speseSettimana.scontriniInAttesa > 0 && (
                    <div className="row" style={{ marginTop: 12 }}>
                      <span className="cu-muted" style={{ fontSize: 12 }}>
                        {data.speseSettimana.scontriniInAttesa} scontrino/i in attesa di conferma
                      </span>
                      <button className="btn btn-ghost" style={{ marginLeft: 'auto' }} onClick={() => navigate('/spese')}>
                        Rivedi
                        <Icon name="arrow-right" size={14} />
                      </button>
                    </div>
                  )}
                </div>
                )}

                <div>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <h5>Lista spesa</h5>
                    <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                      <Icon name="plus" size={14} />
                      Aggiungi
                    </button>
                  </div>
                  <div>
                    {data.listaSpesa.map((item) => (
                      <ShoppingRow
                        key={item.id}
                        item={item}
                        onToggle={() => toggleShopping.mutate({ id: item.id, preso: !item.preso })}
                        pending={toggleShopping.isPending}
                      />
                    ))}
                    {data.listaSpesa.length === 0 && <div className="cu-muted" style={{ fontSize: 13, padding: '10px 0' }}>Lista della spesa vuota.</div>}
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«segna 8€ colazione al bar», «ho fatto palestra e lettura»" />
    </>
  );
}
