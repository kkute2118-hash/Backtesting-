---
name: scan
description: Rebuild the ATI Lab Daily page (claude.ai/artifact/Dvt7jL3RgXxi4eNw3gc6dN) - run the S4/S5/S6 scan and read the forward-test book from the latest GitHub database backup, then republish the page. Use for /scan, "run the scan", "update the dashboard", "how are my forward tests", or a scan on another universe.
---

# /scan - rebuild the ATI Lab Daily page

The page is a Claude artifact: https://claude.ai/artifact/Dvt7jL3RgXxi4eNw3gc6dN
Its source is `claude_dashboard/index.html`. It renders one data file,
`dashboard.json`, which `scripts/claude_dashboard.py` builds.

The script is read-only with respect to the database backup: it restores the
backup into a temporary directory, scans, reads forward tests, and writes JSON.
It never enrols, resolves or pushes anything. Forward testing belongs to the
GitHub job `.github/workflows/daily-forward-test.yml`. Do not run
`daily_job.py`, `scripts/push_backup.sh` or anything else that writes to the
`db-backup` branch from here.

## Steps

1. Dependencies, once per container (about a minute):

   ```bash
   pip install -q --ignore-installed cryptography -r backend/requirements.txt
   ```

2. Build the data file into your scratchpad directory:

   ```bash
   python3 scripts/claude_dashboard.py <scratchpad>/dashboard.json
   ```

   - `--universe "Nifty 50"` (or any name in `core.UNIVERSE_CHOICES`) when the
     user asks for a different universe. Default is Nifty 500.
   - It needs `GITHUB_TOKEN` (or `GH_TOKEN`) to read the backup. It takes about
     45 seconds.
   - Live prices: during market hours it overlays Dhan quotes when Dhan is
     reachable. If the environment's network policy blocks `api.dhan.co`,
     `images.dhan.co` or `auth.dhan.co`, it falls back to the last stored close
     and says so in the JSON (`scan.live.reason`). That is expected, not an
     error.

3. Republish the page to the SAME URL. Read it first (a publish to an
   artifact this conversation has not read is refused), then publish:

   - Artifact `read` with `url` = the page URL above.
   - Artifact `publish` with `url` = the page URL, `file_path` =
     `claude_dashboard/index.html`, and `files` =
     `{"dashboard.json": "<scratchpad>/dashboard.json"}`.

   Never publish without `url`: that creates a second page instead of
   updating this one.

4. Reply in a few lines, from the JSON:
   - market breadth (`breadth.latest`) against `breadth.threshold` (S6 open or
     waiting);
   - today's setups (`scan.signals`): stock, strategy, entry, stop; or why there
     are none (`scan.per_strategy`, `scan.filtered_out`);
   - the closest S6 watchlist names (`scan.s6_watchlist`, first 3-5, with
     `eligible_from`);
   - forward tests: open count, anything closed since the previous run
     (`forward.closed`, newest first), and the S4/S5/S6 scorecard;
   - whether prices were live or the last close (`scan.live.reason`).
   Then give the page link.

## Answering questions without republishing

For "how is my S6 trade in X doing" or "what did S5 find today", run step 2
and answer from the JSON. Republish only when asked or when the data changed.

## Changing the page

Edit `claude_dashboard/index.html`, rebuild the data (step 2) and republish
(step 3). Keep the page reading everything from `dashboard.json`: the JSON
shape is produced by `scripts/claude_dashboard.py`, so add fields there first.
