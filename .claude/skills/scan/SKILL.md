---
name: scan
description: Rebuild the ATI Lab Daily page (claude.ai/artifact/Dvt7jL3RgXxi4eNw3gc6dN) - run the S1-S6 scan and read the forward-test book from the latest GitHub database backup, then republish the page. Use for /scan, "run the scan", "update the dashboard", "how are my forward tests", or a scan on another universe.
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
     (`forward.closed`, newest first), and the S1-S6 scorecard;
   - whether prices were live or the last close (`scan.live.reason`).
   Then give the page link.

5. Phone messages: Google Calendar events, twice a trading day. After each
   scheduled run, put one event on the owner's primary calendar
   (`kkute2118@gmail.com`) with the Google Calendar connector. The Calendar
   app on the phone shows it as a notification at the event's start; this is
   the owner's chosen daily message.

   | Run (routine) | Event time (IST) | Title starts | What it is for |
   |---|---|---|---|
   | 09:16 morning (after the 09:15 open, so prices are live) | 09:20-09:25 | "ATI 9:20" | market overview at the open: breadth and gate, regime, open paper trades and any gap through a stop, S6 watchlist, setups forming (provisional until the close) |
   | 15:05 afternoon | 15:15-15:20 | "ATI 3:15" | the decision run: setups to act on before 15:30 with entry, stop and quantity, exits today |

   - Settings: `timeZone` "Asia/Kolkata", `availability` AVAILABILITY_FREE,
     `overrideReminders` [{"method": "popup", "minutes": 0}],
     `notificationLevel` NONE.
   - One event per run per day: first search today's events for the run's
     title prefix; update that event if it exists instead of adding another.
   - Title (the notification text, under 90 characters), action first:
     "ATI 3:15: 2 setups - WELCORP S6 <=2,840 SL 2,391; MCX S5 ...",
     "ATI 3:15: exit NIACL S5 -1.0R", "ATI 9:20: no setups, breadth 0.11 (S1-S3, S6 waiting)",
     "ATI 9:20: PRICES NOT LIVE - check Dhan".
   - Description: the step 4 summary as short lines: market overview
     (breadth against 0.50 and which strategies it holds back, regime, how
     many stocks were scanned and whether prices were live), setups with
     entry, stop and suggested quantity at 1% risk on Rs 1 lakh (capped at
     25% of capital), exits today, open paper trades (best, worst, nearest to
     its stop), the three nearest S6 watchlist names, and the page link. A
     morning setup is marked provisional: an S5 or S6 entry counts only on
     the day's close.
   - Also call PushNotification with the same line when there is something to
     act on (setups, an exit today, or prices not live). It reaches the phone
     only when Remote Control is connected, so the calendar event is the one
     that always arrives.
   - Skip the event on market holidays and weekends (no scan runs then).

## Answering questions without republishing

For "how is my S6 trade in X doing" or "what did S5 find today", run step 2
and answer from the JSON. Republish only when asked or when the data changed.

## Real trades (the journal)

The page's "My trades" section stores real orders in the artifact's own
database, collection `journal`, one document per trade: `symbol`,
`strategy`, `entry_date`, `entry`, `qty`, `stop`, `exit`, `exit_date`,
`note`. Only the owner and Editors can write it. It survives republishes.
For "how are my real trades doing", read it with the ArtifactData tool
(`list`, collection `journal`, url of the page) and compare with
`forward.open` / `forward.closed` from the dashboard JSON: the same stock and
strategy within 5 days of each other is the paper twin. Never write to it
unless the user asks you to record or correct a trade.

When republishing, omit `capabilities` so the stored declaration
(`db` with rule read: interact, write: admin) carries forward. Passing a
different set would revoke the journal's storage rules.

## Changing the page

Edit `claude_dashboard/index.html`, rebuild the data (step 2) and republish
(step 3). Keep the page reading everything from `dashboard.json`: the JSON
shape is produced by `scripts/claude_dashboard.py`, so add fields there first.

## Schedules (Claude routines, not GitHub)

| IST, weekdays | Routine | What it does |
|---|---|---|
| 09:05 | ATI Lab morning data job kick | Wakes a small dedicated session that calls `workflow_dispatch` on `daily-forward-test.yml`. GitHub starts its own cron runs 4-5 hours late on this repository; dispatched runs start within seconds. The workflow's crons stay as a fallback. |
| 09:16 | ATI Lab morning overview | Runs this skill with live prices and posts the 09:20 phone message (step 5). |
| 15:05 | ATI Lab daily scan | Wakes the session that owns the page and runs this skill. The morning job has finished by then, so the page shows the newest candles, forward-test results and setups before the 15:30 close. |

Manage them in claude.ai under Routines. If the page's "Updated" time is not
today's afternoon on a trading day, check the 15:05 routine first; if its
"Data" chip is a day behind, check the morning kick and the workflow's runs.
