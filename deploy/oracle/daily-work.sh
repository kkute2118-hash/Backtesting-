#!/usr/bin/env bash
#
# The server's daily work (backend/app/tasks/oracle_daily.py), run inside the
# API container at low priority so the web app keeps the CPU it needs:
#
#   daily-work.sh scan       NSE Top 2000 scan, S1-S6, live prices in market hours
#   daily-work.sh research   nightly two-year backtest of every strategy
#
# Reports land in the database volume under reports/ and are served behind the
# site login at /reports/. Started by the ati-lab-scan and ati-lab-research
# timers that update.sh installs. Real work every day is also what keeps an
# Always Free server from being reclaimed as idle.
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/ati-lab}"
job="${1:?usage: daily-work.sh scan|research|trend}"
docker compose -f "$APP_DIR/deploy/oracle/docker-compose.yml" \
  --env-file "$APP_DIR/deploy/oracle/.env" \
  exec -T api nice -n 15 python -m app.tasks.oracle_daily "$job"
