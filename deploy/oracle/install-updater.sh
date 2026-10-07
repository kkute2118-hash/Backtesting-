#!/usr/bin/env bash
#
# Install the self-update (every 15 minutes) (update.sh) as a systemd timer, then run it
# once. Safe to re-run. On a server created before this existed, run once:
#
#   sudo bash -c 'cd /opt/ati-lab && git fetch origin main && git checkout -B main origin/main && bash deploy/oracle/install-updater.sh'
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/ati-lab}"
chmod +x "$APP_DIR/deploy/oracle/update.sh"

cat > /etc/systemd/system/ati-lab-update.service <<UNIT
[Unit]
Description=Update ATI Lab from GitHub main and rebuild if it changed
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=APP_DIR=$APP_DIR
ExecStart=$APP_DIR/deploy/oracle/update.sh
UNIT

cat > /etc/systemd/system/ati-lab-update.timer <<'UNIT'
[Unit]
Description=Check GitHub for ATI Lab updates every 15 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=15min
RandomizedDelaySec=1min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now ati-lab-update.timer
systemctl start ati-lab-update.service
systemctl --no-pager status ati-lab-update.service | tail -5 || true
