#!/usr/bin/env bash
#
# Third copy of the database: one dated, compressed snapshot a day on this
# server's own disk, newest KEEP_DAYS kept (plus the first of each month for
# KEEP_MONTHS months). Independent of GitHub.
#
# Run by ati-lab-snapshot.timer at 03:00 IST, when nothing trades and no job
# runs, at the lowest CPU and disk priority (see the unit written by
# install_snapshot_timer in update.sh), outside the app's containers. The
# app does not wait on it or notice it.
#
# Uses SQLite's online backup, so the copy is consistent even if the mirror
# refreshes the database at the same moment. Restore one with:
#   gunzip -c /var/backups/ati-lab/market_data-YYYY-MM-DD.sqlite3.gz > market_data.sqlite3
set -euo pipefail

DEST="${SNAPSHOT_DIR:-/var/backups/ati-lab}"
KEEP_DAYS="${KEEP_DAYS:-14}"
KEEP_MONTHS="${KEEP_MONTHS:-6}"
VOLUME="${DB_VOLUME:-oracle_market-data}"

src="$(docker volume inspect "$VOLUME" -f '{{.Mountpoint}}')/market_data.sqlite3"
if [ ! -s "$src" ]; then
  echo "$(date -u +%FT%TZ) no database at $src; nothing to snapshot"
  exit 0
fi
mkdir -p "$DEST"
day="$(date -u +%F)"
tmp="$DEST/.snapshot-$day.sqlite3"
out="$DEST/market_data-$day.sqlite3.gz"

python3 - "$src" "$tmp" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=120)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst, pages=2048)      # in steps, so a reader is never blocked for long
dst.close(); src.close()
PY
gzip -c -6 "$tmp" > "$out.part" && mv "$out.part" "$out"
rm -f "$tmp"

# Keep the newest KEEP_DAYS, and the first snapshot of each of the last KEEP_MONTHS months.
ls -1 "$DEST"/market_data-*.sqlite3.gz | sort -r | tail -n +"$((KEEP_DAYS + 1))" | while read -r f; do
  d="$(basename "$f" | sed -E 's/market_data-([0-9-]+)\.sqlite3\.gz/\1/')"
  month="${d%-*}"
  first_of_month="$(ls -1 "$DEST"/market_data-"$month"-*.sqlite3.gz | sort | head -1)"
  cutoff="$(date -u -d "-$KEEP_MONTHS months" +%Y-%m)"
  if [ "$f" = "$first_of_month" ] && [[ "$month" > "$cutoff" ]]; then continue; fi
  rm -f "$f"
done
echo "$(date -u +%FT%TZ) snapshot $(du -h "$out" | cut -f1) -> $out; $(ls -1 "$DEST"/market_data-*.sqlite3.gz | wc -l) kept"
