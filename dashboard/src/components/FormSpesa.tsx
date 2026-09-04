import { useState } from 'react';
import type { Movimento, NuovaSpesa } from '../types/api';

/**
 * Il form con cui si registra una spesa a mano e si corregge una sbagliata
 * (§8.5). È lo stesso in tutti e due i casi perché i campi sono gli stessi:
 * cambia solo da dove partono i valori.
 *
 * La **data** c'è sempre, ed è il motivo principale per cui questo form
 * esiste: una spesa che scrivi da qui è quasi sempre una che ti eri
 * dimenticato di dire al bot, quindi non è di oggi; e una spesa da correggere
 * ha spesso proprio la data sbagliata.
 */
export function FormSpesa({
  spesa,
  categorie,
  inCorso,
  onSalva,
  onAnnulla,
}: {
  spesa?: Movimento;
  categorie: string[];
  inCorso: boolean;
  // `NuovaSpesa` e non `ModificaSpesa`: il form manda sempre tutti i campi,
  // anche quando corregge, perché li ha tutti sotto gli occhi.
  onSalva: (corpo: NuovaSpesa) => void;
  onAnnulla: () => void;
}) {
  const [importo, setImporto] = useState(spesa ? String(spesa.importo) : '');
  const [descrizione, setDescrizione] = useState(spesa?.descrizione ?? '');
  const [categoria, setCategoria] = useState(
    // "Senza categoria" è l'etichetta che il backend mostra per l'assenza:
    // riproporla nel campo la trasformerebbe in una categoria vera.
    spesa && spesa.categoria !== 'Senza categoria' ? spesa.categoria : '',
  );
  const [luogo, setLuogo] = useState(spesa?.luogo ?? '');
  const [data, setData] = useState(spesa?.data ?? new Date().toISOString().slice(0, 10));

  const valore = Number(importo.replace(',', '.'));
  const valido = descrizione.trim().length > 0 && Number.isFinite(valore) && valore > 0;

  function salva(e: React.FormEvent) {
    e.preventDefault();
    if (!valido) return;
    onSalva({
      importo: valore,
      descrizione: descrizione.trim(),
      // Stringa vuota, non `undefined`: è così che si **toglie** un luogo o
      // una categoria sbagliata, che altrimenti resterebbe attaccata.
      categoria: categoria.trim(),
      luogo: luogo.trim(),
      data,
    });
  }

  return (
    <form
      onSubmit={salva}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8,
        alignItems: 'flex-end',
        padding: '12px 0',
        borderTop: '1px solid var(--color-divider)',
      }}
    >
      <datalist id="categorie-in-uso">
        {categorie.map((nome) => (
          <option key={nome} value={nome} />
        ))}
      </datalist>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, width: 96 }}>
        <span className="cu-kicker">Importo €</span>
        <input
          autoFocus
          value={importo}
          onChange={(e) => setImporto(e.target.value)}
          inputMode="decimal"
          placeholder="17,00"
          style={{ padding: '8px 10px', fontSize: 14 }}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 140 }}>
        <span className="cu-kicker">Descrizione</span>
        <input
          value={descrizione}
          onChange={(e) => setDescrizione(e.target.value)}
          placeholder="spesa"
          style={{ padding: '8px 10px', fontSize: 14 }}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, width: 140 }}>
        <span className="cu-kicker">Categoria</span>
        <input
          list="categorie-in-uso"
          value={categoria}
          onChange={(e) => setCategoria(e.target.value)}
          placeholder="nessuna"
          style={{ padding: '8px 10px', fontSize: 14 }}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, width: 130 }}>
        <span className="cu-kicker">Luogo</span>
        <input
          value={luogo}
          onChange={(e) => setLuogo(e.target.value)}
          placeholder="—"
          style={{ padding: '8px 10px', fontSize: 14 }}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, width: 150 }}>
        <span className="cu-kicker">Giorno</span>
        <input
          type="date"
          value={data}
          // Una spesa datata in avanti sarebbe scritta e invisibile in ogni
          // vista, che finisce a oggi (§8.5): il browser la blocca prima
          // ancora dell'API.
          max={new Date().toISOString().slice(0, 10)}
          onChange={(e) => setData(e.target.value)}
          style={{ padding: '8px 10px', fontSize: 14 }}
        />
      </label>

      <button className="btn btn-secondary" type="submit" disabled={!valido || inCorso}>
        {spesa ? 'Salva' : 'Registra'}
      </button>
      <button className="btn btn-ghost" type="button" onClick={onAnnulla}>
        Annulla
      </button>
    </form>
  );
}
