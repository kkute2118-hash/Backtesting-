# Running on an Oracle Cloud Always Free box

Everything here is free and stays free, provided one thing holds: **the
instance shape carries the "Always Free-eligible" badge.** Nothing else in
this document can put a charge on your card.

Why bother: the free Render instance is 0.1 CPU and 512 MB with no disk. This
is 4 cores and 24 GB with a persistent one. Measured on the same code, a
per-symbol scan costs ~44 ms; the difference between hosts is the difference
between a scan you wait 40 minutes for and one that finishes while you read
this.

---

## What "free" depends on

Your account has two layers and only one of them expires:

| | lasts | covers |
|---|---|---|
| **Always Free** | **forever** | 4 OCPU + 24 GB Ampere A1, 200 GB block storage, 10 TB egress |
| $300 trial credits | 30 days | anything, including paid shapes |

On day 31 the credits go and any resource that is **not** Always Free is
stopped and then deleted. Always Free resources carry on untouched. So the
trial expiring is a reclamation event, not a billing event — **Oracle blocks
rather than bills while the account stays on Free Tier.**

The one thing that can interrupt you is **idle reclamation**: Oracle may
reclaim an Always Free instance that looks unused over roughly a week. A web
app plus a daily scan is light enough to be borderline, which is why the
GitHub backup stays switched on below.

---

## 1. Create the instance

Console → Compute → Instances → Create.

| setting | value | why |
|---|---|---|
| Image | **Ubuntu 24.04, aarch64** | ARM build; every Python dependency here has an ARM wheel |
| Shape | **VM.Standard.A1.Flex** | must display *Always Free-eligible* |
| OCPU / memory | **4 / 24 GB** | the whole free allowance in one machine |
| Boot volume | **50 GB** | the database is ~1 GB; a separate block volume is not needed |
| Backups | **off** | volume backups are **not** Always Free — this is the usual accidental charge |
| SSH | your public key | |

**"Out of host capacity" is normal.** A1 is in demand and Mumbai/Hyderabad are
busy. Retry periodically. Do not switch to a paid shape to get past it — that
is how the bill starts.

Networking: use the **Create VCN with Internet Connectivity** wizard, then add
ingress rules for **TCP 80 and 443** on the public subnet's security list.

## 2. Bootstrap

```bash
ssh ubuntu@<your-instance-ip>
git clone https://github.com/kkute2118-hash/Backtesting-.git /tmp/ati
sudo bash /tmp/ati/deploy/oracle/bootstrap.sh
```

Installs Python, Node 20, Caddy and the repo, creates the directories, sets
the clock to IST, installs the systemd units, and **fixes the firewall** —
Oracle's Ubuntu images block every port but 22 at the OS level, so opening
80/443 in the console alone leaves the site unreachable. That mismatch is the
single most common failed first deploy.

Nothing starts yet.

## 3. Secrets

```bash
sudo -u ubuntu nano /etc/ati-lab/env
openssl rand -hex 32      # for API_ACCESS_KEY
```

The file is `chmod 600`, lives outside the repository, and is never printed by
either script. Fill in the Dhan credentials, `API_ACCESS_KEY`, the GitHub
backup token, and your hostname.

## 4. Hostname

```bash
sudo cp /opt/ati-lab/deploy/oracle/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile      # replace the first line
```

**No domain?** Use wildcard DNS so Caddy can still get a real certificate —
Let's Encrypt will not issue one for a bare IP:

```
203.0.113.10.nip.io
```

Put the same value in `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS`. Swap in a real
domain later by editing those three places and re-running `deploy.sh`.

One hostname serves both halves, because the paths do not collide:

```
/api/v1/*        FastAPI       the browser reads from here
/api/gateway/*   Next.js       mutations; it attaches API_ACCESS_KEY
everything else  Next.js
```

Same origin for both means no CORS preflight and no second certificate. The
API binds **127.0.0.1 only** — Caddy is the sole thing facing the internet.

## 5. Deploy

```bash
sudo bash /opt/ati-lab/deploy/oracle/deploy.sh
```

Pulls, installs, builds the frontend **before** restarting anything (so a
failed build leaves the running version serving), restores the database from
the GitHub backup if this box has none, then starts and enables everything.

Re-run the same command to ship a change.

## 6. Check

```bash
systemctl status ati-lab-api ati-lab-web caddy
systemctl list-timers 'ati-lab-*'
journalctl -u ati-lab-api -f
journalctl -u ati-lab-daily --since today
```

Then open `https://<your-host>` in a browser.

---

## What runs on a schedule

| timer | when (IST) | job |
|---|---|---|
| `ati-lab-token` | 08:30 daily | mint a fresh 24-hour Dhan token |
| `ati-lab-daily` | 18:30 weekdays | sync candles, resolve forward tests, scan, record, back up |

Both use `Persistent=true`, so a run missed while the box was down happens at
the next boot instead of being silently skipped — which is how a store quietly
falls days behind.

**Turn off the GitHub Actions schedules once this is working**, or the two will
race to write the same database backup. Keep the workflows themselves; a
`workflow_dispatch` run is a useful fallback if the box is ever gone.

## Keep the GitHub backup

On Render it was the only thing standing between a restart and total loss. On
Oracle the boot volume is persistent, so it is no longer load-bearing — **but
do not remove it.** An Always Free instance can be reclaimed if it looks idle,
and this backup is the difference between an evening's rebuild and losing five
years of candles and the entire forward-test record.

## Stay free

- Never click **Upgrade to Pay As You Go** — that removes the hard cap
- Never enable **boot or block volume backup policies**
- Never create a second A1 beyond the 4-OCPU total, or volumes past 200 GB
- Set a **budget alert at ₹1**: Billing & Cost Management → Budgets
- Check **Cost Analysis** after the first week; it should read zero

While the account stays on Free Tier, Oracle refuses to provision past the free
limits rather than charging you. The budget alert is belt and braces.

## Rollback

```bash
sudo -u ubuntu git -C /opt/ati-lab checkout <previous-sha>
sudo bash /opt/ati-lab/deploy/oracle/deploy.sh
```

And keep the Render deployment alive until this box has run for a month or
two. Two hosts reading the same GitHub backup is cheap insurance, and it means
no single platform decision can take the app offline for good.
