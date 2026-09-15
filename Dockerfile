# Immagini dei servizi di Custode: un solo file, un target per servizio, così
# la base (Python, uv, dipendenze comuni) è pinnata in un posto solo.
# Immagini pinnate per versione, mai `:latest` (ARCHITECTURE.md §9).
# Il tag `slim-bookworm` copre sia x86_64 (sviluppo) sia arm64 (Raspberry Pi 5).
#
# **Tre strati, dal più stabile al più volatile**, ed è la ragione per cui
# `base` non contiene il codice: `docker compose up --build` ricostruisce ogni
# layer che sta *sotto* a qualcosa di cambiato, quindi tutto ciò che sta dopo
# la copia del codice si rifà ad ogni modifica. Con whisper.cpp — che si
# compila da sorgente — quello voleva dire quattro minuti per cambiare una
# riga di Python. Qui il codice entra il più tardi possibile:
#
#   base        python + uv + utente        cambia quasi mai
#   dipendenze  pyproject.toml + uv.lock    cambia quando cambiano le librerie
#   progetto    il codice                   cambia ogni volta
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

# Utente non-root (§9) e la cartella del volume. Stanno qui, e non dopo il
# codice, perché non dipendono da niente del progetto: creare un utente non è
# un'operazione da rifare ogni volta che cambia una riga.
RUN useradd --create-home --uid 10001 custode \
    && mkdir -p /data \
    && chown custode:custode /data

ENV CUSTODE_DB_PATH=/data/custode.db


# — dipendenze: il layer pesante, che cambia solo con uv.lock ————
# Qui vanno solo le dipendenze comuni; ogni servizio aggiunge il proprio extra
# nel suo target, così l'immagine dell'API non si porta dietro
# python-telegram-bot e viceversa.
FROM base AS dipendenze

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev


# — progetto: il codice, e l'installazione del pacchetto ————————
FROM dipendenze AS progetto

# `--chown` sulla copia e non un `chown -R` dopo: `chown -R` riscrive il
# proprietario di ogni file, e Docker registra quel cambiamento come uno strato
# nuovo che contiene **un'altra copia** dell'albero dei sorgenti. Passandolo
# alla COPY i file nascono già dell'utente giusto e l'albero sta nell'immagine
# una volta sola. È lo stesso motivo per cui il `chown` di `/data` sta in
# `base`, dove la cartella viene creata.
COPY --chown=custode:custode core/ core/
COPY --chown=custode:custode api/ api/
COPY --chown=custode:custode bot/ bot/
COPY --chown=custode:custode README.md .
COPY --chown=custode:custode router/ router/
COPY --chown=custode:custode whisper/ whisper/
COPY --chown=custode:custode worker/ worker/
COPY --chown=custode:custode calendario/ calendario/
RUN uv sync --frozen --no-dev


# — api: il backend che serve la dashboard ————————————————
FROM progetto AS api

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
FROM progetto AS bot

RUN uv sync --frozen --no-dev --extra bot --extra router
RUN chown -R custode:custode /opt/venv
USER custode

CMD ["python", "-m", "custode_bot.main"]


# — worker: i job schedulati (§5, §8.4) ————————————————————
# Nessuna porta esposta: il worker parla col database e con Telegram, e verso
# Telegram è lui a chiamare. Gli basta l'extra `router` (Claude per il riepilogo
# settimanale) più `worker` (httpx per mandare il messaggio): `python-telegram-bot`
# resta fuori, perché qui si spedisce e basta — i tap sui bottoni li riceve il bot.
FROM progetto AS worker

RUN uv sync --frozen --no-dev --extra router --extra worker --extra calendario
RUN chown -R custode:custode /opt/venv
USER custode

CMD ["python", "-m", "custode_worker.main"]


# — whisper: trascrizione locale (§4, §13) ————————————————
# whisper.cpp si compila qui: il binario finisce nell'immagine finale senza
# portarsi dietro il compilatore.
#
# **`FROM base` e non `FROM progetto`**: questo stage non usa una riga del
# progetto, e farlo dipendere dal codice vorrebbe dire ricompilare whisper.cpp
# da sorgente ad ogni modifica — quattro minuti per niente, ad ogni
# `docker compose up --build`. Da qui in giù si ricostruisce solo quando
# cambiano `WHISPER_VERSION` o `WHISPER_MODEL`.
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


# Parte da `dipendenze` e non da `progetto` per la stessa ragione: così
# l'installazione di ffmpeg — una cinquantina di megabyte di pacchetti — e la
# copia del binario di whisper restano in cache quando cambia il codice. Il
# codice arriva dopo, dallo stage che l'ha già installato una volta.
FROM dipendenze AS whisper

# ffmpeg converte i vocali OGG/Opus di Telegram in WAV 16 kHz mono.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=whisper-build /opt/whisper /opt/whisper
# Niente `--chown` qui e niente `/app` nel `chown` sotto: una COPY da un altro
# stage porta con sé il proprietario che i file hanno là, e là sono già di
# `custode`. Rifarlo costerebbe una seconda copia dell'albero in questa
# immagine, che è la più grossa delle quattro.
COPY --from=progetto /app /app

RUN uv sync --frozen --no-dev --extra whisper
RUN chown -R custode:custode /opt/venv /opt/whisper
USER custode
EXPOSE 8100

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8100/health').read()"]

CMD ["uvicorn", "custode_whisper.main:app", "--host", "0.0.0.0", "--port", "8100"]


# — test: stessa base, più le dipendenze di sviluppo e i test —————
# Usato da docker-compose.test.yml (§10).
FROM progetto AS test

RUN uv sync --frozen --all-extras
COPY tests/ tests/

ENV CUSTODE_AMBIENTE=test \
    CUSTODE_DB_PATH=/tmp/custode-test.db

CMD ["pytest"]
