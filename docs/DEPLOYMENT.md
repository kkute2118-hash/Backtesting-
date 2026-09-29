# Deployment

The web app runs on one Oracle Cloud **Always Free** server as a read-only
mirror: `deploy/oracle/` (see its README for provisioning, the self-update and
the Always Free limits, which `provision.py` enforces). Render and Vercel are
no longer used and their configuration has been removed.

| Part | Where |
| --- | --- |
| Data: candles, scans, paper trades, backup | GitHub Actions (`.github/workflows/`), the only writer of the backup |
| Web app (API + Next.js + Caddy) | Oracle, `deploy/oracle/docker-compose.yml`, follows `main` and the backup by itself |
| Daily dashboard and alerts | the Claude artifact, rebuilt by the `/scan` skill |

## The database and its three copies

1. **`db-backup` branch**, `backups/market_data.sqlite3.gz`: the primary copy,
   pushed with git by `scripts/push_backup.sh` after every job. Each push is a
   separate commit, so any earlier day can be restored from the branch history.
   GitHub limits a file on a branch to 100 MB; the script warns at 90 MB and
   refuses at 99 MB. `core.trim_backup_copy` keeps the file small.
2. **GitHub Release `db-backup`**: the same file, uploaded by
   `scripts/release_backup.py` right after the branch push, as
   `market_data.sqlite3.gz` (newest) plus one dated file per day for the last 7
   days. A release asset may be up to 2 GB, so this copy keeps working if the
   database outgrows the branch. `core.restore_db_from_github` falls back to it.
3. **Oracle's own disk**: `deploy/oracle/snapshot.sh`, run daily at 03:00 IST
   by `ati-lab-snapshot.timer` at the lowest CPU and disk priority, keeps 14
   daily snapshots and the first of each month for 6 months in
   `/var/backups/ati-lab/`.

Restore by hand from any of them: download or copy the `.gz`, then
`gunzip -c market_data….sqlite3.gz > market_data.sqlite3`.

## Running it elsewhere

`docker-compose.yml` at the repository root runs the same two processes on
any machine with Docker. The backend needs a disk that survives a restart for
the SQLite file (`DATA_DB`), and the GitHub backup settings (`GH_BACKUP_TOKEN`,
`GH_REPO`, `DB_BACKUP_BRANCH`) to restore it. A mirror sets
`BACKUP_READONLY=1` so it never writes the backup.

## Frontend environment

| variable | why |
|---|---|
| `NEXT_PUBLIC_API_URL` | Where the browser sends reads. Inlined at **build** time. |
| `API_BACKEND_URL` | Where the server-side mutation gateway forwards. Read at request time. |
| `API_ACCESS_KEY` | Same value as on the API. Server-side only; never prefix it `NEXT_PUBLIC_`. |

## Health checks

| service | path | what it means |
|---|---|---|
| API | `/health` | the API process is up; no database work. `/api/v1/health` also reports the database. |
| Web | `/health` | the Next server is up; says nothing about the API. |
