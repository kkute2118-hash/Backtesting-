# Deployment

The application is two processes, so it needs two hosts (or one machine running
both). Streamlit Cloud cannot serve it — it only runs `streamlit run`.

| Part | What it needs |
| --- | --- |
| `backend/` | Python 3.11, and **a disk that survives a restart** for the SQLite file |
| `frontend/` | any Next.js host |

The persistent disk is the part that matters. Candles can be re-synced from
Dhan in one job; forward tests, resolved outcomes and accumulated learning
**cannot be rebuilt from anywhere**. Configure the GitHub backup as well, so the
irreplaceable half survives even losing the disk.

---

## Recommended: Render + Vercel

Closest to the push-to-deploy experience Streamlit Cloud gave you. Roughly ten
minutes, and the order matters — the frontend needs the API's URL, and the API
needs the frontend's URL.

### 1. Backend on Render

1. <https://dashboard.render.com/blueprints> → **New Blueprint Instance**.
2. Connect this repository and pick the branch. Render reads `render.yaml` and
   proposes one web service with a 5 GB disk.
3. It will prompt for every value marked `sync: false`. Fill in at minimum:

   ```text
   DHAN_CLIENT_ID       your Dhan client id
   DHAN_PIN             your trading PIN          ┐ preferred: the app then mints
   DHAN_TOTP_SECRET     the base32 TOTP secret    ┘ its own 24h token
   CORS_ORIGINS         http://localhost:3000     (corrected in step 3)
   ```

   Leave the optional ones blank if you do not use them — the scanner,
   backtests and forward tests all work without Twelve Data and Anthropic.
4. Deploy. When it goes green, open `https://<your-service>.onrender.com/docs`
   — the interactive API documentation. **This is not the app**, it is the API.

> `render.yaml` is configured for the **free** plan, which has no persistent
> disk. Read *Running on the free plan* below before relying on it — the GitHub
> backup is mandatory there. Switching to `starter` and uncommenting the `disk`
> block removes that dependency and the 15-minute sleep, at a monthly cost.

### 2. Frontend on Vercel

1. <https://vercel.com/new> → import this repository.
2. **Root Directory: `frontend`.** Vercel detects Next.js on its own.
3. Add one environment variable:

   ```text
   NEXT_PUBLIC_API_URL = https://<your-service>.onrender.com
   ```

   It is read at build time, so it must be set before the first build. It is a
   URL, not a credential — no provider key is ever exposed to the browser.
4. Deploy. **The URL Vercel gives you is your app** — the replacement for the
   Streamlit link.

### 3. Let the two talk

Back on Render, set `CORS_ORIGINS` to the Vercel URL and redeploy:

```text
CORS_ORIGINS = https://your-app.vercel.app
```

A browser treats a different origin as a different site, so until this is set
every request from the frontend is blocked and the app shows *"Cannot reach the
analysis server"*. Include a comma-separated list if you also want to develop
locally against the deployed API:

```text
CORS_ORIGINS = https://your-app.vercel.app,http://localhost:3000
```

### 4. First run

Open your Vercel URL. The candle store starts empty, so:

1. **Data Manager → Sync missing history** — once, to build the history. It is
   rate-limited to five requests a second, so a full universe takes a while.
2. **Data Manager → Back up now** — confirm a `backups/market_data.sqlite3`
   file appears on the `db-backup` branch. If it fails, **Test the backup path**
   names the exact reason.
3. Thereafter, **Top up latest sessions** daily — or leave it to the scheduled
   GitHub Actions job, which does it for you.

---

## Running on the free plan

The free plan has **no persistent disk** and **sleeps after ~15 minutes idle**.
The filesystem — and therefore the whole SQLite database — is discarded on
every sleep. That is survivable, but only because the app treats the GitHub
backup as its disk:

```text
cold start  →  restore_on_cold_start()   pulls the whole database back
               (candles + forward tests + learning)
after a sync →  the candle store is pushed back up
after a
forward-test →  the small learning backup is pushed (rate-limited)
write
```

`app/services/bootstrap.py` does this, and it exists because of an ordering
trap worth knowing about: `core` restores the *small* learning backup at import
time, which makes the database non-empty, and `restore_db_from_github()`
refuses to overwrite a non-empty database. So a naive startup hook silently
skips the whole-database restore and leaves you with learning history but no
candles — an app that looks configured and can scan nothing. The bootstrap
checks the `candles` table specifically, and merges the learning backup back on
top afterwards.

**This makes the three `GH_*` variables mandatory on the free plan**, not
optional. Without them every sleep costs you everything the app has
accumulated.

### Setting it up

1. Create a GitHub token with write access to this repository:
   <https://github.com/settings/personal-access-tokens/new> → *Repository
   access* → **Only select repositories** → this repo → *Repository permissions*
   → **Contents: Read and write**.
2. On the API service, set:

   ```text
   GH_BACKUP_TOKEN    the token from step 1
   GH_REPO            owner/repo          (not a URL)
   DB_BACKUP_BRANCH   db-backup
   ```

3. Sync some history, then check **Data Manager → Back up now**. A
   `backups/market_data.sqlite3` file should appear on the `db-backup` branch.
   The branch is created automatically on the first backup.
4. Confirm recovery works: `GET /api/v1/health` reports a `boot_restore`
   object saying what the last cold start recovered.

### What free still costs you

- **First request after a sleep takes ~50 seconds**, plus the restore.
- **A very large candle store gets slow to move.** The whole-database backup
  goes through GitHub's Contents API, which caps a file at 100 MB. Nifty 500
  over a few years is comfortably inside that; the full ~2000-name NSE universe
  over many years eventually is not. If you get there, switch to a disk.
- **Nothing runs while the service sleeps.** Scheduled work is unaffected —
  the GitHub Actions jobs run on GitHub's runners against `daily_job.py` and
  never touch the web host at all. On the free plan they are doing the real
  daily work, and the web app is the viewer.

---

## Alternative: one machine

Any VPS with Docker. Both processes, one command:

```bash
git clone -b <branch> https://github.com/kkute2118-hash/Backtesting-.git
cd Backtesting-
cp backend/.env.example .env          # fill in your credentials
docker compose up -d
```

Open `http://<your-server>:3000`. Put a reverse proxy with TLS in front of both
ports before exposing it to the internet, and set `NEXT_PUBLIC_API_URL` and
`CORS_ORIGINS` to the public hostnames.

The database lives in the `market-data` Docker volume — a named volume, not a
bind mount into the checkout, so `git pull` can never land on top of it.

---

## The scheduled jobs are separate

`.github/workflows/` runs on GitHub's runners against `daily_job.py`. It does
not touch either host and keeps working through any hosting change.

It reads **GitHub Actions secrets**, which are a different store from your
hosting provider's environment variables. Setting one does not set the other —
this is the single most common reason the backup works in the app but not in the
scheduled job, or the reverse.

---

## Checklist

- [ ] Backend deployed, `/api/v1/health` returns `"status": "ok"`
- [ ] Persistent disk mounted, `DATA_DB` pointing at it
- [ ] Frontend deployed, `NEXT_PUBLIC_API_URL` set to the backend URL
- [ ] `CORS_ORIGINS` on the backend set to the frontend URL
- [ ] Dhan credentials set; **Settings** shows Dhan as configured
- [ ] History synced once from Data Manager
- [ ] `GH_BACKUP_TOKEN` + `GH_REPO` + `DB_BACKUP_BRANCH` set, and a backup verified
- [ ] The same secrets added to GitHub Actions for the scheduled jobs
