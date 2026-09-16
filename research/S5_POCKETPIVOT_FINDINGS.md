# S5 Pocket Pivot — first evidence run

Run date 2026-09-16. Reproduce with `BACKTEST_STUDY=s5_pocketpivot python daily_job.py study`,
or `core.run_s5_pocket_pivot_backtest()` directly.

| | |
| --- | --- |
| Data | local candle store, 485 NSE symbols with ≥260 bars |
| Window | 2022-06-01 → 2026-09-15 (223.9 weeks) |
| Gate | **none** — every S5 signal simulated, no score filter |
| Exits | `PocketPivotSLStateMachine` only (10/50 EMA, 35-day rule), 250-bar backstop |
| Trades | 24,478 (109.4 signals/week; the source claimed ~40–50 on a full universe) |

## Headline — and why it does not survive

| Measure | Value |
| --- | --- |
| Win rate | 37.2% |
| Avg R | **+0.839** |
| Median R | −0.44 |
| Avg return | +2.50% |
| Profit factor (on return %) | 2.06 |
| Avg holding | 19.5 bars |

The avg R is carried by a handful of trades and **does not survive trimming**:

| | Avg R |
| --- | --- |
| Raw | +0.839 |
| Winsorised 1/99 | +0.577 |
| Excluding \|R\| > 20 (655 trades, 2.9%) | **−0.025** |

Per year, on return % (outlier-free by construction):

| Year | N | Win % | Avg return | Profit factor |
| --- | --- | --- | --- | --- |
| 2022 | 2,934 | 37.5 | +1.11% | 1.43 |
| 2023 | 5,241 | 47.4 | **+10.49%** | **6.55** |
| 2024 | 5,534 | 35.9 | +0.87% | 1.32 |
| 2025 | 6,194 | 33.9 | −0.18% | 0.92 |
| 2026 | 4,575 | 31.5 | −0.15% | 0.94 |

**S5 made its money in 2023 and has been flat-to-losing since.** Any statistic
quoted over the whole window is a statement about 2023.

## What the winning trades have in common

Two splits, 42 readings recorded at the signal bar.

**Ordinary winners vs losers — nothing.** Largest gap 0.15 sd
(`s5_base_range_pct`). All 42 readings inert. Whether an S5 trade ends green is
not predictable from anything measured at entry.

**Big winners (top quintile) vs the rest — one coherent theme, in 2023 only.**
Price *extended above* the moving averages, high RSI, already broken out,
shallow pullback, near the recent high, full EMA stack, steep EMA200 slope.
It survives normalising by R (0.31–0.43 sd), so it is not just the wider stop
a distant 10 EMA implies. But split by year:

| Window | Readings ≥ 0.5 sd |
| --- | --- |
| 2023 only | **16** (top: `s5_dist_ema50_pct` 0.79, `s5_dist_ema20_pct` 0.76, `rsi14` 0.74) |
| Everything except 2023 | **none** (top 0.32) |
| 2025–2026 only | **none** (top 0.30) |

The signature is a 2023 artifact. Outside 2023 no reading separates, and there
is little to explain — profit factor sits at 1.0–1.3 on every cut.

## Secondary findings

**Variant.** Over the full window CONTINUATION looks best (avg R 1.233 vs
UNDERCUT 0.609). Ex-2023 the ranking collapses to noise — PF 1.22 / 1.09 / 1.01
for undercut / continuation / base. Undercut-and-rally is still 60% of all
signals, as flagged when it was implemented.

**Regime.** Full window: STRONG BULL avg R 1.501, BULL 1.034, BEAR −0.037,
EARLY BEAR −0.117, RECOVERY/SIDEWAYS −0.396. Ex-2023 every regime sits at PF
0.83–1.33. Regime looked like the dominant variable; it was 2023.

**The tight stop is a harness artifact and needs fixing before the next run.**
`initial_tight_stop_hit`: 2,967 trades (13.3%), avg R **−4.65**, worst −616R.
The state machine is defined on closes, and the undercut stop sits ~1.3% from
entry, so an exit lands far below the stop level in R terms. With an intraday
stop capping those at −1R, overall avg R would be 1.323 rather than 0.839. Near-
zero R denominators also make avg R unreliable — median R is the safer read.

**Do not read the exit-reason table as signal.** `10ema_violated_locked` shows a
100% win rate because reaching LOCKED_TIGHT requires surviving 35 days without
losing the 10 EMA, which only happens when already deep in profit. Tautology.

## Conclusion

No S5 scoring system should be written from this run. The only readings that
separate winners from losers do so in one year out of five, and the strategy's
edge outside that year is not distinguishable from zero.

Before anything is built on S5: fix the close-based stop, then re-run and ask
whether 2023 repeats anywhere else in the record.
