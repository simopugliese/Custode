import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { AvvisoRow } from '../components/AvvisoRow';
import { StatsBar } from '../components/StatsBar';
import { AsyncState } from '../components/AsyncState';
import { AskBar } from '../components/AskBar';
import { SegmentedControl } from '../components/SegmentedControl';
import { Tag } from '../components/Tag';
import { Icon } from '../lib/icons';
import { useCalendario, useCorreggiTagEvento, type VistaCalendario } from '../hooks/useCalendario';
import type { CalendarioData, EventoCalendario, SerieDaRivedere, TipoEvento } from '../types/api';

const VISTE = [
  { value: 'settimana', label: 'Settimana' },
  { value: 'mese', label: 'Mese' },
  { value: 'da_rivedere', label: 'Da rivedere' },
] as const;

/** I tre stati del tag, e come si vedono. Le parole le manda il backend. */
const VARIANTE_STATO: Record<EventoCalendario['statoTag'], 'accent' | 'outline' | 'neutral'> = {
  da_guardare: 'outline',
  proposto: 'accent',
  corretto: 'neutral',
};

/**
 * Il menu con cui si corregge un tipo. È un `select` nativo: ha la tastiera e
 * il tocco già risolti, e questa è l'unica interazione della pagina che scrive.
 */
function SceltaTipo({
  valore,
  tipi,
  disabilitato,
  onScegli,
}: {
  valore: string;
  tipi: TipoEvento[];
  disabilitato: boolean;
  onScegli: (tipo: string) => void;
}) {
  return (
    <select
      className="cu-select"
      aria-label="Tipo dell'evento"
      value={valore}
      disabled={disabilitato}
      onChange={(e) => onScegli(e.target.value)}
    >
      {tipi.map((tipo) => (
        <option key={tipo.valore} value={tipo.valore}>
          {tipo.label}
        </option>
      ))}
    </select>
  );
}

function RigaEvento({
  evento,
  tipi,
  disabilitato,
  onCorreggi,
}: {
  evento: EventoCalendario;
  tipi: TipoEvento[];
  disabilitato: boolean;
  onCorreggi: (id: string, tipo: string) => void;
}) {
  return (
    <div className="listrow" style={{ padding: '10px 0', gap: 12, alignItems: 'baseline' }}>
      <span className="cu-mono" style={{ fontSize: 13, width: 46, flex: 'none' }}>
        {evento.ora}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14 }}>{evento.titolo}</div>
        {(evento.luogo || evento.meta) && (
          <div className="cu-muted" style={{ fontSize: 12, marginTop: 2 }}>
            {[evento.meta, evento.luogo].filter(Boolean).join(' · ')}
          </div>
        )}
      </div>
      <div
        className="row"
        style={{ marginLeft: 'auto', gap: 8, flex: 'none', alignItems: 'center' }}
      >
        <Tag variant={VARIANTE_STATO[evento.statoTag]}>{evento.statoTagLabel}</Tag>
        <SceltaTipo
          valore={evento.tipo}
          tipi={tipi}
          disabilitato={disabilitato}
          onScegli={(tipo) => onCorreggi(evento.id, tipo)}
        />
      </div>
    </div>
  );
}

function RigaDaRivedere({
  serie,
  tipi,
  disabilitato,
  onCorreggi,
}: {
  serie: SerieDaRivedere;
  tipi: TipoEvento[];
  disabilitato: boolean;
  onCorreggi: (id: string, tipo: string) => void;
}) {
  return (
    <article
      style={{ borderTop: '1px solid var(--color-divider)', padding: '14px 0' }}
      data-titolo={serie.titolo}
    >
      <div className="row" style={{ gap: 10, alignItems: 'baseline' }}>
        <span style={{ fontSize: 15 }}>{serie.titolo}</span>
        <Tag variant="accent">{serie.tipoLabel}</Tag>
        <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
          {serie.propostoLabel}
        </span>
      </div>
      <div className="cu-muted" style={{ fontSize: 12, marginTop: 4 }}>
        {[serie.quandoLabel, serie.occorrenzeLabel].filter(Boolean).join(' · ')}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 10, alignItems: 'center' }}>
        {/* Confermare lo stesso tipo è comunque una risposta: «ha indovinato»
            toglie la serie dalla coda senza doverla cambiare e rimettere. */}
        <button
          className="btn btn-primary"
          disabled={disabilitato}
          onClick={() => onCorreggi(serie.id, serie.tipo)}
        >
          <Icon name="check" size={15} />
          Va bene
        </button>
        <span className="cu-muted" style={{ fontSize: 12 }}>
          oppure è
        </span>
        <SceltaTipo
          valore={serie.tipo}
          tipi={tipi}
          disabilitato={disabilitato}
          onScegli={(tipo) => onCorreggi(serie.id, tipo)}
        />
        {serie.serie && (
          <span className="cu-muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
            vale per tutta la serie
          </span>
        )}
      </div>
    </article>
  );
}

