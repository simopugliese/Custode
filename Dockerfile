# Immagini dei servizi di Custode: un solo file, un target per servizio, così
# la base (Python, uv, dipendenze comuni) è pinnata in un posto solo.
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
# in cache anche quando cambia il codice. Qui vanno solo le dipendenze comuni;
# ogni servizio aggiunge il proprio extra nel suo target, così l'immagine
# dell'API non si porta dietro python-telegram-bot e viceversa.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY core/ core/
COPY api/ api/
COPY bot/ bot/
COPY README.md .
COPY router/ router/
COPY whisper/ whisper/
COPY worker/ worker/
RUN uv sync --frozen --no-dev

# Utente non-root (§9), proprietario di /data così può scrivere sul volume.
RUN useradd --create-home --uid 10001 custode \
    && mkdir -p /data \
    && chown -R custode:custode /data /app

ENV CUSTODE_DB_PATH=/data/custode.db


# — api: il backend che serve la dashboard ————————————————
FROM base AS api

RUN uv sync --frozen --no-dev --extra router
RUN chown -R custode:custode /opt/venv
USER custode
EXPOSE 8000

# Health check senza dipendenze extra: python è già nell'immagine, curl no.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health').read()"]

CMD ["uvicorn", "custode_api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# — bot: il canale Telegram, in long polling —————————————
# Nessuna porta esposta: è il bot a chiamare Telegram, mai il contrario (§9).
FROM base AS bot

RUN uv sync --frozen --no-dev --extra bot --extra router
RUN chown -R custode:custode /opt/venv
USER custode

CMD ["python", "-m", "custode_bot.main"]


# — worker: i job schedulati (§5, §8.4) ————————————————————
# Nessuna porta esposta: il worker parla col database e con Telegram, e verso
# Telegram è lui a chiamare. Gli basta l'extra `router` (Claude per il riepilogo
# settimanale) più `worker` (httpx per mandare il messaggio): `python-telegram-bot`
# resta fuori, perché qui si spedisce e basta — i tap sui bottoni li riceve il bot.
FROM base AS worker

RUN uv sync --frozen --no-dev --extra router --extra worker
RUN chown -R custode:custode /opt/venv
USER custode

CMD ["python", "-m", "custode_worker.main"]


# — whisper: trascrizione locale (§4, §13) ————————————————
# whisper.cpp si compila qui: il binario finisce nell'immagine finale senza
# portarsi dietro il compilatore.
FROM base AS whisper-build

ARG WHISPER_VERSION=v1.7.4
ARG WHISPER_MODEL=base-q5_1

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential cmake git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${WHISPER_VERSION}" \
        https://github.com/ggml-org/whisper.cpp /tmp/whisper.cpp \
    && cmake -S /tmp/whisper.cpp -B /tmp/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    && cmake --build /tmp/whisper.cpp/build --target whisper-cli -j "$(nproc)" \
    && mkdir -p /opt/whisper/models \
    && cp /tmp/whisper.cpp/build/bin/whisper-cli /opt/whisper/whisper-cli \
    && /tmp/whisper.cpp/models/download-ggml-model.sh "${WHISPER_MODEL}" /opt/whisper/models \
    && rm -rf /tmp/whisper.cpp


FROM base AS whisper

# ffmpeg converte i vocali OGG/Opus di Telegram in WAV 16 kHz mono.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=whisper-build /opt/whisper /opt/whisper

RUN uv sync --frozen --no-dev --extra whisper
RUN chown -R custode:custode /opt/venv /opt/whisper
USER custode
EXPOSE 8100

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8100/health').read()"]

CMD ["uvicorn", "custode_whisper.main:app", "--host", "0.0.0.0", "--port", "8100"]


# — test: stessa base, più le dipendenze di sviluppo e i test —————
# Usato da docker-compose.test.yml (§10).
FROM base AS test

RUN uv sync --frozen --all-extras
COPY tests/ tests/

ENV CUSTODE_AMBIENTE=test \
    CUSTODE_DB_PATH=/tmp/custode-test.db

CMD ["pytest"]
