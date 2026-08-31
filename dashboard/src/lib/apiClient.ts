/**
 * Thin fetch wrapper for the Custode REST API (see /API.md for the contract).
 * The API is reached through the Cloudflare Tunnel + Access chain described
 * in the architecture doc — Access authenticates the request before it gets
 * here, so this client sends no credentials of its own.
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
  patch: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
};
