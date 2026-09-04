import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { DotRow, DotGrid } from '../components/DotGrid';
import { Checkbox } from '../components/Checkbox';
import { Icon } from '../lib/icons';
import {
  useAbitudiniPage,
  useCreaAbitudine,
  useLogAbitudine,
  useModificaAbitudine,
  useRispondiPropostaAbitudine,
} from '../hooks/useAbitudini';
import type { AbitudineDettaglio } from '../types/api';

const VISTE = [
  { value: 'settimana', label: 'Settimana' },
  { value: 'mese', label: 'Mese' },
] as const;

// Da 1 a 7: il target è settimanale (§7), e 7 vuol dire tutti i giorni.
const TARGET = [1, 2, 3, 4, 5, 6, 7];

/** Il target attuale, letto dall'etichetta che il backend ha già composto.
 *  Le etichette italiane le produce il backend (`core/formato.py`): qui si
 *  ricava solo il numero da preselezionare nella tendina. */
function targetDi(h: AbitudineDettaglio): number {
  if (h.frequenzaLabel.startsWith('tutti')) return 7;
  return Number(h.frequenzaLabel.match(/\d+/)?.[0] ?? 3);
}

function oggiISO() {
  return new Date().toISOString().slice(0, 10);
}

export default function Abitudini() {
  const [vista, setVista] = useState<'settimana' | 'mese'>('settimana');
  const { data, isLoading, error, refetch } = useAbitudiniPage(vista);
  const log = useLogAbitudine();
  const proposta = useRispondiPropostaAbitudine();
  const crea = useCreaAbitudine();
  const modifica = useModificaAbitudine();
  const [formAperto, setFormAperto] = useState(false);
  const [nuovoNome, setNuovoNome] = useState('');
  const [nuovoTarget, setNuovoTarget] = useState(3);
  const [inModifica, setInModifica] = useState<string | null>(null);

  function aggiungi(e: React.FormEvent) {
    e.preventDefault();
    if (!nuovoNome.trim()) return;
    crea.mutate(
      { nome: nuovoNome.trim(), targetSettimanale: nuovoTarget },
      {
        onSuccess: () => {
          setNuovoNome('');
          setNuovoTarget(3);
          setFormAperto(false);
        },
      },
    );
  }

  return (
    <>
      <PageHeader kicker={`Abitudini${data ? ` · ${data.periodoLabel}` : ''}`} title={data?.titolo ?? 'Abitudini'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {data.avviso && <AvvisoRow icon="calendar-clock" actionLabel="Mettilo in agenda" actionIcon="arrow-right">{data.avviso}</AvvisoRow>}

            <StatsBar
              items={[
                { label: 'Abitudini attive', value: data.stats.attive },
                {
                  label: 'Obiettivi centrati',
                  value: (
                    <>
                      {data.stats.obiettiviCentrati.fatti}
                      <small style={{ opacity: 0.55 }}> / {data.stats.obiettiviCentrati.totali}</small>
                    </>
                  ),
                  accent: true,
                },
                { label: 'Streak migliore', value: <>{data.stats.streakMigliore}<small> giorni</small></> },
                { label: 'Costanza del mese', value: <>{data.stats.costanzaMese}<small> %</small></> },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div className="row" style={{ gap: 6 }}>
                  <span className="cu-kicker" style={{ flex: 'none' }}>Vista</span>
                  <div style={{ marginLeft: 6 }}>
                    <SegmentedControl name="vAb" options={[...VISTE]} value={vista} onChange={(v) => setVista(v as typeof vista)} />
                  </div>
                  <button
                    className="btn btn-ghost"
                    style={{ marginLeft: 'auto' }}
                    onClick={() => setFormAperto((aperto) => !aperto)}
                  >
                    <Icon name="plus" size={14} />
                    Nuova abitudine
                  </button>
                </div>

                {formAperto && (
                  <form onSubmit={aggiungi} className="row" style={{ gap: 8, alignItems: 'flex-end' }}>
                    <label style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <span className="cu-kicker">Nome</span>
                      <input
                        autoFocus
                        value={nuovoNome}
                        onChange={(e) => setNuovoNome(e.target.value)}
                        placeholder="Palestra"
                        style={{ padding: '8px 10px', fontSize: 14 }}
                      />
                    </label>
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <span className="cu-kicker">Volte a settimana</span>
                      <select
                        value={nuovoTarget}
                        onChange={(e) => setNuovoTarget(Number(e.target.value))}
                        style={{ padding: '8px 10px', fontSize: 14 }}
                      >
                        {TARGET.map((n) => (
                          <option key={n} value={n}>
                            {n === 7 ? 'tutti i giorni' : n}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="btn btn-secondary" type="submit" disabled={crea.isPending}>
                      Aggiungi
                    </button>
                  </form>
                )}

                <div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', alignItems: 'center', gap: '0 22px', borderBottom: '2px solid var(--color-divider)', paddingBottom: 8 }}>
                    <span className="cu-kicker">Abitudine</span>
                    <span className="cu-kicker">Lun – Dom</span>
                    <span className="cu-kicker" style={{ textAlign: 'right' }}>Obiettivo</span>
                  </div>
                  {data.abitudini.map((h, i) => (
                    <div
                      key={h.id}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr auto auto',
                        alignItems: 'center',
                        gap: '0 22px',
                        padding: '16px 0',
                        borderBottom: i === data.abitudini.length - 1 ? 'none' : '1px solid var(--color-rule)',
                      }}
                    >
                      <div>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>{h.nome}</div>
                        {inModifica === h.id ? (
                          <div className="row" style={{ gap: 6, marginTop: 4 }}>
                            <select
                              autoFocus
                              defaultValue={targetDi(h)}
                              onChange={(e) =>
                                modifica.mutate(
                                  { id: h.id, targetSettimanale: Number(e.target.value) },
                                  { onSuccess: () => setInModifica(null) },
                                )
                              }
                              style={{ padding: '4px 6px', fontSize: 12 }}
                            >
                              {TARGET.map((n) => (
                                <option key={n} value={n}>
                                  {n === 7 ? 'tutti i giorni' : `${n} a settimana`}
                                </option>
                              ))}
                            </select>
                            <button
                              className="btn btn-ghost"
                              style={{ fontSize: 12 }}
                              onClick={() =>
                                modifica.mutate(
                                  { id: h.id, attiva: false },
                                  { onSuccess: () => setInModifica(null) },
                                )
                              }
                            >
                              Non la seguo più
                            </button>
                          </div>
                        ) : (
                          <button
                            className="cu-muted"
                            onClick={() => setInModifica(h.id)}
                            style={{
                              fontSize: 12,
                              background: 'none',
                              border: 'none',
                              padding: 0,
                              cursor: 'pointer',
                              textAlign: 'left',
                            }}
                            title="Cambia obiettivo o smetti di seguirla"
                          >
                            {h.frequenzaLabel}
                          </button>
                        )}
                      </div>
                      <DotRow values={h.giorni} />
                      <span
                        className="cu-mono"
                        style={{ fontSize: 15, textAlign: 'right', width: 44, color: h.evidenziata ? 'var(--color-accent-700)' : undefined, fontWeight: h.evidenziata ? 600 : undefined }}
                      >
                        {h.goalRatioLabel}
                      </span>
                    </div>
                  ))}
                </div>

                <div>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <h5>Segna per oggi</h5>
                    <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>di solito lo fai dal bot, ma da qui funziona uguale</span>
                  </div>
                  <div>
                    {data.abitudini.map((h) => (
                      <div className="listrow" style={{ padding: '11px 0' }} key={h.id}>
                        <Checkbox
                          checked={h.segnataOggi}
                          onChange={() => log.mutate({ id: h.id, data: oggiISO(), fatto: !h.segnataOggi })}
                          disabled={log.isPending}
                        />
                        <span style={{ fontSize: 15 }}>{h.nome}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="colR">
                <div>
                  <div className="row" style={{ marginBottom: 12 }}>
                    <h5>{data.meseSingolaAbitudine.nome}</h5>
                  </div>
                  <DotGrid values={data.meseSingolaAbitudine.giorni} />
                  <div className="cu-muted" style={{ fontSize: 12, marginTop: 10 }}>{data.meseSingolaAbitudine.nota}</div>
                </div>

                <div>
                  <h5 style={{ marginBottom: 10 }}>Streak</h5>
                  <div>
                    {data.streak.map((s, i) => (
                      <div className="listrow" style={{ padding: '10px 0' }} key={i}>
                        <span className={s.mutedRow ? 'cu-muted' : undefined} style={{ fontSize: 14 }}>{s.nome}</span>
                        <span
                          className={`cu-mono${s.mutedValue || s.mutedRow ? ' cu-muted' : ''}`}
                          style={{ marginLeft: 'auto', fontSize: 14, color: s.evidenziata ? 'var(--color-accent-700)' : undefined, fontWeight: s.evidenziata ? 600 : undefined }}
                        >
                          {s.valoreLabel}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {data.report && (
                  <div>
                    <div className="row" style={{ marginBottom: 10 }}>
                      <h5>Il racconto</h5>
                      <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
                        {data.report.periodoLabel}
                      </span>
                    </div>
                    <div
                      style={{
                        borderTop: '1px solid var(--color-divider)',
                        paddingTop: 12,
                        fontSize: 14,
                        lineHeight: 1.6,
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {data.report.testo}
                    </div>
                  </div>
                )}

                {data.proposta && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Custode propone</h5>
                    <div style={{ borderTop: '1px solid var(--color-divider)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.4 }}>{data.proposta.titolo}</div>
                      <div className="cu-muted" style={{ fontSize: 12 }}>{data.proposta.motivazione}</div>
                      <div className="row" style={{ gap: 6 }}>
                        <button
                          className="btn btn-secondary"
                          onClick={() => proposta.mutate({ id: data.proposta!.id, accetta: true })}
                          disabled={proposta.isPending}
                        >
                          Accetta
                        </button>
                        <button
                          className="btn btn-ghost"
                          onClick={() => proposta.mutate({ id: data.proposta!.id, accetta: false })}
                          disabled={proposta.isPending}
                        >
                          No, lascia com'è
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«ho fatto palestra», «segna lettura per ieri»" />
    </>
  );
}
