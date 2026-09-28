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
for kv in BACKUP_READONLY=1 MIRROR_REFRESH_MINUTES=10 DHAN_YIELD_TO_JOBS=1; do
  key="${kv%%=*}"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    echo "$kv" >> "$ENV_FILE"
    changed_env=1
  fi
done

git fetch --quiet origin main
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && [ "$changed_env" = 0 ] \
   && [ "${1:-}" != "--force" ]; then
  echo "$(date -u +%FT%TZ) up to date at $(git rev-parse --short HEAD)"
  exit 0
fi

git checkout --quiet -B main origin/main
git reset --quiet --hard origin/main
echo "$(date -u +%FT%TZ) updating to $(git rev-parse --short HEAD)"
"${COMPOSE[@]}" up -d --build
# Old image layers pile up with every rebuild; the boot disk is only ~47 GB.
docker image prune -f >/dev/null
echo "$(date -u +%FT%TZ) running $(git rev-parse --short HEAD)"
