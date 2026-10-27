/**
 * Thin fetch wrapper for the Custode REST API (see /API.md for the contract).
 * The API is reached through the Cloudflare Tunnel + Access chain described
 * in the architecture doc — Access authenticates the request before it gets
 * here. The client holds no secret of its own, but it must let the browser send
 * the Access session cookie on cross-origin calls (`credentials: 'include'`),
 * which also needs the API to answer with `Access-Control-Allow-Credentials`.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function apiConfigured() {
  return BASE_URL.length > 0;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!BASE_URL) {
    throw new ApiError(0, 'VITE_API_BASE_URL non configurato: imposta l\'indirizzo dell\'API di Custode in .env');
  }
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}/api${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
    });
  } catch {
    throw new ApiError(0, 'Impossibile contattare Custode: verifica connessione e tunnel.');
  }
  if (!res.ok) {
    let message = res.statusText || `Errore ${res.status}`;
    try {
      const body = await res.json();
      message = body?.detail ?? body?.message ?? message;
    } catch {
      /* risposta senza corpo JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  // Sostituisce una risorsa singola: oggi solo la posizione (§8.12), risponde 204.
  put: (path: string, body: unknown) =>
    request<void>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  // Serve a togliere una spesa sbagliata (§8.5): risponde 204, quindi il tipo
  // di ritorno è sempre vuoto.
  del: (path: string) => request<void>(path, { method: 'DELETE' }),
};

/**
 * `true` se la fetch non è nemmeno partita. Con la sessione di Access scaduta
 * (24 ore) la richiesta viene reindirizzata al login e il browser la segnala
 * come errore CORS: da qui non si distingue da una rete assente, ma il rimedio
 * più probabile è rinnovare l'accesso.
 */
export function erroreDiRete(errore: unknown): boolean {
  return errore instanceof ApiError && errore.status === 0 && apiConfigured();
}

/** Una pagina dell'API che fa passare dal login di Access e rimette il cookie. */
export function urlRinnovoAccesso(): string {
  return `${BASE_URL}/api/health`;
}

/**
 * Il messaggio da mostrare per un errore qualunque.
 *
 * `ApiError` porta già la frase giusta — il `detail` dell'API, o «Impossibile
 * contattare Custode» se la fetch non è nemmeno partita. Qualunque altra cosa
 * arrivi qui è un guasto della pagina, non una risposta, e mostrarne il
 * messaggio grezzo direbbe all'utente qualcosa che non lo riguarda.
 */
export function messaggioErrore(errore: unknown): string {
  return errore instanceof ApiError ? errore.message : 'Errore imprevisto.';
}
