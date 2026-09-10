"""I modi in cui la lettura del calendario può fallire.

Sono distinti perché richiedono cose diverse da chi li riceve: una rete che non
va si riprova, un'autorizzazione morta no — va rifatta a mano, e finché non lo
fai il calendario resta fermo. Confonderli vorrebbe dire riprovare per giorni
una cosa che non funzionerà mai.
"""

from __future__ import annotations


class ErroreCalendario(RuntimeError):
    """Radice di tutto ciò che può andare storto leggendo il calendario."""


class CalendarioNonConfigurato(ErroreCalendario):
    """Mancano le credenziali: il modulo è spento, non rotto."""


class CalendarioNonRaggiungibile(ErroreCalendario):
    """Google non risponde adesso. Si riprova al giro dopo."""


class AutorizzazioneNonValida(ErroreCalendario):
    """Il refresh token non vale più: nessun numero di tentativi lo farà tornare.

    Le cause vere sono tre, e il messaggio le nomina perché la più probabile è
    anche la meno intuitiva: il progetto su Google Cloud è rimasto in
    «Testing», e lì i refresh token muoiono dopo sette giorni.
    """
