# Running ATI Lab on Oracle Cloud's free tier

## How it runs: a read-only mirror that updates itself

The scheduled GitHub jobs own the data: they sync prices, run the scans and
forward tests, and write the database backup. The Oracle server follows them
and never competes with them:

- **Read-only.** `BACKUP_READONLY=1`: the app never writes the GitHub backup,
  so it cannot overwrite a newer backup with an older copy.
- **Refreshes only when there is something new.** `MIRROR_REFRESH_MINUTES=10`:
  every 10 minutes the app asks GitHub for the newest backup commit (one small
  API call). It downloads the ~64 MB backup only after a job has pushed a new
  one, about three times a trading day, and swaps it in atomically. Your
  preferences, watchlists and presets (`app_*` tables) and the server's own Dhan
  login are carried over each time.
- **Never takes the Dhan login from a running job.** `DHAN_YIELD_TO_JOBS=1`:
  Dhan keeps one live token per account. While a GitHub Dhan job is running the
  app does not mint a new token (that would cut the job off mid-sync); it shows
  stored prices for those few minutes and logs in again after the job ends.
- **Updates itself.** `install-updater.sh` installs a systemd timer that runs
  `update.sh` every 15 minutes: one `git fetch`, and a rebuild only when `main`
  has changed. It also adds the three settings above to an older `.env`.
- **Keeps its own daily copies.** `update.sh` also installs
  `ati-lab-snapshot.timer`: at 03:00 IST, at the lowest CPU and disk priority,
  `snapshot.sh` writes `/var/backups/ati-lab/market_data-YYYY-MM-DD.sqlite3.gz`
  (14 daily copies plus the first of each month for 6 months). It is the third
  copy of the database, after the `db-backup` branch and the `db-backup`
  GitHub Release (docs/DEPLOYMENT.md).
- **Does real work every day.** `update.sh` also installs two timers that run
  `daily-work.sh` inside the API container at `nice 15`
  (`backend/app/tasks/oracle_daily.py`):
  - `ati-lab-scan.timer`: S1-S6 over the stored NSE Top 2000 at 09:20, 12:30
    and 15:10 IST on weekdays, with live Dhan prices while the market is open
    (about 2 minutes each);
  - `ati-lab-research.timer`: at 02:00, 08:00, 14:00 and 20:00 IST, every strategy backtested
    over the last 2 years on every stored stock, by market-breadth band and as a
    Rs 1 lakh account.

  - `ati-lab-trend.timer`: every 5 minutes, the 4-hour trend strategy for
    crypto and gold perpetuals is paper-traded live
    (`backend/app/tasks/trend_paper.py`, Binance public candles, Yahoo Finance
    as the fallback). The book is at `/reports/trend.html`. Breakouts, fills
    and exits are pushed to the owner's phone through the free ntfy app; the
    private topic name is created on the server and shown only on that page.

  Reports are JSON files under `/reports/` on the site (same login), kept for
  30 days. Neither job writes the backup or GitHub. The daily load is also what
  keeps Oracle from reclaiming the server as idle (below).

A server created before this existed needs one command, once:

```bash
sudo bash -c 'cd /opt/ati-lab && git fetch origin main && git checkout -B main origin/main && bash deploy/oracle/install-updater.sh'
```

The Claude page (`/scan`) and the GitHub jobs do not depend on this server at
all: they keep working whether it is up or down.

Oracle's **Always Free** Ampere server (up to 4 CPU cores and 24 GB of RAM,
free indefinitely) runs the whole app on one machine. It never sleeps and has
a real disk that survives restarts.

Everything is started by one script, `cloud-init.sh`, which you paste in while
creating the server. You need an Oracle Cloud account first
(<https://signup.cloud.oracle.com>; card verification only, nothing charged
on Always Free resources).

## Or: let the API do steps 1-3

`provision.py` creates the network, opens ports 22 and 80, and launches the
server with the setup script already filled in, all through Oracle's API. It
reads everything from environment variables (listed at the top of the file):
an Oracle API key from **Profile → API keys → Add API key**, plus the same
Dhan and GitHub values the script asks for.

```bash
pip install oci
python deploy/oracle/provision.py --dry-run   # check the plan
python deploy/oracle/provision.py             # create it; prints the address
```

