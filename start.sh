#!/usr/bin/env bash
# One command to get the app running on this machine.
#
#     ./start.sh
#
# Installs what is missing, starts both processes, and prints the URL. Safe to
# re-run: everything it does is skipped if it has already been done.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- prerequisites
PYTHON="$(command -v python3.13 || command -v python3.12 || command -v python3.11 \
       || command -v python3 || true)"
[ -n "$PYTHON" ] || fail "Python 3.11 or newer is required. Install it, then re-run."

"$PYTHON" - <<'PY' || fail "Python 3.11 or newer is required; the python3 on PATH is older."
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

command -v node >/dev/null 2>&1 || fail "Node 20 or newer is required. Install it, then re-run."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 20 ] || fail "Node 20 or newer is required; found $(node -v)."

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }
port_busy "$API_PORT" && fail "Port $API_PORT is already in use. Stop what is using it, or run: API_PORT=8001 ./start.sh"
port_busy "$WEB_PORT" && fail "Port $WEB_PORT is already in use. Stop what is using it, or run: WEB_PORT=3001 ./start.sh"

# ------------------------------------------------------------------- backend
cd "$ROOT/backend"

if [ ! -d .venv ]; then
  bold "Creating the Python environment (one time)…"
  "$PYTHON" -m venv .venv
fi
VENV_PY="$ROOT/backend/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/backend/.venv/Scripts/python.exe"   # Git Bash on Windows

if ! "$VENV_PY" -c "import fastapi, pandas" >/dev/null 2>&1; then
  bold "Installing Python dependencies (one time, a few minutes)…"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt
fi

CONFIGURED=1
if [ ! -f .env ]; then
  cp .env.example .env
  CONFIGURED=0
fi
grep -qE '^DHAN_CLIENT_ID=.+' .env || CONFIGURED=0

# -------------------------------------------------------------------- frontend
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  bold "Installing frontend dependencies (one time)…"
  npm install --no-fund --no-audit
fi

# ----------------------------------------------------------------------- run
cd "$ROOT"
mkdir -p .run
API_LOG="$ROOT/.run/api.log"
WEB_LOG="$ROOT/.run/web.log"

cleanup() {
  trap - INT TERM EXIT
  echo
  bold "Stopping…"
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

bold "Starting the API on port $API_PORT…"
( cd "$ROOT/backend" && "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$API_LOG" 2>&1 ) &
API_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/v1/health" >/dev/null 2>&1; then break; fi
  kill -0 "$API_PID" 2>/dev/null || { echo; tail -20 "$API_LOG"; fail "The API failed to start (log above)."; }
  sleep 1
done
curl -fsS "http://127.0.0.1:$API_PORT/api/v1/health" >/dev/null 2>&1 \
  || { tail -20 "$API_LOG"; fail "The API did not become healthy in 60s (log above)."; }

bold "Starting the web app on port $WEB_PORT…"
( cd "$ROOT/frontend" && NEXT_PUBLIC_API_URL="http://127.0.0.1:$API_PORT" \
    npx next dev -p "$WEB_PORT" >"$WEB_LOG" 2>&1 ) &
WEB_PID=$!

for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$WEB_PORT" >/dev/null 2>&1; then break; fi
  kill -0 "$WEB_PID" 2>/dev/null || { echo; tail -20 "$WEB_LOG"; fail "The web app failed to start (log above)."; }
  sleep 1
done

echo
bold "────────────────────────────────────────────────────────"
bold "  Open:  http://localhost:$WEB_PORT"
bold "────────────────────────────────────────────────────────"
echo "  API docs:  http://localhost:$API_PORT/docs"
echo "  Logs:      .run/api.log  .run/web.log"
echo

if [ "$CONFIGURED" -eq 0 ]; then
  warn "Dhan is not configured yet, so the app cannot fetch any market data."
  warn "Add your credentials to backend/.env, then restart this script:"
  warn "    DHAN_CLIENT_ID, plus DHAN_PIN and DHAN_TOTP_SECRET"
  warn "    (or DHAN_ACCESS_TOKEN if you paste a token by hand each day)"
  echo
fi

echo "First run? Open Data Manager and use 'Sync missing history' once to build"
echo "the candle store, then 'Top up latest sessions' each day after that."
echo
echo "Press Ctrl-C to stop both."
wait
