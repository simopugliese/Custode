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
 */
export function CampoAggiunta({
  placeholder,
  inCorso,
  conData = false,
  dataIniziale = '',
  onSalva,
  onAnnulla,
}: {
  placeholder: string;
  inCorso: boolean;
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
    setTesto('');
    setScadenza(dataIniziale);
  }

  return (
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
      />
      {conData && (
        <input
          className="input"
          type="date"
          style={{ width: 150, flex: 'none' }}
          aria-label="Scadenza"
          value={scadenza}
          onChange={(e) => setScadenza(e.target.value)}
        />
      )}
      <button className="btn btn-primary" type="submit" disabled={!valido || inCorso}>
        <Icon name="check" size={15} />
        Aggiungi
      </button>
      <button className="btn btn-ghost" type="button" onClick={onAnnulla}>
        Annulla
      </button>
    </form>
  );
}