It is safe to re-run, which matters because free Ampere servers are often
out of capacity: it tries every availability domain, and a later run picks up
where the last one stopped. Then continue at step 4.

## 1. Fill in the script

Open `deploy/oracle/cloud-init.sh` and fill in the block at the top: your Dhan
details and a GitHub token (`GH_BACKUP_TOKEN`). The token lets the new server
download your existing candle store and learning history on first boot.

## 2. Create the server

In the Oracle Cloud console: **Compute → Instances → Create instance**.

| Setting | Choose |
| --- | --- |
| Image | **Canonical Ubuntu 24.04** (or 22.04) |
| Shape | **Ampere → VM.Standard.A1.Flex**, 2 OCPUs and 12 GB is plenty (up to 4 / 24 is free) |
| Networking | Keep "Assign a public IPv4 address" on |
| SSH keys | Download the generated private key and keep it safe |
| Advanced options → Management → **Cloud-init script** | Paste the whole of `cloud-init.sh` |

Click **Create**. If you get **"Out of capacity"**, your region's free Ampere
servers are all taken right now: retry later, or try another availability
domain.

## 3. Open port 80

Oracle blocks all incoming traffic except SSH by default. On the instance page:
**Primary VNIC → Subnet → Security Lists → Default Security List → Add Ingress
Rules**:

- Source CIDR: `0.0.0.0/0`
- IP protocol: TCP
- Destination port range: `80`

The script opens the server's own firewall; this rule opens Oracle's.

## 4. Wait, then open it

Setup takes 10-15 minutes (it builds both apps). Then visit
`http://<public IP>` — the public IP is on the instance page.

To watch progress, SSH in and run:

```bash
tail -f /var/log/ati-lab-setup.log
```

## Updating later

```bash
cd /opt/ati-lab && sudo git pull \
  && sudo docker compose -f deploy/oracle/docker-compose.yml \
       --env-file deploy/oracle/.env up -d --build
```

The database lives in a Docker volume, not in the checkout, so `git pull` and
rebuilds never touch it.

## Staying free

This setup is built to stay inside Oracle's **Always Free** allowance: one
Ampere server of 2 OCPUs / 12 GB (the free limit is 4 / 24 in total) and a
50 GB disk (the free limit is 200 GB in total). `provision.py` checks what the
account already uses and refuses to create anything that would go over.

Two things on your side keep it that way:

- **Do not upgrade to "Pay As You Go".** On a Free Tier account Oracle cannot
  bill for anything outside Always Free: those resources simply stop when the
  30-day trial credit ends. Upgrading removes that safety net.
- **Add a budget alert** as a second net: Billing & Cost Management → Budgets →
  Create budget, amount **1** (in your currency), alert at 1% of actual spend,
  with your email. Any charge at all then emails you at once.

## Good to know

- **Settings** (Dhan, GitHub and the rest) live in
  `/opt/ati-lab/deploy/oracle/.env` on the server. After editing it, run the
  update command above.
- **API_ACCESS_KEY** is generated on the server by the script; the web app adds
  it to every change request automatically.
- **Login**: the whole site asks for a username and password (user `krushna21`).
  Only a bcrypt hash of the password is in `Caddyfile`; the owner has the
  password. To change it: `docker run --rm caddy:2 caddy hash-password`, put
  the new hash in `Caddyfile`, push to `main`. `/health` and `/health/api`
  stay open (they say only "ok") for the uptime check.
- **HTTPS**: `https://<ip-with-dashes>.sslip.io` (for 132.226.191.194:
  `https://132-226-191-194.sslip.io`). sslip.io is a free public name that
  points at the IP; Caddy gets a Let's Encrypt certificate for it by itself.
  `update.sh` writes `SITE_HOST` into `.env` and opens port 443 in the
  server's firewall; port 443 is open in the Oracle network's security list.
  `http://<ip>` keeps working too, with the same login.
- **Uptime**: `.github/workflows/uptime.yml` checks the app every hour; a
  failed run emails the repository owner.
- **Logs** are capped at 3 x 10 MB per container, so they cannot fill the disk.
- **Idle reclamation**: Oracle may reclaim an Always Free server that sits
  almost completely idle for 7 days; the daily scans and nightly research above
  keep it busy. The data does not depend on it (the
  backup branch and release copy are on GitHub); the uptime check would say so,
  and `provision.py` recreates the server.
