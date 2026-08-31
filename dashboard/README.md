# Custode — Dashboard

Frontend statico della dashboard di controllo di Custode (React + Vite +
TypeScript). Consuma la REST API descritta in `../project/uploads/assistente-ia-personale-design.md`
tramite il contratto documentato in [`API.md`](./API.md): nessun dato finto,
ogni pagina mostra caricamento/errore finché l'API non è raggiungibile.

Il design viene dal bundle esportato da Claude Design in `../project/`
(`Custode Dashboard.dc.html`, il design system Modernist, `custode.css`) — i
CSS sono stati portati qui pressoché invariati in `src/styles/`; le sole
regole aggiunte adattano il canvas del prototipo (larghezza fissa 1380px) a
un viewport reale (`src/styles/layout.css`).

## Sviluppo

```bash
npm install
cp .env.example .env   # imposta VITE_API_BASE_URL sull'indirizzo della tua API
npm run dev
```

Senza `VITE_API_BASE_URL` configurato ogni pagina mostra lo stato d'errore
("VITE_API_BASE_URL non configurato…") invece di dati finti — è il
comportamento atteso finché bot/API/DB non sono in piedi.

## Struttura

- `src/styles/` — `modernist.css` (design system) + `custode.css` (override
  Custode: accento verde, tema giorno/antracite) + `layout.css` (bento
  layout, rail, adattamenti per un viewport reale).
- `src/types/api.ts` — tipi delle risposte API, uno per pagina.
- `src/lib/apiClient.ts` — wrapper fetch, legge `VITE_API_BASE_URL`.
- `src/hooks/` — un hook TanStack Query per pagina + le mutazioni (spunte,
  approvazioni, pausa/attiva regole, log abitudini, messaggi a Custode).
- `src/components/` — primitive condivise (Checkbox, Tag, SegmentedControl,
  AskBar, TaskRow, ecc.) che ricalcano le classi del design system.
- `src/pages/` — le 9 pagine, una per voce di navigazione.

## Build & deploy (Cloudflare Pages)

```bash
npm run build   # output in dist/
```

`public/_redirects` reindirizza ogni percorso a `index.html` (routing lato
client con React Router) — copiato automaticamente in `dist/` dal build.
Imposta `VITE_API_BASE_URL` come variabile d'ambiente del progetto Pages
(Settings → Environment variables): nessun segreto qui, solo l'indirizzo
pubblico raggiunto tramite Cloudflare Tunnel — l'autenticazione la fa
Cloudflare Access davanti al tunnel.
