import { CheckCircle } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { Tag } from '../components/Tag';
import { Icon } from '../lib/icons';
import { useTheme } from '../theme/ThemeContext';
import { useAggiornaImpostazioni, useImpostazioni } from '../hooks/useImpostazioni';
import type { ImpostazioniData } from '../types/api';

const APPROVAZIONE_OPTIONS = [
  { value: 'chiedi', label: 'Chiedi' },
  { value: 'automatico', label: 'Automatico' },
] as const;

type Approvazione = 'chiedi' | 'automatico';

const CONNESSIONE_LABEL: Record<ImpostazioniData['connessioni'][number]['stato'], string> = {
  collegato: 'collegato',
  attiva: 'attiva',
  non_collegato: 'non collegato',
};

export default function Impostazioni() {
  const { data, isLoading, error, refetch } = useImpostazioni();
  const aggiorna = useAggiornaImpostazioni();
  const { theme } = useTheme();

  function patchOrari(partial: Partial<ImpostazioniData['orari']>) {
    if (!data) return;
    aggiorna.mutate({ orari: { ...data.orari, ...partial } });
  }
  function patchApprovazioni(partial: Partial<ImpostazioniData['approvazioni']>) {
    if (!data) return;
    aggiorna.mutate({ approvazioni: { ...data.approvazioni, ...partial } });
  }
  function patchBudget(partial: Partial<ImpostazioniData['budget']>) {
    if (!data) return;
    aggiorna.mutate({ budget: { ...data.budget, ...partial } });
  }

  return (
    <>
      <PageHeader kicker="Impostazioni" title="Come e quando Custode ti parla." />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            <div className="row" style={{ padding: '13px 0', borderBottom: '1px solid var(--color-rule)', gap: 10 }}>
              <CheckCircle size={15} color="var(--color-accent)" />
              <span style={{ fontSize: 13 }}>{data.botStatoLabel}</span>
              <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.apiStatoLabel}</span>
            </div>

            <div className="cols">
              <div className="colL">
                <div>
                  <h5 style={{ marginBottom: 14 }}>Orari</h5>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Digest mattutino</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>Meteo, lezioni, task e spesa</div>
                      </div>
                      <input
                        className="input cu-mono"
                        style={{ width: 96, flex: 'none', textAlign: 'center' }}
                        defaultValue={data.orari.digestMattutino}
                        onBlur={(e) => patchOrari({ digestMattutino: e.target.value })}
                      />
                    </div>
                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Check-in serale lezioni</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>Minuti dopo l'ultima lezione</div>
                      </div>
                      <input
                        className="input cu-mono"
                        type="number"
                        style={{ width: 96, flex: 'none', textAlign: 'center' }}
                        defaultValue={data.orari.checkInMinutiDopo}
                        onBlur={(e) => patchOrari({ checkInMinutiDopo: Number(e.target.value) })}
                      />
                    </div>
                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Voce di diario</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>Quando Custode prepara il riassunto del giorno</div>
                      </div>
                      <input
                        className="input cu-mono"
                        style={{ width: 96, flex: 'none', textAlign: 'center' }}
                        defaultValue={data.orari.voceDiarioOra}
                        onBlur={(e) => patchOrari({ voceDiarioOra: e.target.value })}
                      />
                    </div>
                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Riepilogo settimanale</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>Giorno</div>
                      </div>
                      <div style={{ flex: 'none' }}>
                        <SegmentedControl
                          name="sett"
                          options={[{ value: 'domenica', label: 'Domenica' }, { value: 'lunedi', label: 'Lunedì' }]}
                          value={data.orari.riepilogoSettimanaleGiorno}
                          onChange={(v) => patchOrari({ riepilogoSettimanaleGiorno: v as 'domenica' | 'lunedi' })}
                        />
                      </div>
                    </div>
                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Ore di silenzio</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>Nessun messaggio in questa fascia</div>
                      </div>
                      <div className="row" style={{ flex: 'none', gap: 8 }}>
                        <input
                          className="input cu-mono"
                          style={{ width: 82, textAlign: 'center' }}
                          defaultValue={data.orari.oreSilenzio.inizio}
                          onBlur={(e) => patchOrari({ oreSilenzio: { ...data.orari.oreSilenzio, inizio: e.target.value } })}
                        />
                        <span className="cu-muted">–</span>
                        <input
                          className="input cu-mono"
                          style={{ width: 82, textAlign: 'center' }}
                          defaultValue={data.orari.oreSilenzio.fine}
                          onBlur={(e) => patchOrari({ oreSilenzio: { ...data.orari.oreSilenzio, fine: e.target.value } })}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                <div>
                  <h5 style={{ marginBottom: 14 }}>Approvazioni</h5>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    {(
                      [
                        { key: 'vociDiario', titolo: 'Voci di diario', nota: 'Se disattivi, entrano nel diario senza chiedere' },
                        { key: 'nuoveRegole', titolo: 'Nuove regole di contesto', nota: 'Consigliato: chiedi sempre' },
                        { key: 'categorieSpesa', titolo: 'Categorie di spesa nuove', nota: 'Quando Custode ne inventa una' },
                        { key: 'scontrini', titolo: 'Scontrini letti da foto', nota: 'Importo e categoria dedotti dall\'immagine' },
                      ] as const
                    ).map((row) => (
                      <div className="row" key={row.key}>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 15, fontWeight: 600 }}>{row.titolo}</div>
                          <div className="cu-muted" style={{ fontSize: 12 }}>{row.nota}</div>
                        </div>
                        <div style={{ flex: 'none' }}>
                          <SegmentedControl
                            name={`ap-${row.key}`}
                            options={[...APPROVAZIONE_OPTIONS]}
                            value={data.approvazioni[row.key]}
                            onChange={(v) => patchApprovazioni({ [row.key]: v as Approvazione })}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h5 style={{ marginBottom: 14 }}>Connessioni</h5>
                  <div>
                    {data.connessioni.map((c) => (
                      <div className="listrow" style={{ padding: '14px 0' }} key={c.nome}>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 15, fontWeight: 600 }}>{c.nome}</div>
                          <div className="cu-muted" style={{ fontSize: 12 }}>{c.dettaglio}</div>
                        </div>
                        <Tag variant={c.stato === 'non_collegato' ? 'outline' : 'accent'}>{CONNESSIONE_LABEL[c.stato]}</Tag>
                        <button className="btn btn-ghost" style={{ marginLeft: 10 }}>
                          {c.stato === 'non_collegato' ? 'Collega' : 'Gestisci'}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="colR">
                <div>
                  <h5 style={{ marginBottom: 14 }}>Aspetto</h5>
                  <div className="row" style={{ marginBottom: 14 }}>
                    <span style={{ flex: 1, fontSize: 14 }}>Tema</span>
                    <span className="cu-muted" style={{ fontSize: 13 }}>{theme === 'giorno' ? 'Giorno' : 'Notte'}</span>
                  </div>
                  <div className="row">
                    <span style={{ flex: 1, fontSize: 14 }}>Prima settimana</span>
                    <div style={{ flex: 'none' }}>
                      <SegmentedControl
                        name="wk"
                        options={[{ value: 'lunedi', label: 'Lunedì' }, { value: 'domenica', label: 'Domenica' }]}
                        value={data.primaSettimana}
                        onChange={(v) => aggiorna.mutate({ primaSettimana: v as 'lunedi' | 'domenica' })}
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <h5 style={{ marginBottom: 14 }}>Budget</h5>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                    <div className="row">
                      <span style={{ flex: 1, fontSize: 14 }}>Settimanale</span>
                      <input
                        className="input cu-mono"
                        style={{ width: 110, flex: 'none', textAlign: 'right' }}
                        defaultValue={data.budget.settimanale.toFixed(2)}
                        onBlur={(e) => patchBudget({ settimanale: Number(e.target.value.replace(',', '.')) || data.budget.settimanale })}
                      />
                    </div>
                    <div className="row">
                      <span style={{ flex: 1, fontSize: 14 }}>Mensile</span>
                      <input
                        className="input cu-mono"
                        style={{ width: 110, flex: 'none', textAlign: 'right' }}
                        defaultValue={data.budget.mensile.toFixed(2)}
                        onBlur={(e) => patchBudget({ mensile: Number(e.target.value.replace(',', '.')) || data.budget.mensile })}
                      />
                    </div>
                    <div className="row">
                      <span style={{ flex: 1, fontSize: 14 }}>Soglia di avviso</span>
                      <input
                        className="input cu-mono"
                        style={{ width: 110, flex: 'none', textAlign: 'right' }}
                        defaultValue={data.budget.sogliaAvvisoPercento}
                        onBlur={(e) => patchBudget({ sogliaAvvisoPercento: Number(e.target.value) || data.budget.sogliaAvvisoPercento })}
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <h5 style={{ marginBottom: 14 }}>Dati</h5>
                  <div>
                    <div className="listrow" style={{ padding: '11px 0' }}>
                      <span style={{ fontSize: 14 }}>Voci di diario</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.dati.vociDiario}</span>
                    </div>
                    <div className="listrow" style={{ padding: '11px 0' }}>
                      <span style={{ fontSize: 14 }}>Spese registrate</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.dati.speseRegistrate}</span>
                    </div>
                    <div className="listrow" style={{ padding: '11px 0' }}>
                      <span style={{ fontSize: 14 }}>Messaggi al bot</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.dati.messaggiBot}</span>
                    </div>
                    <div className="listrow" style={{ padding: '11px 0' }}>
                      <span style={{ fontSize: 14 }}>Ultimo backup</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.dati.ultimoBackupLabel}</span>
                    </div>
                  </div>
                  <div className="row" style={{ gap: 6, marginTop: 14 }}>
                    <button className="btn btn-secondary">
                      <Icon name="download" size={15} />
                      Esporta tutto
                    </button>
                    <button className="btn btn-ghost">Cancella un periodo</button>
                  </div>
                </div>

                <div style={{ marginTop: 'auto' }}>
                  <h5 style={{ marginBottom: 10 }}>Sistema</h5>
                  <div>
                    <div className="listrow" style={{ padding: '9px 0' }}>
                      <span style={{ fontSize: 14 }}>API</span>
                      <span style={{ marginLeft: 'auto' }}>
                        <Tag variant={data.sistema.apiOnline ? 'accent' : 'outline'}>{data.sistema.apiOnline ? 'online' : 'offline'}</Tag>
                      </span>
                    </div>
                    <div className="listrow" style={{ padding: '9px 0' }}>
                      <span style={{ fontSize: 14 }}>Ultimo sync calendario</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.sistema.ultimoSyncCalendarioLabel}</span>
                    </div>
                    <div className="listrow" style={{ padding: '9px 0' }}>
                      <span style={{ fontSize: 14 }}>Versione</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.sistema.versione}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«manda il digest alle 7 invece che alle 7:30»" />
    </>
  );
}
