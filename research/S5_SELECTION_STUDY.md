# S5 — refining 109 signals/week down to 3 positions

Follows `S5_POCKETPIVOT_FINDINGS.md`. Same data: 485 NSE symbols,
2022-06-01 → 2026-09-15, 24,478 signals, no score gate.

Run on the corrected stop (`S5_INTRADAY_INITIAL_STOP`), so the numbers here
differ from the first run and supersede it.

## The stop fix, and a prediction that was wrong

The tight initial stop is a resting order; it fills intraday. It had been
modelled on closes. Fixing it made results **worse**, not better:

| | Close-based (v1) | Intraday (v2) |
| --- | --- | --- |
| Win rate | 37.2% | 34.3% |
| Avg R | +0.839 | +0.609 |
| Median R | −0.44 | −0.59 |
| `initial_tight_stop_hit` | 4,402 @ −4.65R | 6,683 @ −1.89R |

The earlier estimate — "capping those at −1R would lift avg R to 1.32" — was
wrong in direction. It assumed the same stopped trades with smaller losses. In
fact the intraday stop fires on **2,281 more** trades, cutting short positions
that survived on closes and went on to do better. Per-trade losses shrank; the
population of losers grew more.

Per year is unchanged in shape: 2022 PF 1.41, **2023 PF 6.59**, 2024 PF 1.30,
2025 PF 0.93, 2026 PF 0.92.

## Baseline: what "take three at random" actually earns

Out of sample (2025-01-01 → 2026-09-15, 10,769 signals offered), 3 slots,
one position per name, 30 random draws:

| | |
| --- | --- |
| Trades actually takeable | ~123 of 10,769 (**1.1%**) |
| Win rate | 31.4% |
| Avg return per trade | −0.34% |
| Equity multiple | **×0.849** |

Two things follow. Slot pressure is the binding constraint — 99% of signals
are never reachable, so the scan's size is irrelevant and only the *choice*
matters. And unfiltered S5 **loses money** over the last 20 months.

## Filters chosen on 2022-2024, judged on 2025-2026

264 single-reading thresholds swept. Baseline: train PF 2.938, test PF 0.923.
71 improved profit factor in both windows. Top survivors:

| Rule | Train PF | Test PF | Test lift | Keeps |
| --- | --- | --- | --- | --- |
| `atr_pct >= 4.0` | 3.058 | **1.360** | +0.438 | 19.8% |
| `gap_pct >= 0.70` | 3.213 | **1.312** | +0.389 | 19.4% |
| `gap_pct >= 0.36` | 3.238 | 1.120 | +0.197 | 36.0% |
| `candle_lower_wick_pct >= 34` | 3.073 | 1.082 | +0.159 | 23.4% |

And the ones that looked best **in training** — the 2023 momentum signature —
failed out of sample:

| Rule | Train PF | Test PF | Test lift |
| --- | --- | --- | --- |
| `rsi14 >= 67.8` | 3.493 | 0.812 | **−0.111** |
| `dist_ema20_atr >= 1.98` | 3.471 | 0.807 | **−0.116** |
| `dist_ema50_atr >= 2.98` | 3.320 | 0.766 | **−0.157** |

This is the first run's conclusion confirmed by a different method: the
extended/high-RSI profile was 2023, and trading it afterwards loses.

## Filter first, then take three (the realistic system)

Out of sample, 3 slots, random pick *within* each filter:

| Filter | Kept | Took | Win % | Avg ret | Equity | vs base |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | 10,769 | 123 | 31.4 | −0.34% | 0.849 | — |
| `atr_pct >= 4` AND `gap_pct >= 0.36` | 923 | 98 | **38.1** | **+0.75%** | **1.221** | +0.372 |
| `gap_pct >= 0.36` | 3,886 | 104 | 31.9 | +0.32% | 1.055 | +0.206 |
| `gap_pct >= 0.70` | 2,104 | 94 | 32.0 | +0.34% | 1.052 | +0.203 |
| `atr_pct >= 4.0` | 2,147 | 125 | 34.8 | +0.29% | 1.006 | +0.157 |
| Variant = CONTINUATION | 2,490 | 46 | 29.3 | +0.25% | 0.994 | +0.144 |
| regime STRONG BULL/BULL | 4,913 | 82 | 28.5 | −0.20% | 0.903 | +0.054 |
| `rsi14 >= 67.8` (2023's winner) | 1,374 | 37 | 31.4 | −1.41% | 0.814 | −0.035 |
| `atr_pct >= 3.0` | 5,406 | 140 | 30.1 | −0.79% | 0.667 | −0.182 |

The best combination turns a losing system (×0.849) into a modestly positive
one (×1.221) while cutting the scan by 91%. Note `atr_pct >= 3.0` is *worse*
than no filter while `>= 4.0` helps — a threshold that sensitive on one window
is a warning, not a setting.

## What to do with this

1. **Filter on volatility and the entry gap, not on momentum.** `atr_pct >= 4`
   and `gap_pct >= 0.36` are the only readings that survived being chosen on
   one window and judged on another.
2. **Do not build a score from the winners-vs-losers table.** Nothing separates
   there (max 0.15 sd). The separation is all in the big-winner tail and all in
   2023.
3. **Treat the thresholds as provisional.** They come from one train/test split
   on one market. A third window, or a walk-forward re-fit, is what would make
   them a system rather than a hypothesis.
4. Even at its best this is ×1.22 over 20 months on 3 concentrated positions.
   That is not a finished strategy; it is the first version that is not losing.
