#!/usr/bin/env bash
#
# Keep the Oracle server on the latest `main`, as a read-only mirror.
#
# Run by ati-lab-update.timer (installed by install-updater.sh) every 15 minutes.
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

# Check for new code every 15 minutes, not every 6 hours: a fix pushed to main
# reached the server up to 6 hours late. The check is one `git fetch`.
# (Servers installed with the older 6-hour timer get this one here.)
install_update_timer() {
  local unit=/etc/systemd/system/ati-lab-update.timer want
  want="[Unit]
Description=Check GitHub for ATI Lab updates every 15 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=15min
RandomizedDelaySec=1min
Persistent=true

[Install]
WantedBy=timers.target"
  if [ "$(cat "$unit" 2>/dev/null)" != "$want" ]; then
    printf '%s\n' "$want" > "$unit"
    systemctl daemon-reload
    systemctl restart ati-lab-update.timer
    echo "$(date -u +%FT%TZ) update timer set to every 15 minutes"
  fi
}
install_update_timer || echo "$(date -u +%FT%TZ) could not change the update timer"

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

# The server's daily work (daily-work.sh): an NSE Top 2000 scan at 09:20,
# 12:30 and 15:10 IST on weekdays, and a two-year backtest of every strategy
# every night at 02:00 IST. Reports at /reports/. Written only when changed.
install_daily_work_timers() {
  local changed=0 name want
  for name in scan research trend; do
    want="[Unit]
Description=ATI Lab daily work: $name
After=docker.service

[Service]
Type=oneshot
ExecStart=$APP_DIR/deploy/oracle/daily-work.sh $name
TimeoutStartSec=3h"
    if [ "$(cat /etc/systemd/system/ati-lab-$name.service 2>/dev/null)" != "$want" ]; then
      printf '%s\n' "$want" > "/etc/systemd/system/ati-lab-$name.service"
      changed=1
    fi
  done
  local scan_timer research_timer
  scan_timer="[Unit]
Description=NSE Top 2000 scan at 09:20, 12:30 and 15:10 IST on weekdays

[Timer]
OnCalendar=Mon..Fri *-*-* 03:50:00 UTC
OnCalendar=Mon..Fri *-*-* 07:00:00 UTC
OnCalendar=Mon..Fri *-*-* 09:40:00 UTC

[Install]
WantedBy=timers.target"
  # Four runs a day, not one: Oracle reclaims an Always Free server whose
  # 95th-percentile CPU stays under 20% for 7 days, and one ~35-minute nightly
  # run (plus 6 minutes of scans) is under 5% of the time. Four put the server
  # at real work about 10% of the day, at the lowest priority.
  research_timer="[Unit]
Description=Two-year backtest of every strategy at 02:00, 08:00, 14:00 and 20:00 IST

[Timer]
OnCalendar=*-*-* 20:30:00 UTC
OnCalendar=*-*-* 02:30:00 UTC
OnCalendar=*-*-* 08:30:00 UTC
OnCalendar=*-*-* 14:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target"
  local trend_timer
  trend_timer="[Unit]
Description=4h trend paper book and phone alerts (crypto and gold perpetuals), every 5 minutes

[Timer]
OnCalendar=*-*-* *:01/5:00 UTC

[Install]
WantedBy=timers.target"
  if [ "$(cat /etc/systemd/system/ati-lab-trend.timer 2>/dev/null)" != "$trend_timer" ]; then
    printf '%s\n' "$trend_timer" > /etc/systemd/system/ati-lab-trend.timer; changed=1
  fi
  if [ "$(cat /etc/systemd/system/ati-lab-scan.timer 2>/dev/null)" != "$scan_timer" ]; then
    printf '%s\n' "$scan_timer" > /etc/systemd/system/ati-lab-scan.timer; changed=1
  fi
  if [ "$(cat /etc/systemd/system/ati-lab-research.timer 2>/dev/null)" != "$research_timer" ]; then
    printf '%s\n' "$research_timer" > /etc/systemd/system/ati-lab-research.timer; changed=1
  fi
  if [ "$changed" = 1 ]; then
    chmod +x "$APP_DIR/deploy/oracle/daily-work.sh"
    systemctl daemon-reload
    systemctl enable --now ati-lab-scan.timer ati-lab-research.timer ati-lab-trend.timer
    echo "$(date -u +%FT%TZ) daily work timers installed"
  fi
}
install_daily_work_timers || echo "$(date -u +%FT%TZ) could not install the daily work timers"

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
# Compared with the last commit that built and started, not with HEAD: HEAD
# moves before the build, so a failed build would otherwise never be retried.
DEPLOYED_FILE=/var/lib/ati-lab/deployed-commit
if [ "$(cat "$DEPLOYED_FILE" 2>/dev/null)" = "$(git rev-parse origin/main)" ] && [ "$changed_env" = 0 ] \
   && [ "${1:-}" != "--force" ]; then
  echo "$(date -u +%FT%TZ) up to date at $(git rev-parse --short HEAD)"
  exit 0
fi

before="$(git rev-parse --verify -q HEAD:deploy/oracle/update.sh || true)"
git checkout --quiet -B main origin/main
git reset --quiet --hard origin/main
# This script just changed: run the new copy, so its timers and settings apply
# now and not one (formerly 6-hour) cycle later. Once only.
if [ -z "${ATI_UPDATE_REEXEC:-}" ] && [ "$before" != "$(git rev-parse HEAD:deploy/oracle/update.sh)" ]; then
  echo "$(date -u +%FT%TZ) update.sh changed, running the new copy"
  ATI_UPDATE_REEXEC=1 exec bash "$APP_DIR/deploy/oracle/update.sh" "$@"
fi
echo "$(date -u +%FT%TZ) updating to $(git rev-parse --short HEAD)"
"${COMPOSE[@]}" up -d --build
# The Caddyfile is a mounted file: a change to it alone does not recreate the
# container, so reload it every update (a no-op when nothing changed).
"${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
# Old image layers pile up with every rebuild; the boot disk is only ~47 GB.
docker image prune -f >/dev/null
mkdir -p "$(dirname "$DEPLOYED_FILE")"
git rev-parse HEAD > "$DEPLOYED_FILE"
echo "$(date -u +%FT%TZ) running $(git rev-parse --short HEAD)"
