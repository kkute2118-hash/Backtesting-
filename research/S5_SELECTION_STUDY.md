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

## Two multiple-comparison tests, one of them fatal

**Ranking rules: dead.** Searching 84 rankings (42 readings × 2 directions)
directly on the test window found `s5_ema200_slope_pct` lowest-first at ×1.414,
beating 100% of 30 random draws. That looks conclusive and is worthless. The
right null is not one random draw but the BEST of 84 random draws, because with
84 tries something always wins. Over 150 such experiments:

| best-of-84 random rankings | |
| --- | --- |
| median | ×1.735 |
| p95 | ×2.213 |
| max | ×2.923 |

The observed ×1.414 sits at **p = 0.98** — worse than the median of pure search
luck. No ranking rule found here is real. Any "rank the candidates by X" scoring
system built on this data would be ranking noise.

**Filters: they clear it.** The same null was run for the sweep — outcomes
shuffled within the train block and within the test block, so 2023 stays the
good year and 2025-26 stay bad while every reading-to-outcome link is destroyed.
60 shuffles:

| | Observed | Null median | Null p95 | Null max | p |
| --- | --- | --- | --- | --- | --- |
| Survivors | 71 | 65 | 87 | 93 | 0.40 |
| Best test lift | **+0.438** | +0.185 | +0.319 | +0.361 | **< 0.017** |

Two different answers, and both matter. The *count* of survivors is pure chance —
71 of 264 is what coin-flips give, so "71 thresholds survived" means nothing on
its own. But the *size* of the best lift beats all 60 shuffles; the null never
once reached +0.438. `atr_pct >= 4.0` is not the kind of thing this search
produces by accident.

## The decisive check: does it lift every year?

Profit factor by year, unfiltered and filtered. The filter thresholds come from
2022-2024 only.

| Year | N | PF all | `atr_pct>=4` | `gap_pct>=0.36` | both |
| --- | --- | --- | --- | --- | --- |
| 2022 | 2,934 | 1.413 | 1.880 | 1.408 | 1.815 |
| 2023 | 5,241 | 6.592 | 8.618 | 7.415 | 10.786 |
| 2024 | 5,534 | 1.304 | 1.489 | 1.379 | 1.611 |
| 2025 | 6,194 | 0.928 | 1.017 | 1.099 | **1.224** |
| 2026 | 4,575 | 0.915 | 1.864 | 1.139 | **2.305** |

**Five years out of five, in the same direction** — including turning both
losing years profitable. That is a far stronger result than one train/test split,
and it is what separates this from the ranking search that failed.

It also improves direction, not just tail size, which is what a pure
volatility-harvesting artifact would look like:

| | Win rate | Median ret | Avg win | Avg loss |
| --- | --- | --- | --- | --- |
| All signals | 34.3% | −0.95% | — | — |
| `atr_pct>=4` | 39.9% | −0.87% | +15.49% | −4.34% |
| both | **41.8%** | −0.64% | +17.45% | −4.42% |

## What to do with this

1. **Filter on volatility and the entry gap, not on momentum.** `atr_pct >= 4`
   and `gap_pct >= 0.36` are the only readings that survived being chosen on
   one window and judged on another.
2. **Do not build a score from the winners-vs-losers table.** Nothing separates
   there (max 0.15 sd). The separation is all in the big-winner tail and all in
   2023.
3. **The thresholds are supported but not settled.** They cleared a shuffled
   null and lift every one of five years. What remains open is the exact
   number: `atr_pct >= 3.0` came out *worse* than no filter in the slot
   simulation while `>= 4.0` helped, and a cliff that sharp between adjacent
   thresholds usually means the slot sample (~140 trades) is too small to
   resolve it, not that 3.5 is a boundary. Re-fit the level walk-forward rather
   than hard-coding 4.0.
4. **Do not build a ranking.** Filtering works; ordering the survivors does not.
   84 ranking rules were searched and the best came out below the median of pure
   search luck.
5. Even at its best this is ×1.22 over 20 months on 3 concentrated positions,
   from 923 of 24,478 signals (3.8%). That is not a finished strategy; it is the
   first version that is not losing, and the first S5 result that survives a
   null.
