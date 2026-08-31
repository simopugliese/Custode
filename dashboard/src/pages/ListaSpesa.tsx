import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { ShoppingRow } from '../components/ShoppingRow';
import { Bar } from '../components/Bar';
import { Money } from '../components/Money';
import { Icon } from '../lib/icons';
import { useToggleShoppingItem } from '../hooks/useHome';
import { useAggiungiVoceSpesa, useListaSpesaPage, useSvuotaPresi } from '../hooks/useListaSpesa';

const VISTE = [
  { value: 'reparto', label: 'Reparto' },
  { value: 'aggiunta', label: 'Aggiunta' },
] as const;

export default function ListaSpesa() {
  const [ordina, setOrdina] = useState<'reparto' | 'aggiunta'>('reparto');
  const { data, isLoading, error, refetch } = useListaSpesaPage(ordina);
  const toggle = useToggleShoppingItem();
  const svuota = useSvuotaPresi();
  const aggiungi = useAggiungiVoceSpesa();

  return (
    <>
      <PageHeader kicker={`Lista spesa${data ? ` · aggiornata alle ${data.aggiornataAlleLabel}` : ''}`} title={data?.titolo ?? 'Lista spesa'} />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {data.suggerimento && (
              <AvvisoRow
                icon="lightbulb"
                actionLabel="Aggiungi entrambi"
                actionIcon="plus"
                onAction={() => data.suggerimento!.voci.forEach((nome) => aggiungi.mutate(nome))}
              >
                {data.suggerimento.testo}
              </AvvisoRow>
            )}

            <StatsBar
              items={[
                { label: 'Da prendere', value: data.stats.daPrendere },
                { label: 'Presi', value: data.stats.presi, accent: true },
                { label: 'Stima carrello', value: <Money value={data.stats.stimaCarrello} /> },
                { label: 'Ultima spesa', value: <span style={{ fontSize: 34, paddingTop: 8, display: 'block' }}>{data.stats.ultimaSpesaGiorni} giorni</span> },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div className="row" style={{ gap: 6 }}>
                  <span className="cu-kicker" style={{ flex: 'none' }}>Ordina per</span>
                  <div style={{ marginLeft: 6 }}>
                    <SegmentedControl name="vSpesa" options={[...VISTE]} value={ordina} onChange={(v) => setOrdina(v as typeof ordina)} />
                  </div>
                  <button className="btn btn-ghost" style={{ marginLeft: 'auto' }}>
                    <Icon name="plus" size={14} />
                    Aggiungi voce
                  </button>
                </div>

                {data.reparti.map((reparto) => (
                  <div key={reparto.nome}>
                    <div className="row" style={{ marginBottom: 4 }}>
                      <h5>{reparto.nome}</h5>
                    </div>
                    <div>
                      {reparto.voci.map((item) => (
                        <ShoppingRow key={item.id} item={item} onToggle={() => toggle.mutate({ id: item.id, preso: !item.preso })} pending={toggle.isPending} padding="11px 0" />
                      ))}
                    </div>
                  </div>
                ))}

                <div>
                  <div className="row" style={{ marginBottom: 4 }}>
                    <h5>Presi</h5>
                    <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.presi.length}</span>
                  </div>
                  <div style={{ opacity: 0.45 }}>
                    {data.presi.map((item) => (
                      <ShoppingRow key={item.id} item={item} onToggle={() => toggle.mutate({ id: item.id, preso: !item.preso })} pending={toggle.isPending} padding="10px 0" />
                    ))}
                  </div>
                  {data.presi.length > 0 && (
                    <div className="row" style={{ marginTop: 12 }}>
                      <button className="btn btn-secondary" onClick={() => svuota.mutate()} disabled={svuota.isPending}>
                        Svuota i presi
                      </button>
                      <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>Custode li archivia da sé dopo la spesa</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="colR">
                {data.suggeriti.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 12 }}>Suggeriti da Custode</h5>
                    <p className="cu-muted" style={{ fontSize: 13, lineHeight: 1.55, marginBottom: 12, textWrap: 'pretty' }}>
                      Cose che ricompri a intervalli regolari e che ora dovrebbero essere finite.
                    </p>
                    <div>
                      {data.suggeriti.map((s) => (
                        <div className="listrow" style={{ padding: '10px 0' }} key={s.nome}>
                          <span style={{ fontSize: 14 }}>{s.nome}</span>
                          <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{s.frequenzaLabel}</span>
                          <button className="btn btn-ghost" style={{ marginLeft: 10 }} onClick={() => aggiungi.mutate(s.nome)} disabled={aggiungi.isPending}>
                            <Icon name="plus" size={14} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {data.ultimeSpese.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Ultime spese fatte</h5>
                    <div>
                      {data.ultimeSpese.map((s, i) => (
                        <div className="listrow" style={{ padding: '10px 0' }} key={i}>
                          <span className="cu-mono" style={{ fontSize: 13 }}>{s.dataLabel}</span>
                          <span className="cu-muted" style={{ fontSize: 13 }}>{s.luogo}</span>
                          <span className="cu-mono" style={{ marginLeft: 'auto', fontSize: 14 }}>{s.importo.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                    <button className="btn btn-ghost" style={{ marginTop: 8 }}>
                      Vedi in Spese
                      <Icon name="arrow-right" size={14} />
                    </button>
                  </div>
                )}

                {data.repartiFrequenti.length > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 10 }}>Reparti più frequenti</h5>
                    <div>
                      {data.repartiFrequenti.map((r) => (
                        <div className="listrow" style={{ padding: '9px 0' }} key={r.nome}>
                          <span style={{ fontSize: 14 }}>{r.nome}</span>
                          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                            <Bar quota={r.quota} width={80} />
                          </div>
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

      <AskBar placeholder="«aggiungi due yogurt e la carta forno alla lista»" />
    </>
  );
}
