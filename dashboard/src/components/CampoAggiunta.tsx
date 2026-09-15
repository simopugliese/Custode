import { useState } from 'react';
import { Icon } from '../lib/icons';

/**
 * La riga con cui si aggiunge una cosa senza passare dal linguaggio libero:
 * un task, una voce della lista. Compare sotto il bottone «Aggiungi» che
 * l'ha aperta e sparisce appena hai finito.
 *
 * **Perché esiste accanto alla barra «A Custode».** Quella manda il testo al
 * modello, che decide cosa farne: è comoda quando la frase è una frase
 * («ricordami di chiamare il prof giovedì»), ma dipende dal modello — se la
 * chiave manca o DeepSeek non risponde, non aggiungi niente. Questo campo
 * scrive direttamente sul database dalla pagina che stai già guardando, e
 * funziona anche quando il modello è spento.
 *
 * Un campo solo, e una data solo dove serve davvero: un form lungo in mezzo a
 * un elenco lo trasformerebbe in un modulo da compilare.
 *
 * **Chi chiude il campo è chi salva, e solo quando la scrittura è andata.** Il
 * campo non si svuota e non si chiude da sé: se lo facesse al momento del
 * clic, una POST fallita — API irraggiungibile, tunnel giù — lascerebbe la
 * pagina identica a prima con quello che avevi scritto buttato via, cioè un
 * bottone indistinguibile da uno rotto. Restando aperto tiene il testo, mostra
 * `errore` e si può riprovare senza riscrivere niente.
 */
export function CampoAggiunta({
  placeholder,
  inCorso,
  errore = null,
  conData = false,
  dataIniziale = '',
  onSalva,
  onAnnulla,
}: {
  placeholder: string;
  inCorso: boolean;
  /** Perché l'ultimo tentativo non è andato. `null` finché non è successo. */
  errore?: string | null;
  /** Mostra anche la scadenza. Serve ai task, non alla lista della spesa. */
  conData?: boolean;
  /**
   * Con che data nasce il campo. La Home la riempie con oggi: lì il bottone
   * sta dentro il blocco «Oggi», e un task senza scadenza — che finisce in
   * «Senza scadenza», su un'altra pagina — sparirebbe appena aggiunto,
   * lasciando il bottone indistinguibile da uno rotto. Resta modificabile.
   */
  dataIniziale?: string;
  onSalva: (testo: string, scadenza?: string) => void;
  onAnnulla: () => void;
}) {
  const [testo, setTesto] = useState('');
  const [scadenza, setScadenza] = useState(dataIniziale);
  const valido = testo.trim().length > 0;

  function salva(e: React.FormEvent) {
    e.preventDefault();
    if (!valido || inCorso) return;
    onSalva(testo.trim(), scadenza || undefined);
  }

  return (
    <div>
      <form
        onSubmit={salva}
        // Esc chiude, come ci si aspetta da un campo aperto per sbaglio. Sul
        // form e non sull'input: così vale anche mentre scegli la data.
        onKeyDown={(e) => {
          if (e.key === 'Escape') onAnnulla();
        }}
        className="row"
        style={{ gap: 8, padding: '10px 0' }}
      >
        <input
          className="input"
          // Il bottone l'ha appena aperto: il cursore deve essere già qui,
          // altrimenti il clic in più lo rende più lento che scriverlo al bot.
          autoFocus
          placeholder={placeholder}
          value={testo}
          onChange={(e) => setTesto(e.target.value)}
          disabled={inCorso}
        />
        {conData && (
          <input
            className="input"
            type="date"
            style={{ width: 150, flex: 'none' }}
            aria-label="Scadenza"
            value={scadenza}
            onChange={(e) => setScadenza(e.target.value)}
            disabled={inCorso}
          />
        )}
        <button className="btn btn-primary" type="submit" disabled={!valido || inCorso}>
          <Icon name="check" size={15} />
          {inCorso ? 'Aggiungo…' : 'Aggiungi'}
        </button>
        <button className="btn btn-ghost" type="button" onClick={onAnnulla}>
          Annulla
        </button>
      </form>
      {errore && (
        <div className="cu-muted" style={{ fontSize: 12, paddingBottom: 10 }} role="alert">
          Non aggiunto — {errore}
        </div>
      )}
    </div>
  );
}
