import { useEffect, useState } from 'react';
import { Send } from 'lucide-react';
import { useAssistente } from '../hooks/useAssistente';

/**
 * Barra "A Custode" — un campo in stile chat presente in ogni pagina per
 * parlare a Custode dal PC, come richiesto nel brief originale (§ risposte
 * al form: "Un campo di input in stile chat anche qui").
 */
/**
 * `id` serve a chi vuole mandarci qualcuno: la pagina Regole ha un bottone
 * «Scrivine una» che porta qui invece di aprire una form con cinque campi.
 * Sarebbe un secondo modo di creare la stessa cosa, da tenere allineato al
 * primo per sempre — mentre la barra accetta già «ricordami la creatina tutti
 * i giorni alle 19», che è come lo diresti.
 *
 * `bozza` è la stessa idea portata un passo più in là, e serve a «Riscrivila a
 * parole» sulle proposte (§8.10): invece di una form per correggere i
 * parametri di una regola proposta, la si riscrive **qui**, partendo dal testo
 * che Custode aveva in mente. Resta un canale solo per creare regole, che è
 * quello che il contratto impone.
 *
 * `chiave` cambia ad ogni richiesta e non è un dettaglio: due tap sullo stesso
 * bottone hanno lo stesso `testo`, e senza qualcosa che cambi il secondo non
 * riscriverebbe la barra che nel frattempo hai modificato a mano.
 */
export function AskBar({
  placeholder,
  id,
  bozza,
}: {
  placeholder: string;
  id?: string;
  bozza?: { testo: string; chiave: number };
}) {
  const [testo, setTesto] = useState('');

  useEffect(() => {
    if (!bozza) return;
    setTesto(bozza.testo);
    // Il fuoco va dove va il testo: senza, la barra si riempie in fondo alla
    // pagina e chi ha premuto il bottone non ha idea che sia successo qualcosa.
    document.getElementById(id ?? '')?.focus();
    // Solo la chiave: il testo di una bozza non cambia senza che ne arrivi una
    // nuova, e guardarlo rimetterebbe la bozza ad ogni battuta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bozza?.chiave]);
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
      {/* Le frasi stanno **sopra** la riga, non sotto: la barra è in fondo alla
          pagina, e una conferma disegnata sotto di lei finisce sotto il bordo
          dello schermo — cioè proprio dove non la si legge. Chi ha appena
          premuto «Invia» sta guardando la barra: l'esito va lì, e vale sia per
          «Segnato: comprare il pane» sia per «manca la chiave del modello»,
          che è il caso in cui non vederlo fa più danno. */}
      {!isError && !isPending && fatte.length > 0 && (
        <div className="ask-esiti">
          {fatte.map((frase, i) => (
            <span key={i} className="cu-muted" style={{ fontSize: 12 }}>
              {frase}
            </span>
          ))}
        </div>
      )}
      <div className="ask">
        <span className="cu-kicker" style={{ flex: 'none' }}>
          A Custode
        </span>
        <input
          id={id}
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
    </div>
  );
}
