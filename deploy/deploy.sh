#!/usr/bin/env bash
# Aggiorna il Pi all'ultimo `origin/main`, ma solo se la CI è tutta verde, e
# torna indietro se il nuovo non sta in piedi (ARCHITECTURE.md §10, DEPLOY.md §6).
#
# Lo chiama il listener quando la CI lo avvisa, ma si lancia anche a mano:
#
#     sudo bash deploy/deploy.sh
#
# Exit code (li legge custode_deploy/listener.py, STATI_PER_CODICE):
#    0  fatto: il nuovo è su e /api/health risponde
#   10  rifiutato: la CI di quel commit non è tutta verde, non è stato toccato nulla
#   11  rollback: il nuovo non rispondeva, è tornato il commit di prima (ora sta su)
#   12  da guardare a mano: è cambiata una migrazione, oppure anche il rollback fallisce
#    1  altro: fetch o merge non riusciti, ecc.
#
# Tutto il corpo sta in `main` e l'unica riga eseguita fuori è l'ultima: bash
# legge lo script a pezzi mentre lo esegue, e `git merge` può riscrivere questo
# stesso file nel mezzo. Così bash lo ha già letto tutto prima di cominciare.

set -u -o pipefail

dire() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }

# Legge una chiave dal .env senza fare `source`: un valore con spazi o `$` lì
# dentro non deve diventare un comando.
valore_env() {
  grep -E "^$1=" "$DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" || true
}

# Una riga su Telegram. Non riuscirci non è un motivo per fallire il deploy.
notifica() {
  local token chat
  token=$(valore_env TELEGRAM_BOT_TOKEN)
  chat=$(valore_env TELEGRAM_ALLOWED_USER_ID)
  [ -n "$token" ] && [ -n "$chat" ] || return 0
  curl -s --max-time 10 -o /dev/null \
    --data-urlencode "chat_id=$chat" --data-urlencode "text=$1" \
    "https://api.telegram.org/bot$token/sendMessage" || true
}

# Stampa l'esito (ultima riga: la legge il listener), avvisa, esce con `$1`.
chiudi() {
  local codice=$1 messaggio=$2
  dire "$messaggio"
  notifica "Custode · $messaggio"
  return "$codice"
}

# L'API risponde 200 su /api/health? Riprova per un po': dopo `up` ci vuole il
# tempo della migrazione e dell'avvio.
sta_in_piedi() {
  local tentativo
  for ((tentativo = 1; tentativo <= SMOKE_TENTATIVI; tentativo++)); do
    if curl -sf --max-time 5 "$HEALTH_URL" >/dev/null; then
      return 0
    fi
    sleep "$SMOKE_PAUSA"
  done
  return 1
}

main() {
  DIR=${CUSTODE_DEPLOY_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
  HEALTH_URL=${CUSTODE_DEPLOY_HEALTH_URL:-http://127.0.0.1:8000/api/health}
  SMOKE_TENTATIVI=${CUSTODE_DEPLOY_SMOKE_TENTATIVI:-18}
  SMOKE_PAUSA=${CUSTODE_DEPLOY_SMOKE_PAUSA:-5}
  local remoto=${CUSTODE_DEPLOY_REMOTO:-origin/main}

  cd "$DIR" || return 1
  local prima nuovo
  prima=$(git rev-parse HEAD) || return 1

  dire "recupero $remoto"
  git fetch --quiet origin || { chiudi 1 "Deploy non riuscito: git fetch fallito"; return; }
  nuovo=$(git rev-parse "$remoto") || { chiudi 1 "Deploy non riuscito: $remoto non esiste"; return; }

  # Il Pi non si fida di chi lo ha chiamato: chiede a GitHub com'è andata la CI.
  local motivo
  if [ -n "${CUSTODE_DEPLOY_CI_CMD:-}" ]; then
    motivo=$("$CUSTODE_DEPLOY_CI_CMD" "$nuovo" 2>&1)
  else
    motivo=$(PYTHONPATH="$DIR/deploy" python3 -m custode_deploy.ci "$nuovo" 2>&1)
  fi || { chiudi 10 "Deploy rifiutato (${nuovo:0:7}): $motivo"; return; }
  dire "CI: $motivo"

  # Se tra il commit di prima e il nuovo cambia una migrazione, il codice di
  # prima potrebbe non reggere lo schema nuovo: in quel caso non si torna
  # indietro da soli.
  local migrazioni_toccate=0
  git diff --quiet "$prima" "$nuovo" -- core/custode_core/migrazioni/ || migrazioni_toccate=1

  git merge --ff-only --quiet "$nuovo" ||
    { chiudi 1 "Deploy non riuscito: il merge non è un fast-forward (modifiche locali sul Pi?)"; return; }

  dire "docker compose up --build -d (${prima:0:7} → ${nuovo:0:7})"
  if docker compose up --build -d && sta_in_piedi; then
    chiudi 0 "Deploy ok: ${nuovo:0:7} in esecuzione"
    return
  fi

  if [ "$migrazioni_toccate" = 1 ]; then
    chiudi 12 "Deploy FALLITO su ${nuovo:0:7}, e c'è una migrazione nuova: NON sono tornato indietro. Guarda a mano (DEPLOY.md §6)"
    return
  fi

  dire "il nuovo non risponde: torno a ${prima:0:7}"
  git reset --hard --quiet "$prima"
  if docker compose up --build -d && sta_in_piedi; then
    chiudi 11 "Deploy FALLITO su ${nuovo:0:7}: tornato a ${prima:0:7}, che risponde"
  else
    chiudi 12 "Deploy FALLITO su ${nuovo:0:7} e anche il ritorno a ${prima:0:7} non risponde: guarda a mano"
  fi
}

main "$@"
exit $?
