# Immagini dei servizi di Custode: un solo file, un target per servizio, così
# la base (Python, uv, dipendenze bloccate) è pinnata in un posto solo.
# Immagini pinnate per versione, mai `:latest` (ARCHITECTURE.md §9).
# Il tag `slim-bookworm` copre sia x86_64 (sviluppo) sia arm64 (Raspberry Pi 5).
FROM python:3.12.8-slim-bookworm AS base

# uv installato copiando il binario dall'immagine ufficiale, anch'essa pinnata.
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Prima solo i file di dipendenze: finché non cambiano, il layer pesante resta
# in cache anche quando cambia il codice.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --all-extras

COPY core/ core/
COPY api/ api/
COPY bot/ bot/
RUN uv sync --frozen --no-dev --all-extras

# Utente non-root (§9), proprietario di /data così può scrivere sul volume.
RUN useradd --create-home --uid 10001 custode \
    && mkdir -p /data \
    && chown -R custode:custode /data /app

ENV CUSTODE_DB_PATH=/data/custode.db


# — api: il backend che serve la dashboard ————————————————
FROM base AS api

USER custode
EXPOSE 8000

# Health check senza dipendenze extra: python è già nell'immagine, curl no.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health').read()"]

CMD ["uvicorn", "custode_api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# — bot: il canale Telegram, in long polling —————————————
# Nessuna porta esposta: è il bot a chiamare Telegram, mai il contrario (§9).
FROM base AS bot

USER custode

CMD ["python", "-m", "custode_bot.main"]


# — test: stessa base, più le dipendenze di sviluppo e i test —————
# Usato da docker-compose.test.yml (§10).
FROM base AS test

RUN uv sync --frozen --all-extras
COPY tests/ tests/

ENV CUSTODE_AMBIENTE=test \
    CUSTODE_DB_PATH=/tmp/custode-test.db

CMD ["pytest"]
