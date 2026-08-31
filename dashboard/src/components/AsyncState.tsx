import type { ReactNode } from 'react';
import { ApiError } from '../lib/apiClient';

interface AsyncStateProps {
  isLoading: boolean;
  error: unknown;
  onRetry?: () => void;
  children: ReactNode;
}

/** Involucro condiviso da ogni pagina: nessun dato finto, solo caricamento / errore / contenuto. */
export function AsyncState({ isLoading, error, onRetry, children }: AsyncStateProps) {
  if (isLoading) {
    return <div className="state-msg">Caricamento…</div>;
  }
  if (error) {
    const message = error instanceof ApiError ? error.message : 'Errore imprevisto.';
    return (
      <div className="state-msg is-error row" style={{ gap: 12 }}>
        <span>{message}</span>
        {onRetry && (
          <button className="btn btn-ghost" onClick={onRetry}>
            Riprova
          </button>
        )}
      </div>
    );
  }
  return <>{children}</>;
}
