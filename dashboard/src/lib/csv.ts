import type { Movimento } from '../types/api';

// Punto e virgola e virgola decimale: è ciò che Excel italiano apre in colonne
// senza chiedere niente. Il BOM davanti gli fa leggere gli accenti come UTF-8.
const cella = (valore: string) =>
  /[;"\n\r]/.test(valore) ? `"${valore.replace(/"/g, '""')}"` : valore;

export function movimentiInCsv(movimenti: Movimento[]): string {
  const righe = movimenti.map((m) =>
    [m.data, m.descrizione, m.categoria, m.luogo ?? '', m.importo.toFixed(2).replace('.', ',')]
      .map(cella)
      .join(';'),
  );
  return ['Data;Descrizione;Categoria;Luogo;Importo', ...righe].join('\r\n');
}

export function scaricaCsv(nomeFile: string, contenuto: string) {
  const url = URL.createObjectURL(new Blob(['﻿', contenuto], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = nomeFile;
  a.click();
  URL.revokeObjectURL(url);
}
