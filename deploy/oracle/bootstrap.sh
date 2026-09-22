#!/usr/bin/env bash
# One-time setup for an Oracle Cloud Always Free A1 instance (Ubuntu 24.04, ARM).
#
# Run ONCE, as the default `ubuntu` user, on a freshly created instance:
#
#     git clone https://github.com/kkute2118-hash/Backtesting-.git /tmp/ati
#     sudo bash /tmp/ati/deploy/oracle/bootstrap.sh
#
# It installs everything, lays out the directories, and leaves the services
# stopped. Fill in /etc/ati-lab/env, then run deploy.sh to start.
#
# Nothing here is Oracle-specific except the iptables rules, which exist
# because Oracle's Ubuntu images ship a firewall that blocks every port but 22
# - opening 80/443 in the console Security List is NOT enough, and that
# mismatch is the single most common reason a first deploy is unreachable.

set -euo pipefail

APP_USER="${APP_USER:-ubuntu}"
APP_DIR="${APP_DIR:-/opt/ati-lab}"
DATA_DIR="${DATA_DIR:-/var/lib/ati-lab}"
REPO="${REPO:-https://github.com/kkute2118-hash/Backtesting-.git}"
BRANCH="${BRANCH:-main}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo." >&2; exit 1
fi
id "$APP_USER" >/dev/null 2>&1 || { echo "No such user: $APP_USER" >&2; exit 1; }

echo "==> Timezone to IST"
# The engine converts to IST internally either way (core.MARKET_TZ), but a box
# on IST makes journalctl timestamps and timer schedules read the same way the
# market does, which removes a whole class of "did it run after the close?"
# confusion.
timedatectl set-timezone Asia/Kolkata

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-dev build-essential \
  git curl ca-certificates gnupg sqlite3 \
  debian-keyring debian-archive-keyring apt-transport-https \
  iptables-persistent

echo "==> Node 20 (for the Next.js frontend)"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> Caddy (TLS certificates, renewed automatically)"
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi

echo "==> Firewall"
# Oracle's image has an INPUT chain that REJECTs by default after a few
# allow rules. Insert before the reject rather than appending, or the rule is
# never reached. -C first so re-running this script does not stack duplicates.
for port in 80 443; do
  if ! iptables -C INPUT -m state --state NEW -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 6 -m state --state NEW -p tcp --dport "$port" -j ACCEPT
  fi
done
netfilter-persistent save >/dev/null

echo "==> Directories"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
install -d -o "$APP_USER" -g "$APP_USER" "$DATA_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 700 /etc/ati-lab

echo "==> Clone"
if [ ! -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git clone --branch "$BRANCH" "$REPO" "$APP_DIR"
fi

echo "==> Python environment"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip wheel
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

echo "==> systemd units"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@APP_USER@|$APP_USER|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
    "$APP_DIR/deploy/oracle/systemd/ati-lab-api.service" > /etc/systemd/system/ati-lab-api.service
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@APP_USER@|$APP_USER|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
    "$APP_DIR/deploy/oracle/systemd/ati-lab-web.service" > /etc/systemd/system/ati-lab-web.service
for unit in ati-lab-daily.service ati-lab-daily.timer ati-lab-token.service ati-lab-token.timer; do
  sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@APP_USER@|$APP_USER|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
      "$APP_DIR/deploy/oracle/systemd/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [ ! -f /etc/ati-lab/env ]; then
  install -o "$APP_USER" -g "$APP_USER" -m 600 \
    "$APP_DIR/deploy/oracle/env.example" /etc/ati-lab/env
  echo
  echo "  Created /etc/ati-lab/env from the template."
fi

cat <<EOF

==> Done. Three things left, in this order:

  1. Fill in the secrets:      sudo -u $APP_USER nano /etc/ati-lab/env
  2. Set your hostname:        sudo nano /etc/caddy/Caddyfile
                               (copy from $APP_DIR/deploy/oracle/Caddyfile)
  3. Build and start:          sudo bash $APP_DIR/deploy/oracle/deploy.sh

Nothing is running yet, and no secret has been printed or logged by this
script.
EOF
