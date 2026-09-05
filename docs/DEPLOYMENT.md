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

> **On the free tier** there is no persistent disk and the service sleeps when
> idle, so the database is wiped between wakes. That is only workable with the
> GitHub backup configured, and it re-syncs candles on every cold start. The
> `starter` plan in `render.yaml` avoids both problems.

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
