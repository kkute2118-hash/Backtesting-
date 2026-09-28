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

- **No web host.** Render is retired; do not deploy to it or fix it. The
  dashboard is the Claude artifact https://claude.ai/artifact/Dvt7jL3RgXxi4eNw3gc6dN,
  rebuilt by the `/scan` skill. Oracle (`deploy/oracle/`) only if the owner asks
  for a live web app again.
- **One writer for the database.** Only the GitHub workflows write the
  `db-backup` branch. Claude sessions and research scripts restore it into a
  temporary directory and never push it.
- **Scanner strategies: S4, S5, S6 only.** S1-S3 are retired
  (`core.RETIRED_STRATEGIES`) from the scanner and the page, but the daily job
  still forward-tests them in a separate background book
  (`core.SHADOW_STRATEGIES`, `daily_job.step_shadow`), so there is live data
  if they are ever reconsidered. That book never blocks an S4-S6 position in
  the same stock, and the page and alerts show S4-S6 only. The owner reviewed S1-S6 on 28 Sep 2026
  (`research/STRATEGY_SHORTLIST.md`) and chose to keep S4, S5 and S6.
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
