# Research scripts

Backtests and studies behind the decisions in `research/`. Nothing scheduled
runs them; re-run one when a rule is being reconsidered. Each script's
docstring has its usage line, and the matching note in `research/` has its
results.

| Scripts | Note |
|---|---|
| `portfolio_backtest.py`, `breadth_gate_study.py`, `s6_crosscheck.py`, `s6_entry_timing.py`, `s123_improve.py`, `s123_account.py` | NSE S1-S6: `research/PORTFOLIO_FINDINGS.md`, `S6_*`, `S123_IMPROVED.md`, `STRATEGY_SHORTLIST.md` |
| `search_trend_grid.py`, `trend_live_check.py` | The live crypto/gold trend book's rules (steps 14 and 17). Re-run both before changing `backend/app/tasks/trend_paper.py` |
| `liquidity_*`, `search_liquidity_runs.py`, `search_strategies.py`, `search_finalists.py` | Forex liquidity strategy B and the cross-strategy search (steps 2-3, 14) |
| `trend_4h_study.py`, `trend_4h_filtered_study.py`, `trend_4h_partial_ema.py`, `backtest_fast.py`, `backtest_optimizer.py` | Earlier 4h trend versions (steps 6-12), replaced by step 14 |
| `search_orb.py` | Opening-range breakout (step 15), not adopted |

The scripts that live jobs run stay one level up in `scripts/`.
Exploration scripts whose results are written up (fx_structure_study,
daily_trend_study, zone_sniper_study, trend_zone_entry_study,
trend_leverage_study, all_strategies_mtf, trade_charts,
trade_pattern_analysis) were removed on 15 Oct 2026; they are in git history.
