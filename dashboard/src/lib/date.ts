/**
 * La data di oggi come `YYYY-MM-DD`, nel fuso di **chi guarda**.
 *
 * Non `new Date().toISOString().slice(0, 10)`: quella è la data UTC, e la sera
 * tardi in Italia è già il giorno dopo. Un task creato alle 23:30 finirebbe
 * con la scadenza di domani senza che niente lo dica.
 */
export function oggiISO(): string {
  const adesso = new Date();
  const mese = String(adesso.getMonth() + 1).padStart(2, '0');
  const giorno = String(adesso.getDate()).padStart(2, '0');
  return `${adesso.getFullYear()}-${mese}-${giorno}`;
}
