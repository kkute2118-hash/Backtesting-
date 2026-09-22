#!/usr/bin/env bash
# Build and (re)start everything. Safe to run repeatedly - this is also how
# you ship a change:
#
#     sudo bash /opt/ati-lab/deploy/oracle/deploy.sh
#
# Order matters. The frontend is built BEFORE anything is restarted, so a
# build that fails leaves the currently running version serving traffic
# instead of taking the site down and then failing.

set -euo pipefail

APP_USER="${APP_USER:-ubuntu}"
APP_DIR="${APP_DIR:-/opt/ati-lab}"
DATA_DIR="${DATA_DIR:-/var/lib/ati-lab}"
BRANCH="${BRANCH:-main}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo." >&2; exit 1
fi

if [ ! -s /etc/ati-lab/env ]; then
  echo "/etc/ati-lab/env is missing or empty. Fill it in first." >&2; exit 1
fi
# Presence only. The value is never printed.
if ! grep -q '^API_ACCESS_KEY=.\+' /etc/ati-lab/env; then
  echo "API_ACCESS_KEY is not set in /etc/ati-lab/env." >&2
  echo "Generate one with: openssl rand -hex 32" >&2
  exit 1
fi

echo "==> Pulling $BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" checkout --quiet "$BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"

echo "==> Python dependencies"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

echo "==> Frontend build (before any restart, so a failure changes nothing)"
sudo -u "$APP_USER" env -C "$APP_DIR/frontend" npm ci --silent
# NEXT_PUBLIC_* values are inlined at BUILD time, so the build has to see them.
# Reading them at runtime only would bake in whatever was set when the image
# was made - which is exactly the bug the gateway route documents.
#
# ONE variable is extracted, rather than sourcing the file. Two reasons, and
# both bite:
#   - the file is systemd EnvironmentFile format, not shell. A value like
#     SCAN_UNIVERSE=NSE All Cash (~2000) is valid there and a syntax error in
#     bash, so `. /etc/ati-lab/env` would abort the deploy;
#   - sourcing would put DHAN_PIN and the rest into the npm build's
#     environment, where a postinstall script could read them. The frontend
#     build has no business seeing a broker credential.
PUBLIC_API_URL="$(sed -n 's/^NEXT_PUBLIC_API_URL=//p' /etc/ati-lab/env | tail -1 \
                  | sed -e 's/^"//' -e "s/^'//" -e 's/"$//' -e "s/'$//")"
if [ -z "$PUBLIC_API_URL" ]; then
  echo "NEXT_PUBLIC_API_URL is not set in /etc/ati-lab/env." >&2
  echo "It must be the public https:// hostname, with no trailing slash." >&2
  exit 1
fi
echo "    building against $PUBLIC_API_URL"
sudo -u "$APP_USER" env -C "$APP_DIR/frontend" \
  NEXT_PUBLIC_API_URL="$PUBLIC_API_URL" npm run build

echo "==> Restoring the database if this box has none"
# A first deploy on a fresh instance starts with an empty store. The engine's
# own restore path pulls the last backup rather than making you rebuild five
# years of candles by hand. It declines when real rows are already present, so
# this is safe on every later deploy too.
sudo -u "$APP_USER" env -C "$APP_DIR/backend" GTF_DATA_DIR="$DATA_DIR" \
  "$APP_DIR/.venv/bin/python" -c "
from app.engine import core
if core.restore_db_from_github():
    print('    restored from the GitHub backup')
else:
    print('    nothing restored (local store already has rows, or no backup configured)')
" || echo "    restore skipped"

echo "==> Services"
systemctl enable --quiet --now ati-lab-api.service
systemctl enable --quiet --now ati-lab-web.service
systemctl enable --quiet --now ati-lab-daily.timer
systemctl enable --quiet --now ati-lab-token.timer
systemctl restart ati-lab-api.service
systemctl restart ati-lab-web.service
systemctl reload caddy 2>/dev/null || systemctl restart caddy

sleep 4
echo
echo "==> Health"
for name in ati-lab-api ati-lab-web caddy; do
  printf '  %-14s %s\n' "$name" "$(systemctl is-active "$name" 2>/dev/null || echo inactive)"
done
printf '  %-14s ' "API /health"
curl -fsS --max-time 10 http://127.0.0.1:8000/health >/dev/null 2>&1 && echo ok || echo "NOT RESPONDING"
printf '  %-14s ' "web"
curl -fsS --max-time 10 http://127.0.0.1:3000/health >/dev/null 2>&1 && echo ok || echo "NOT RESPONDING"
echo
echo "  Timers:"
systemctl list-timers --no-pager 'ati-lab-*' | sed 's/^/    /' || true
echo
echo "  Logs:  journalctl -u ati-lab-api -f"
