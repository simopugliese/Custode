"""Rotte dei moduli non ancora costruiti.

Rispondono `501 Not Implemented` dicendo quale modulo manca, invece di dare
404 muti o payload vuoti: la dashboard mostra il suo stato d'errore col motivo
scritto dentro, e "il modulo non c'è ancora" resta distinguibile da "non hai
ancora niente". Ogni gruppo sparisce da qui quando arriva il suo modulo.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["non ancora attivi"])

# Percorso → (metodi, modulo mancante, fase del piano di lavoro)
MODULI: dict[str, tuple[list[str], str, str]] = {
    "/api/diario": (["GET"], "diario", "§8.4"),
    "/api/diario/{voce_id}/approva": (["POST"], "diario", "§8.4"),
    "/api/diario/{voce_id}/scarta": (["POST"], "diario", "§8.4"),
    "/api/lezioni": (["GET"], "lezioni e corsi", "§8.11"),
    "/api/lezioni/piani/{piano_id}/rigenera": (["POST"], "lezioni e corsi", "§8.11"),
    "/api/lezioni/piani/{piano_id}/manda-al-bot": (["POST"], "lezioni e corsi", "§8.11"),
    "/api/spese": (["GET", "POST"], "spese", "§8.5"),
    "/api/spese/{spesa_id}/conferma": (["POST"], "spese", "§8.5"),
    "/api/abitudini": (["GET"], "abitudini", "§8.6"),
    "/api/abitudini/{abitudine_id}/log": (["PATCH"], "abitudini", "§8.6"),
    "/api/abitudini/{abitudine_id}/proposta/accetta": (["POST"], "abitudini", "§8.6"),
    "/api/abitudini/{abitudine_id}/proposta/rifiuta": (["POST"], "abitudini", "§8.6"),
    "/api/regole": (["GET"], "regole di contesto", "§8.10"),
    "/api/regole/{regola_id}": (["PATCH"], "regole di contesto", "§8.10"),
    "/api/regole/{regola_id}/approva": (["POST"], "regole di contesto", "§8.10"),
    "/api/regole/{regola_id}/scarta": (["POST"], "regole di contesto", "§8.10"),
    "/api/impostazioni": (["GET", "PATCH"], "impostazioni", "§8"),
}


def _registra(percorso: str, metodi: list[str], modulo: str, riferimento: str) -> None:
    async def non_attivo() -> None:
        raise HTTPException(
            status_code=501,
            detail=f"Il modulo «{modulo}» non è ancora attivo ({riferimento}).",
        )

    router.add_api_route(
        percorso,
        non_attivo,
        methods=metodi,
        include_in_schema=False,
        name=f"non_attivo:{percorso}",
    )


for _percorso, (_metodi, _modulo, _riferimento) in MODULI.items():
    _registra(_percorso, _metodi, _modulo, _riferimento)
