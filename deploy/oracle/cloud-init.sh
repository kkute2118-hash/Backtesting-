#!/bin/bash
# ATI Lab on an Oracle Cloud "Always Free" server, in one paste.
#
# Paste this whole file into "Show advanced options → Management →
# Cloud-init script" when creating the instance (Ubuntu 22.04 or 24.04, the
# Ampere A1 shape). Fill in the block below first. It runs once, as root, on
# first boot, and takes 10-15 minutes; progress is in /var/log/ati-lab-setup.log.
#
# Then open port 80 in the subnet's security list (see deploy/oracle/README.md)
# and visit http://<the instance's public IP>.
#
# The values below end up in the instance's metadata and in
# /opt/ati-lab/deploy/oracle/.env on the server. Both are visible only to your
# Oracle account and to root on the server.

# =============================== FILL THESE IN ===============================
DHAN_CLIENT_ID=""
DHAN_PIN=""
DHAN_TOTP_SECRET=""
DHAN_ACCESS_TOKEN=""          # only if you do not use PIN + TOTP

# GitHub backup: the candle store and learning history come back from here on
# first boot, so the new server starts with everything Render has.
GH_BACKUP_TOKEN=""            # fine-grained token, Contents: read and write
GH_REPO="kkute2118-hash/Backtesting-"
DB_BACKUP_BRANCH="db-backup"

# Only needed if the repository is private: a read-only token to clone it.
# (GH_BACKUP_TOKEN above works here too.)
GIT_TOKEN=""

ANTHROPIC_API_KEY=""          # optional
TWELVEDATA_API_KEY=""         # optional
# =============================================================================

REPO="kkute2118-hash/Backtesting-"
BRANCH="claude/stock-scanner-web-migration-t70lh0"
APP_DIR="/opt/ati-lab"

set -euo pipefail
exec > >(tee -a /var/log/ati-lab-setup.log) 2>&1
echo "=== ATI Lab setup started $(date -u) ==="

export DEBIAN_FRONTEND=noninteractive

# --- swap: the frontend build wants more than a 1 GB Micro shape has -------
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# --- Docker ------------------------------------------------------------------
apt-get update
apt-get install -y ca-certificates curl git openssl iptables-persistent
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# --- the OS firewall ---------------------------------------------------------
# Oracle's Ubuntu images ship iptables rules that REJECT everything but SSH,
# on top of the cloud security list. Allow port 80 ahead of that REJECT.
if ! iptables -C INPUT -p tcp --dport 80 -m state --state NEW -j ACCEPT 2>/dev/null; then
  reject_at="$(iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')"
  iptables -I INPUT "${reject_at:-1}" -p tcp --dport 80 -m state --state NEW -j ACCEPT
  netfilter-persistent save
fi

# --- the code ----------------------------------------------------------------
if [ ! -d "$APP_DIR/.git" ]; then
  if [ -n "$GIT_TOKEN" ]; then
    git clone --branch "$BRANCH" "https://x-access-token:${GIT_TOKEN}@github.com/${REPO}.git" "$APP_DIR"
    # Do not leave the token in .git/config.
    git -C "$APP_DIR" remote set-url origin "https://github.com/${REPO}.git"
  else
    git clone --branch "$BRANCH" "https://github.com/${REPO}.git" "$APP_DIR"
  fi
fi

# --- configuration -----------------------------------------------------------
PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me)"
ENV_FILE="$APP_DIR/deploy/oracle/.env"
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<ENV
PUBLIC_URL=http://${PUBLIC_IP}
API_ACCESS_KEY=$(openssl rand -hex 32)
DHAN_CLIENT_ID=${DHAN_CLIENT_ID}
DHAN_PIN=${DHAN_PIN}
DHAN_TOTP_SECRET=${DHAN_TOTP_SECRET}
DHAN_ACCESS_TOKEN=${DHAN_ACCESS_TOKEN}
GH_BACKUP_TOKEN=${GH_BACKUP_TOKEN}
GH_REPO=${GH_REPO}
DB_BACKUP_BRANCH=${DB_BACKUP_BRANCH}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
TWELVEDATA_API_KEY=${TWELVEDATA_API_KEY}
ENV
fi

# --- start -------------------------------------------------------------------
cd "$APP_DIR"
docker compose -f deploy/oracle/docker-compose.yml --env-file "$ENV_FILE" up -d --build

echo "=== ATI Lab setup finished $(date -u) ==="
echo "Open http://${PUBLIC_IP} (after allowing port 80 in the subnet's security list)."
