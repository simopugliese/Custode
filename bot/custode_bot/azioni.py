"""Codifica dei `callback_data` dei bottoni inline.

Telegram limita `callback_data` a 64 byte, quindi le azioni sono siglate.
Averle in un modulo a parte, con parsing e formattazione simmetrici, evita che
la stringa venga costruita a mano in un punto e letta a mano in un altro.

Forma: `dominio:azione:argomento:vista`
  dominio  t = task, s = spesa, x = azioni di servizio
  vista    da quale elenco è partito il tap, per ridisegnare quello giusto
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Vista = Literal["task", "oggi", "lista"]

SIGLE_VISTA: dict[Vista, str] = {"task": "t", "oggi": "o", "lista": "l"}
VISTE_PER_SIGLA: dict[str, Vista] = {sigla: vista for vista, sigla in SIGLE_VISTA.items()}


class AzioneNonValida(ValueError):
    """Callback data che non corrisponde a nessuna azione conosciuta."""


@dataclass(frozen=True)
class Azione:
    dominio: Literal["t", "s", "x"]
    nome: str
    argomento: str = ""
    vista: Vista = "task"

    def dato(self) -> str:
        return f"{self.dominio}:{self.nome}:{self.argomento}:{SIGLE_VISTA[self.vista]}"


def leggi(dato: str) -> Azione:
    pezzi = dato.split(":")
    if len(pezzi) != 4:
        raise AzioneNonValida(dato)
    dominio, nome, argomento, sigla_vista = pezzi
    if dominio not in ("t", "s", "x") or sigla_vista not in VISTE_PER_SIGLA:
        raise AzioneNonValida(dato)
    return Azione(
        dominio=dominio,  # type: ignore[arg-type]
        nome=nome,
        argomento=argomento,
        vista=VISTE_PER_SIGLA[sigla_vista],
    )


def task_fatto(task_id: int, vista: Vista) -> str:
    return Azione("t", "fatto", str(task_id), vista).dato()


def task_rinvia(task_id: int, vista: Vista) -> str:
    return Azione("t", "rinvia", str(task_id), vista).dato()


def task_scadenza(task_id: int, quando: str) -> str:
    """Scadenza scelta col bottone subito dopo aver creato un task."""
    return Azione("t", f"sc-{quando}", str(task_id), "task").dato()


def voce_presa(voce_id: int, vista: Vista) -> str:
    return Azione("s", "preso", str(voce_id), vista).dato()


def svuota(conferma: bool) -> str:
    return Azione("x", "svuota", "si" if conferma else "no", "lista").dato()


def annulla(azione_assistente: str, identificatore: int, giorni: int = 1) -> str:
    """Disfà un'azione decisa dal modello (§8.1).

    L'argomento impacchetta i tre dati che servono a tornare indietro; il
    separatore è `-` perché `:` è già quello dei campi.
    """
    return Azione("x", "annulla", f"{azione_assistente}-{identificatore}-{giorni}", "task").dato()


def leggi_annulla(argomento: str) -> tuple[str, int, int]:
    """Scompone l'argomento di `annulla`. Solleva `AzioneNonValida` se è rotto."""
    pezzi = argomento.rsplit("-", 2)
    if len(pezzi) != 3:
        raise AzioneNonValida(argomento)
    nome, identificatore, giorni = pezzi
    try:
        return nome, int(identificatore), int(giorni)
    except ValueError as errore:
        raise AzioneNonValida(argomento) from errore
