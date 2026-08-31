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
  const { mutate, isPending, isError } = useAssistente();

  function invia() {
    const trimmed = testo.trim();
    if (!trimmed || isPending) return;
    mutate(trimmed, { onSuccess: () => setTesto('') });
  }

  return (
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
  );
}
