#!/usr/bin/env bash
#
# Keep the Oracle server on the latest `main`, as a read-only mirror.
#
# Run by ati-lab-update.timer (installed by install-updater.sh) every 6 hours.
# Cheap when nothing changed: one `git fetch`, no rebuild. When main moved it
# rebuilds and restarts the containers; the database lives in a Docker volume
# and the settings in deploy/oracle/.env (untracked), so neither is touched.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ati-lab}"
ENV_FILE="$APP_DIR/deploy/oracle/.env"
COMPOSE=(docker compose -f "$APP_DIR/deploy/oracle/docker-compose.yml" --env-file "$ENV_FILE")
cd "$APP_DIR"

# Mirror settings (see deploy/oracle/README.md): the GitHub jobs own the data
# and the Dhan login; this server follows them. Added once to an existing .env.
changed_env=0
# SITE_HOST: a public name for this server's IP (1.2.3.4 -> 1-2-3-4.sslip.io),
# which gives Caddy a free HTTPS certificate. Derived from PUBLIC_URL.
ip="$(grep -E '^PUBLIC_URL=' "$ENV_FILE" | head -1 | sed -E 's#^PUBLIC_URL=https?://##; s#[/:].*$##')"
site_host=""
if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  site_host="${ip//./-}.sslip.io"
fi
for kv in BACKUP_READONLY=1 MIRROR_REFRESH_MINUTES=10 DHAN_YIELD_TO_JOBS=1 ${site_host:+SITE_HOST=$site_host}; do
  key="${kv%%=*}"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    echo "$kv" >> "$ENV_FILE"
    changed_env=1
  fi
done

# Daily database snapshots on this server's disk (snapshot.sh), at the lowest
# CPU and disk priority so the app never waits on them. Installed or refreshed
# here, before the up-to-date check, so every server gets it within one update
# cycle without a manual step.
install_snapshot_timer() {
  local unit=/etc/systemd/system/ati-lab-snapshot.service
  local want
  want="[Unit]
Description=Daily ATI Lab database snapshot (third copy, on this disk)
After=docker.service

[Service]
Type=oneshot
ExecStart=$APP_DIR/deploy/oracle/snapshot.sh
Nice=19
IOSchedulingClass=idle
CPUQuota=50%"
  if [ "$(cat "$unit" 2>/dev/null)" != "$want" ]; then
    printf '%s\n' "$want" > "$unit"
    cat > /etc/systemd/system/ati-lab-snapshot.timer <<'UNIT'
[Unit]
Description=Daily ATI Lab database snapshot at 03:00 IST

[Timer]
OnCalendar=*-*-* 21:30:00 UTC
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
UNIT
    chmod +x "$APP_DIR/deploy/oracle/snapshot.sh"
    systemctl daemon-reload
    systemctl enable --now ati-lab-snapshot.timer
    echo "$(date -u +%FT%TZ) daily snapshot timer installed"
  fi
}
install_snapshot_timer || echo "$(date -u +%FT%TZ) could not install the snapshot timer"

# HTTPS: Oracle's Ubuntu image rejects everything but SSH and the port 80 that
# cloud-init.sh opened. Open 443 the same way, once, and persist it.
if ! iptables -C INPUT -p tcp --dport 443 -m state --state NEW -j ACCEPT 2>/dev/null; then
  reject_at="$(iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')"
  iptables -I INPUT "${reject_at:-1}" -p tcp --dport 443 -m state --state NEW -j ACCEPT
  netfilter-persistent save >/dev/null 2>&1 || true
  echo "$(date -u +%FT%TZ) opened port 443 for HTTPS"
fi

# Fetch with the backup token when there is one, so the update keeps working if
# the repository is made private; the token is used for this call only and is
# never written into .git/config.
token="$(grep -E '^GH_BACKUP_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
repo_url="$(git remote get-url origin)"
if [ -n "$token" ] && [[ "$repo_url" == https://github.com/* ]]; then
  git fetch --quiet "https://x-access-token:${token}@${repo_url#https://}" main:refs/remotes/origin/main
else
  git fetch --quiet origin main
fi
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && [ "$changed_env" = 0 ] \
   && [ "${1:-}" != "--force" ]; then
  echo "$(date -u +%FT%TZ) up to date at $(git rev-parse --short HEAD)"
  exit 0
fi

git checkout --quiet -B main origin/main
git reset --quiet --hard origin/main
echo "$(date -u +%FT%TZ) updating to $(git rev-parse --short HEAD)"
"${COMPOSE[@]}" up -d --build
# The Caddyfile is a mounted file: a change to it alone does not recreate the
# container, so reload it every update (a no-op when nothing changed).
"${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
# Old image layers pile up with every rebuild; the boot disk is only ~47 GB.
docker image prune -f >/dev/null
echo "$(date -u +%FT%TZ) running $(git rev-parse --short HEAD)"
