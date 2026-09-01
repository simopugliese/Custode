"""Configurazione del router: chiavi, modelli, limiti.

Prefisso `ROUTER_` per le variabili d'ambiente. Le chiavi non hanno default:
restano vuote finché non le fornisce l'ambiente, e un provider senza chiave
viene segnalato con un errore comprensibile invece di fallire in rete (§9).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ImpostazioniRouter(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ROUTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_modello: str = "deepseek-chat"

    anthropic_api_key: str = ""
    claude_modello: str = "claude-opus-5"
    claude_effort: str = "high"
    """Profondità di ragionamento di Claude: low | medium | high | xhigh | max."""

    timeout_secondi: float = 30.0
    """Un comando dal telefono non può restare appeso: meglio un errore chiaro."""

    max_token_risposta: int = 1024
    """Le risposte di DeepSeek sono JSON strutturati brevi, non testi lunghi."""

    max_token_risposta_claude: int = 8000
    """Perché Claude ha un tetto suo, molto più alto.

    Su `claude-opus-5` il ragionamento adattivo è attivo per impostazione
    predefinita e i suoi token **rientrano in `max_tokens`**: un tetto da 1024,
    che a DeepSeek basta e avanza, qui verrebbe consumato dal ragionamento e la
    risposta arriverebbe troncata (`stop_reason: "max_tokens"`) invece che in
    JSON. Finché nessun modulo chiamava Claude il problema non si vedeva; il
    diario (§8.4) è il primo che lo farebbe scattare.
    """


@lru_cache(maxsize=1)
def get_impostazioni_router() -> ImpostazioniRouter:
    return ImpostazioniRouter()
