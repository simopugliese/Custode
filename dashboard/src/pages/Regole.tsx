import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { Tag } from '../components/Tag';
import { Icon } from '../lib/icons';
import { useApprovaRegola, useImpostaStatoRegola, useRegole, useScartaRegola } from '../hooks/useRegole';

const STATO_OPTIONS = [
  { value: 'attiva', label: 'Attiva' },
  { value: 'pausa', label: 'Pausa' },
] as const;

export default function Regole() {
  const { data, isLoading, error, refetch } = useRegole();
  const approva = useApprovaRegola();
  const scarta = useScartaRegola();
  const impostaStato = useImpostaStatoRegola();

  return (
    <>
      <PageHeader kicker="Regole di contesto" title={data?.titolo ?? 'Regole di contesto'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            <AvvisoRow icon="info">{data.spiegazione}</AvvisoRow>

            <StatsBar
              items={[
                { label: 'Attive', value: data.stats.attive },
                { label: 'Da approvare', value: data.stats.daApprovare },
                { label: 'Scattate questa settimana', value: data.stats.scattateSettimana, accent: true },
                { label: 'In pausa', value: data.stats.inPausa },
              ]}
            />

            <div className="cols">
              <div className="colL">
                {data.proposte.length > 0 && (
                  <div>
                    <div className="row" style={{ marginBottom: 10 }}>
                      <h5>Proposte</h5>
                      <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>generate stanotte dall'analisi dei tuoi dati</span>
                    </div>
                    {data.proposte.map((p, i) => (
                      <div
                        key={p.id}
                        style={{ borderTop: '2px solid var(--color-accent)', paddingTop: 14, marginTop: i === 0 ? 0 : 22, display: 'flex', flexDirection: 'column', gap: 10 }}
                      >
                        <div className="row" style={{ gap: 10 }}>
                          <Tag variant="outline" mono>{p.triggerTipo}</Tag>
                          <span className="cu-muted" style={{ fontSize: 11 }}>confidenza {p.confidenza}</span>
                        </div>
                        <div style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.4 }}>{p.testo}</div>
                        <div className="cu-muted" style={{ fontSize: 13, lineHeight: 1.55 }}>{p.motivazione}</div>
                        <div className="row" style={{ gap: 6 }}>
                          <button className="btn btn-primary" onClick={() => approva.mutate(p.id)} disabled={approva.isPending}>
                            <Icon name="check" size={15} />
                            Approva
                          </button>
                          <button className="btn btn-secondary">Modifica i parametri</button>
                          <button className="btn btn-ghost" onClick={() => scarta.mutate(p.id)} disabled={scarta.isPending}>
                            Scarta
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <div>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <h5>Regole attive</h5>
                    <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                      <Icon name="plus" size={14} />
                      Scrivine una
                    </button>
                  </div>
                  <div>
                    {data.regoleAttive.map((r, i) => (
                      <div
                        key={r.id}
                        style={{ padding: '15px 0', borderBottom: i === data.regoleAttive.length - 1 ? 'none' : '1px solid var(--color-rule)', opacity: r.attenuata ? 0.55 : 1 }}
                      >
                        <div className="row">
                          <Tag variant="neutral" mono>{r.triggerTipo}</Tag>
                          <span style={{ fontSize: 15, fontWeight: 600, marginLeft: 10 }}>{r.nome}</span>
                          <div style={{ marginLeft: 'auto' }}>
                            <SegmentedControl
                              name={`r-${r.id}`}
                              options={[...STATO_OPTIONS]}
                              value={r.stato}
                              onChange={(v) => impostaStato.mutate({ id: r.id, stato: v as 'attiva' | 'pausa' })}
                            />
                          </div>
                        </div>
                        <div className="cu-muted" style={{ fontSize: 13, marginTop: 8 }}>{r.descrizione}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="colR">
                {data.attivitaSettimana.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 12 }}>Attività della settimana</h5>
                    <div>
                      {data.attivitaSettimana.map((a) => (
                        <div className="listrow" style={{ padding: '10px 0' }} key={a.nome}>
                          <span style={{ fontSize: 14 }}>{a.nome}</span>
                          <span className="cu-mono" style={{ marginLeft: 'auto', fontSize: 14 }}>{a.conteggio}</span>
                        </div>
                      ))}
                    </div>
                    {data.attivitaNota && <div className="cu-muted" style={{ fontSize: 12, marginTop: 10 }}>{data.attivitaNota}</div>}
                  </div>
                )}

                {data.tipiTrigger.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Tipi di trigger</h5>
                    <div>
                      {data.tipiTrigger.map((t) => (
                        <div className="listrow" style={{ padding: '9px 0' }} key={t.tipo}>
                          <span className="cu-mono" style={{ fontSize: 13 }}>{t.tipo}</span>
                          <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>{t.descrizione}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {data.scartate.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Scartate</h5>
                    <div>
                      {data.scartate.map((s, i) => (
                        <div className="listrow" style={{ padding: '10px 0' }} key={i}>
                          <span style={{ fontSize: 14 }}>{s.nome}</span>
                          <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{s.dataLabel}</span>
                        </div>
                      ))}
                    </div>
                    <div className="cu-muted" style={{ fontSize: 12, marginTop: 10 }}>Custode non ripropone una regola scartata due volte.</div>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«ogni domenica sera chiedimi cosa voglio fare la settimana prossima»" />
    </>
  );
}
