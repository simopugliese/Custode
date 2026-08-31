# worker — job schedulati

I lavori che girano da soli (ARCHITECTURE.md §5): controllo scadenze task e
promemoria su Telegram (§8.2), riepilogo settimanale del diario con rifusione
del `profile_document` (§8.4), digest mattutino (§8.13), valutazione delle
regole di contesto approvate (§8.10), backup cifrato del DB (§9).

## Stato

Vuota. I singoli job nascono insieme al modulo che servono, non prima: il primo
utile è il controllo delle scadenze, subito dopo che task e promemoria hanno
persistenza reale.