function Legenda({ data }: { data: CalendarioData }) {
  return (
    <div>
      <h5 style={{ marginBottom: 12 }}>Cosa ha capito Custode</h5>
      <p className="cu-muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
        Il tipo di un impegno lo propone l'IA la prima volta, e tu lo correggi se serve: resta poi
        fisso per tutta la serie.
      </p>
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div className="row" style={{ gap: 8 }}>
          <Tag variant="outline">da guardare</Tag>
          <span className="cu-muted" style={{ fontSize: 12 }}>
            nessuno l'ha ancora visto
          </span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Tag variant="accent">proposto dall'IA</Tag>
          <span className="cu-muted" style={{ fontSize: 12 }}>
            deciso dal modello, mai confermato
          </span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Tag variant="neutral">corretto da te</Tag>
          <span className="cu-muted" style={{ fontSize: 12 }}>
            l'ultima parola è la tua
          </span>
        </div>
      </div>
      {data.orizzonteLabel && (
        <div className="cu-muted" style={{ fontSize: 12, marginTop: 16 }}>
          {data.orizzonteLabel}
        </div>
      )}
    </div>
  );
}

export default function Calendario() {
  const [vista, setVista] = useState<VistaCalendario>('settimana');
  const { data, isLoading, error, refetch } = useCalendario(vista);
  const correggi = useCorreggiTagEvento();

  const manda = (id: string, tipo: string) => correggi.mutate({ id, tipo });

  return (
    <>
      <PageHeader
        kicker={`Calendario${data ? ` · ${data.periodoLabel}` : ''}`}
        title={data?.titolo ?? 'Calendario'}
      />

      <AsyncState isLoading={isLoading} error={error} onRetry={refetch}>
        {data && (
          <>
            {data.stats.daRivedere > 0 && vista !== 'da_rivedere' && (
              <AvvisoRow
                icon="lightbulb"
                actionLabel="Guardale"
                actionIcon="arrow-right"
                onAction={() => setVista('da_rivedere')}
              >
                {data.stats.daRivedere === 1 ? (
                  <>
                    C'è <b>una proposta</b> dell'IA che non hai ancora confermato.
                  </>
                ) : (
                  <>
                    Ci sono <b>{data.stats.daRivedere} proposte</b> dell'IA che non hai ancora
                    confermato.
                  </>
                )}
              </AvvisoRow>
            )}

            {correggi.data && (
              <div className="cu-muted" style={{ fontSize: 13, marginBottom: 12 }}>
                {correggi.data.label}
              </div>
            )}

            <StatsBar
              items={[
                { label: 'Impegni nel periodo', value: data.stats.eventiPeriodo },
                { label: 'Da rivedere', value: data.stats.daRivedere, accent: true },
                { label: 'Da guardare', value: data.stats.daGuardare },
              ]}
            />

            <div className="cols">
              <div className="colL">
                <div className="row" style={{ gap: 6 }}>
                  <span className="cu-kicker" style={{ flex: 'none' }}>
                    Vista
                  </span>
                  <div style={{ marginLeft: 6 }}>
                    <SegmentedControl
                      name="perCalendario"
                      options={[...VISTE]}
                      value={vista}
                      onChange={(v) => setVista(v as VistaCalendario)}
                    />
                  </div>
                </div>

                {vista === 'da_rivedere' ? (
                  <div>
                    {data.daRivedere.map((serie) => (
                      <RigaDaRivedere
                        key={serie.id}
                        serie={serie}
                        tipi={data.tipi}
                        disabilitato={correggi.isPending}
                        onCorreggi={manda}
                      />
                    ))}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
                    {data.giorni.map((giorno) => (
                      <section key={giorno.label}>
                        <div
                          className="row"
                          style={{
                            borderTop: giorno.isOggi
                              ? '2px solid var(--color-accent)'
                              : '1px solid var(--color-divider)',
                            paddingTop: 10,
                          }}
                        >
                          <span className="cu-mono" style={{ fontSize: 13, fontWeight: 600 }}>
                            {giorno.label}
                          </span>
                          {giorno.isOggi && (
                            <span style={{ marginLeft: 'auto' }}>
                              <Tag variant="accent">oggi</Tag>
                            </span>
                          )}
                        </div>
                        {giorno.notaVuoto ? (
                          <div className="cu-muted" style={{ fontSize: 13, padding: '10px 0' }}>
                            {giorno.notaVuoto}
                          </div>
                        ) : (
                          giorno.eventi.map((evento) => (
                            <RigaEvento
                              key={evento.id}
                              evento={evento}
                              tipi={data.tipi}
                              disabilitato={correggi.isPending}
                              onCorreggi={manda}
                            />
                          ))
                        )}
                      </section>
                    ))}
                  </div>
                )}

                {data.notaVuoto && (
                  <div className="state-msg" style={{ marginTop: 10 }}>
                    {data.notaVuoto}
                  </div>
                )}
              </div>

              <div className="colR">
                <Legenda data={data} />
                {data.stats.daGuardare > 0 && (
                  <div>
                    <h5 style={{ marginBottom: 12 }}>Ancora da guardare</h5>
                    <p className="cu-muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
                      {data.stats.daGuardare === 1
                        ? "Un impegno non ha ancora un tipo: Custode lo guarda al prossimo giro, che è entro cinque minuti."
                        : `${data.stats.daGuardare} impegni non hanno ancora un tipo: Custode li guarda al prossimo giro, che è entro cinque minuti.`}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </AsyncState>

      <AskBar placeholder="«cosa ho giovedì?»" />
    </>
  );
}
