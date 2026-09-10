import { useState } from 'react';
import { Send } from 'lucide-react';
import { useAssistente } from '../hooks/useAssistente';

/**
 * Barra "A Custode" — un campo in stile chat presente in ogni pagina per
 * parlare a Custode dal PC, come richiesto nel brief originale (§ risposte
 * al form: "Un campo di input in stile chat anche qui").
 */
export function AskBar({ placeholder }: { placeholder: string }) {
  const [testo, setTesto] = useState('');
  const { mutate, data, isPending, isError } = useAssistente();

  function invia() {
    const trimmed = testo.trim();
    if (!trimmed || isPending) return;
    mutate(trimmed, { onSuccess: () => setTesto('') });
  }

  // Una riga per ogni cosa fatta: un messaggio può chiederne più d'una, e le
  // frasi arrivano già scritte dal backend. Senza mostrarle, mandare qualcosa
  // dalla barra non dava nessuna conferma di cosa fosse successo.
  const fatte = data?.risposteLabel ?? [];

  return (
    <div className="ask-blocco">
      <div className="ask">
        <span className="cu-kicker" style={{ flex: 'none' }}>
          A Custode
        </span>
        <input
          className="input"
          placeholder={placeholder}
          value={testo}
          onChange={(e) => setTesto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') invia();
          }}
        />
        <button className="btn btn-primary" onClick={invia} disabled={isPending}>
          <Send size={15} />
          <span>Invia</span>
        </button>
        {isError && (
          <span className="cu-muted" style={{ fontSize: 12 }}>
            Non inviato — Custode non è raggiungibile.
          </span>
        )}
      </div>
      {/* Le frasi stanno **sotto** la riga, non dentro: un messaggio ne può
          produrre più d'una, e farle stare sulla stessa riga del campo e del
          bottone li spingerebbe a capo uno per volta. */}
      {!isError && !isPending && fatte.length > 0 && (
        <div className="ask-esiti">
          {fatte.map((frase, i) => (
            <span key={i} className="cu-muted" style={{ fontSize: 12 }}>
              {frase}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
