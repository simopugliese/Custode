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
import { FormSpesa } from '../components/FormSpesa';
import { Icon } from '../lib/icons';
import {
  useCategorieSpesa,
  useConfermaScontrino,
  useEliminaSpesa,
  useModificaCategoria,
  useModificaSpesa,
  useRegistraSpesa,
  useSpese,
  useUnisciCategorie,
} from '../hooks/useSpese';
import type { Movimento } from '../types/api';

const PERIODI = [
  { value: 'settimana', label: 'Settimana' },
  { value: 'mese', label: 'Mese' },
  { value: 'anno', label: 'Anno' },
] as const;

export default function Spese() {
  const [periodo, setPeriodo] = useState<'settimana' | 'mese' | 'anno'>('mese');
  const { data, isLoading, error, refetch } = useSpese(periodo);
  const conferma = useConfermaScontrino();
  const registra = useRegistraSpesa();
  const modifica = useModificaSpesa();
  const elimina = useEliminaSpesa();
  const categorie = useCategorieSpesa();
  const modificaCategoria = useModificaCategoria();
  const unisci = useUnisciCategorie();

  const [formAperto, setFormAperto] = useState(false);
  const [inModifica, setInModifica] = useState<Movimento | null>(null);
  const [categoriaScontrino, setCategoriaScontrino] = useState('');
  const [daUnire, setDaUnire] = useState<string | null>(null);

  const nomiCategorie = (categorie.data ?? []).filter((c) => c.attiva).map((c) => c.nome);

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
                  <button
                    className="btn btn-ghost"
                    style={{ marginLeft: 'auto' }}
                    onClick={() => setFormAperto((aperto) => !aperto)}
                  >
                    <Icon name="plus" size={14} />
                    Registra spesa
                  </button>
                </div>

                {formAperto && (
                  <FormSpesa
                    categorie={nomiCategorie}
                    inCorso={registra.isPending}
                    onAnnulla={() => setFormAperto(false)}
                    onSalva={(corpo) =>
                      registra.mutate(corpo, { onSuccess: () => setFormAperto(false) })
                    }
                  />
                )}

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
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {data.movimenti.map((m) =>
                        inModifica?.id === m.id ? (
                          <tr key={m.id}>
                            <td colSpan={5} style={{ padding: '10px 0' }}>
                              <FormSpesa
                                spesa={m}
                                categorie={nomiCategorie}
                                inCorso={modifica.isPending}
                                onAnnulla={() => setInModifica(null)}
                                onSalva={(corpo) =>
                                  modifica.mutate(
                                    { id: m.id, ...corpo },
                                    { onSuccess: () => setInModifica(null) },
                                  )
                                }
                              />
                            </td>
                          </tr>
                        ) : (
                          <tr key={m.id}>
                            <td className="cu-mono">{m.dataLabel}</td>
                            <td>
                              {m.descrizione}
                              {m.luogo && m.luogo !== m.descrizione && (
                                <span className="cu-muted"> · {m.luogo}</span>
                              )}
                              {m.daScontrino && <span className="cu-muted"> · da scontrino</span>}
                            </td>
                            <td>
                              <Tag variant="neutral">{m.categoria}</Tag>
                            </td>
                            <td className="cu-mono" style={{ textAlign: 'right' }}>{m.importo.toFixed(2)}</td>
                            <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                              <button
                                className="btn btn-ghost"
                                style={{ fontSize: 12 }}
                                onClick={() => setInModifica(m)}
                                title="Correggi importo, data, descrizione o categoria"
                              >
                                Correggi
                              </button>
                              <button
                                className="btn btn-ghost"
                                style={{ fontSize: 12 }}
                                onClick={() => elimina.mutate(m.id)}
                                disabled={elimina.isPending}
                                title="Toglila dai conti"
                              >
                                Elimina
                              </button>
                            </td>
                          </tr>
                        ),
                      )}
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

                {(categorie.data ?? []).length > 0 && (
                  <div>
                    {/* «Fai ordine» e non «Categorie»: il blocco qui sopra si chiama
                        già così e dice quanto pesa ciascuna. Due titoli uguali nella
                        stessa colonna sono due cose che sembrano la stessa. */}
                    <div className="row" style={{ marginBottom: 10 }}>
                      <h5>Fai ordine</h5>
                      <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
                        rinomina, unisci i doppioni
                      </span>
                    </div>
                    <div>
                      {(categorie.data ?? []).map((c) => (
                        <div
                          className="listrow"
                          style={{ padding: '10px 0', gap: 6, alignItems: 'center' }}
                          key={c.id}
                        >
                          <input
                            defaultValue={c.nome}
                            onBlur={(e) => {
                              const nome = e.target.value.trim();
                              if (nome && nome !== c.nome) modificaCategoria.mutate({ id: c.id, nome });
                            }}
                            className={c.attiva ? undefined : 'cu-muted'}
                            style={{
                              flex: 1,
                              minWidth: 0,
                              fontSize: 14,
                              padding: '4px 6px',
                              background: 'none',
                              border: '1px solid transparent',
                            }}
                            aria-label={`Nome della categoria ${c.nome}`}
                          />
                          <span className="cu-mono cu-muted" style={{ fontSize: 12 }}>
                            {c.spese}
                          </span>
                          {daUnire === c.id ? (
                            <select
                              autoFocus
                              defaultValue=""
                              onChange={(e) => {
                                if (e.target.value) {
                                  unisci.mutate(
                                    { id: c.id, inId: e.target.value },
                                    { onSuccess: () => setDaUnire(null) },
                                  );
                                }
                              }}
                              style={{ fontSize: 12, padding: '3px 4px' }}
                            >
                              <option value="">unisci in…</option>
                              {(categorie.data ?? [])
                                .filter((altra) => altra.id !== c.id && altra.attiva)
                                .map((altra) => (
                                  <option key={altra.id} value={altra.id}>
                                    {altra.nome}
                                  </option>
                                ))}
                            </select>
                          ) : (
                            c.attiva && (
                              <button
                                className="btn btn-ghost"
                                style={{ fontSize: 12 }}
                                onClick={() => setDaUnire(c.id)}
                                title="Sposta le sue spese su un'altra categoria"
                              >
                                Unisci
                              </button>
                            )
                          )}
                        </div>
                      ))}
                    </div>
                    <div className="cu-muted" style={{ fontSize: 12, marginTop: 8 }}>
                      Il numero sono le spese attaccate. Unire sposta quelle spese e spegne la
                      categoria, senza cancellarla.
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
                        <input
                          list="categorie-in-uso"
                          value={categoriaScontrino}
                          onChange={(e) => setCategoriaScontrino(e.target.value)}
                          placeholder={data.scontrinoInAttesa.categoriaProposta}
                          style={{ flex: 1, padding: '6px 8px', fontSize: 13 }}
                          aria-label="Categoria dello scontrino"
                        />
                        <button
                          className="btn btn-primary"
                          onClick={() =>
                            conferma.mutate(
                              {
                                id: data.scontrinoInAttesa!.id,
                                categoria: categoriaScontrino.trim() || undefined,
                              },
                              { onSuccess: () => setCategoriaScontrino('') },
                            )
                          }
                          disabled={conferma.isPending}
                        >
                          Conferma
                        </button>
                      </div>
                      <div className="cu-muted" style={{ fontSize: 12 }}>
                        Lascia il campo vuoto per tenere la categoria proposta.
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
