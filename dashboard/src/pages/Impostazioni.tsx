import { AlertCircle, CheckCircle } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { Tag } from '../components/Tag';
import { useTheme } from '../theme/ThemeContext';
import { messaggioErrore } from '../lib/apiClient';
import { useAggiornaImpostazioni, useImpostazioni } from '../hooks/useImpostazioni';
import type { ImpostazioniData } from '../types/api';

/**
 * La pagina mostra **solo** le manopole che girano qualcosa (§8).
 *
 * Il prototipo ne aveva molte di più — digest mattutino, ora della voce di
 * diario, ore di silenzio, le quattro approvazioni, il primo giorno della
 * settimana — e il backend non le manda perché nessun modulo le legge ancora.
 * Disegnarle comunque vorrebbe dire un interruttore che non interrompe: lo
 * giri, non succede niente, e da lì in poi non ti fidi più nemmeno di quelli
 * che funzionano. Torneranno col modulo che le legge.
 */
const CONNESSIONE_LABEL: Record<ImpostazioniData['connessioni'][number]['stato'], string> = {
  collegato: 'collegato',
  non_collegato: 'non collegato',
};

export default function Impostazioni() {
  const { data, isLoading, error, refetch } = useImpostazioni();
  const aggiorna = useAggiornaImpostazioni();
  const { theme } = useTheme();
  const botCollegato =
    data?.connessioni.find((c) => c.nome === 'Telegram')?.stato === 'collegato';

  function patchOrari(partial: Partial<ImpostazioniData['orari']>) {
    aggiorna.mutate({ orari: partial });
  }

  /**
   * Il budget è l'unico campo in cui «vuoto» è una scelta e non un errore: lo
   * si manda come stringa vuota, e il backend lo legge come «nessun tetto» —
   * da lì la Home smette di disegnare il blocco delle spese (§8.5).
   */
  function patchBudget(testo: string) {
    aggiorna.mutate({ budget: { settimanale: testo.trim() === '' ? null : testo } });
  }

  return (
    <>
      <PageHeader kicker="Impostazioni" title="Come e quando Custode ti parla." />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {/* L'icona segue lo stato vero del bot: una spunta verde accanto a
                «non configurato» è la riga che ti fa scorrere oltre senza
                leggerla, ed è proprio quella da leggere. */}
            <div className="row" style={{ padding: '13px 0', borderBottom: '1px solid var(--color-rule)', gap: 10 }}>
              {botCollegato ? (
                <CheckCircle size={15} color="var(--color-accent)" />
              ) : (
                <AlertCircle size={15} className="cu-muted" />
              )}
              <span style={{ fontSize: 13 }}>{data.botStatoLabel}</span>
              <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 12 }}>{data.apiStatoLabel}</span>
            </div>

            {/* L'esito nei due versi. Quello che manca fa più danno dell'altro:
                senza il ramo d'errore, una PATCH rifiutata lascia il campo come
                l'hai scritto e la pagina identica a prima. */}
            {aggiorna.isError && (
              <div className="state-msg is-error" style={{ marginTop: 12 }} role="alert">
                Non salvato — {messaggioErrore(aggiorna.error)}
              </div>
            )}

            <div className="cols">
              <div className="colL">
                <div>
                  <h5 style={{ marginBottom: 14 }}>Orari</h5>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Riepilogo settimanale</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>
                          Quando Custode chiude la settimana del diario e ti manda il riepilogo
                        </div>
                      </div>
                      <div className="row" style={{ flex: 'none', gap: 8 }}>
                        <SegmentedControl
                          name="sett"
                          options={[{ value: 'domenica', label: 'Domenica' }, { value: 'lunedi', label: 'Lunedì' }]}
                          value={data.orari.riepilogoSettimanaleGiorno}
                          onChange={(v) => patchOrari({ riepilogoSettimanaleGiorno: v as 'domenica' | 'lunedi' })}
                        />
                        <input
                          className="input cu-mono"
                          style={{ width: 82, flex: 'none', textAlign: 'center' }}
                          aria-label="Ora del riepilogo settimanale"
                          defaultValue={data.orari.riepilogoSettimanaleOra}
                          key={data.orari.riepilogoSettimanaleOra}
                          onBlur={(e) => patchOrari({ riepilogoSettimanaleOra: e.target.value })}
                        />
                      </div>
                    </div>

                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Proposte di regole</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>
                          Quando Custode cerca pattern nei tuoi dati e ti propone una regola
                          (§8.10). Finché non la sposti segue l'ora del riepilogo.
                        </div>
                      </div>
                      <input
                        className="input cu-mono"
                        style={{ width: 82, flex: 'none', textAlign: 'center' }}
                        aria-label="Ora delle proposte di regole"
                        defaultValue={data.orari.proposteRegoleOra}
                        key={data.orari.proposteRegoleOra}
                        onBlur={(e) => patchOrari({ proposteRegoleOra: e.target.value })}
                      />
                    </div>

                    <div className="row">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Margine dopo l'ultima lezione</div>
                        <div className="cu-muted" style={{ fontSize: 12 }}>
                          Minuti prima che Custode ti consideri a casa. Lo userà il check-in serale
                          (§8.10), che non c'è ancora: intanto il numero è tuo.
                        </div>
                      </div>
                      <input
                        className="input cu-mono"
                        type="number"
                        min={0}
                        max={720}
                        style={{ width: 96, flex: 'none', textAlign: 'center' }}
                        aria-label="Minuti dopo l'ultima lezione"
                        defaultValue={data.orari.checkInMinutiDopo}
                        key={data.orari.checkInMinutiDopo}
                        onBlur={(e) => patchOrari({ checkInMinutiDopo: Number(e.target.value) })}
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <h5 style={{ marginBottom: 6 }}>Connessioni</h5>
                  <p className="cu-muted" style={{ fontSize: 12, marginBottom: 10, lineHeight: 1.6 }}>
                    Le credenziali stanno nel <code>.env</code> del Pi e da qui non si toccano (§9):
                    questa lista dice solo cosa è collegato, e cosa smette di funzionare se non lo è.
                  </p>
                  <div>
                    {data.connessioni.map((c) => (
                      <div className="listrow" style={{ padding: '14px 0', display: 'block' }} key={c.nome}>
                        <div className="row">
                          <span style={{ fontSize: 15, fontWeight: 600 }}>{c.nome}</span>
                          <span style={{ marginLeft: 'auto' }}>
                            <Tag variant={c.stato === 'non_collegato' ? 'outline' : 'accent'}>
                              {CONNESSIONE_LABEL[c.stato]}
                            </Tag>
                          </span>
                        </div>
                        <div className="cu-muted" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.5 }}>
                          {c.dettaglio}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="colR">
                <div>
                  <h5 style={{ marginBottom: 14 }}>Budget</h5>
                  <div className="row">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14 }}>Settimanale</div>
                      <div className="cu-muted" style={{ fontSize: 12 }}>
                        Vuoto = nessun tetto, e la Home non disegna il blocco delle spese
                      </div>
                    </div>
                    <input
                      className="input cu-mono"
                      style={{ width: 110, flex: 'none', textAlign: 'right' }}
                      aria-label="Budget settimanale in euro"
                      placeholder="—"
                      // `key` rimonta il campo quando il valore cambia davvero:
                      // `defaultValue` da solo non si aggiorna dopo un salvataggio,
                      // e dopo averlo svuotato il campo mostrerebbe ancora il vecchio.
                      key={String(data.budget.settimanale)}
                      defaultValue={data.budget.settimanale?.toFixed(2) ?? ''}
                      onBlur={(e) => patchBudget(e.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <h5 style={{ marginBottom: 14 }}>Aspetto</h5>
                  <div className="row">
                    <span style={{ flex: 1, fontSize: 14 }}>Tema</span>
                    <span className="cu-muted" style={{ fontSize: 13 }}>{theme === 'giorno' ? 'Giorno' : 'Notte'}</span>
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
                      <span style={{ fontSize: 14 }}>Ultimo backup</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.dati.ultimoBackupLabel}</span>
                    </div>
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
                    {/* L'unico posto da cui si vede che il worker è fermo: la
                        pagina Calendario direbbe «niente in programma», che
                        rispetto all'archivio è pure vero (§8.10). */}
                    <div className="listrow" style={{ padding: '9px 0' }}>
                      <span style={{ fontSize: 14 }}>Ultimo sync calendario</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.sistema.ultimoSyncCalendarioLabel}</span>
                    </div>
                    <div className="listrow" style={{ padding: '9px 0' }}>
                      <span style={{ fontSize: 14 }}>Versione</span>
                      <span className="cu-mono cu-muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{data.sistema.versione}</span>
                    </div>
                  </div>
                  {data.notaLabel && (
                    <div className="cu-muted" style={{ fontSize: 12, marginTop: 12, lineHeight: 1.6 }}>
                      {data.notaLabel}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«manda il riepilogo il lunedì invece che la domenica»" />
    </>
  );
}
