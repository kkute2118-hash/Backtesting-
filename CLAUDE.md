# Instructions for Claude sessions on this repository

## Oracle Cloud: Always Free only — never anything that can be billed

The owner's card is on file with Oracle Cloud. Everything created there must
stay inside Oracle's **Always Free** allowance, always:

- Only `VM.Standard.A1.Flex` (Ampere) — at most **4 OCPUs and 24 GB memory in
  total** across the whole tenancy — plus, if ever needed, the free
  `VM.Standard.E2.1.Micro`. No other shape.
- At most **200 GB of block storage in total**, boot volumes included.
- No paid services at all: no load balancers beyond the free one, no extra
  public IPs beyond ephemeral ones, no databases, no GPU, no autoscaling.
- Never upgrade the account to Pay As You Go, and never suggest it.
- `deploy/oracle/provision.py` enforces these limits against the tenancy's
  existing usage before creating anything. Do not weaken, bypass or raise
  those checks. If a task seems to need more, stop and ask the owner first.
- When unsure whether something is Always Free, treat it as paid and ask.

## How the system runs (read before changing anything operational)

- **Two independent front ends.** Render is gone (its config removed from the
  repository and all credentials removed from its services); never deploy to it. The Claude artifact https://claude.ai/artifact/Dvt7jL3RgXxi4eNw3gc6dN,
  rebuilt by the `/scan` skill, works on its own. The Oracle server
  (`deploy/oracle/`, `ati-lab`, Always Free) runs the web app as a read-only
  mirror that follows the backup and `main` by itself (deploy/oracle/README.md).
  It also runs its own daily scans and a nightly backtest
  (`app/tasks/oracle_daily.py`), reports only, at `/reports/`.
  Neither depends on the other.
- **Secrets never go into the backup.** The repository is public, so anyone
  can read the `db-backup` branch. `core.BACKUP_EMPTY_TABLES` empties
  `dhan_token_cache` in every whole-database backup; keep it that way.
- **One writer for the database, one owner of the Dhan login.** Only the
  GitHub workflows write the `db-backup` branch; Claude sessions, research
  scripts and the Oracle mirror (`BACKUP_READONLY=1`) only read it. Dhan keeps
  one live token per account, so Dhan jobs share the `dhan-db` concurrency
  group and the mirror yields to them (`DHAN_YIELD_TO_JOBS=1`).
- **Scanner strategies: S1-S6.** S4, S5 and S6 as tested. S1-S3 came back on
  29 Sep 2026 at the owner's request, each gated by S6's market traits
  (breadth >= 0.50, >= 60% above the 52-week low, within 15% of the 52-week
  high: entry rule `s6traits`, research/S123_IMPROVED.md). They take slots
  after S4-S6. `core.RETIRED_STRATEGIES` is empty; if a strategy is retired
  again, the daily job forward-tests it in the separate background book
  (`core.SHADOW_STRATEGIES`, `daily_job.step_shadow`).
- **Universes: at most 2,000 NSE shares.** "NSE Top 2000" is the 2,000 most
  liquid ordinary NSE shares; every download is capped there
  (`core.resolve_universe`). Only the history build ranks the full ~2,700
  candidates, then prunes to 2,000 (`daily_job._build_top2000`). Market breadth
  is always measured on the Nifty 500 (`core.S6_BREADTH_UNIVERSE`), whatever
  else the store holds, because the 0.50 gate was fitted on it.
- **Evidence rule.** A new filter or rule gates trades only if it was chosen on
  2022-24 data and holds on 2025-26 data. Otherwise it is a flag (like the
  results calendar) or it is not adopted (like the S5 market filter). Findings
  live in `research/`.
- **Keep backtests and the live scan identical.** Any rule added to the scan
  (for example the data-gap guard) must also be applied in `run_s6_backtest`,
  `historical_entry_verdict` and therefore `portfolio_bt.collect_trades`.
- **The journal** (collection `journal` in the artifact's database) is the
  owner's real trades: read it, never write it unless asked. Republish the
  page without `capabilities` so its storage rules carry forward.
