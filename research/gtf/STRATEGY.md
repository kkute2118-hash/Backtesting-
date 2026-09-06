# GTF-D13 — implementation-ready specification

Derived in `FINDINGS.md`. Every threshold was fixed on data before
2024-04-01 and left alone; validation (2024-04 → 2025-06) and test
(2025-07 → 2026-08) were read once each.

**Confidence: medium.** It survives every robustness test we ran, and it
loses to buy-and-hold unlevered over the same window. Both are true.

---

## Strategy name
**GTF-D13 — volatility-gated demand-zone arrival**

## Market regime
Long only. **Trade only when the equal-weight universe's 20-day realised
volatility is above its own trailing 500-day median.** Below it the strategy
loses money (−1.08 % per trade over 1,054 trades). This is the single
no-trade condition the data insisted on.

## Stock universe
Nifty 500, daily candles, ≥ 320 bars of history.

## Setup — the zone (video A1-A3, unchanged)

```
exciting(i)  :=  |close - open|  >  0.50 * (high - low)
base(i)      :=  not exciting(i)            # zero-range bars are base
```

A **demand zone** is a maximal run of 1..12 base candles such that:

* the bar immediately before the run is exciting (the leg-in), and
* the bar immediately after the run is exciting **and green** (the leg-out).

```
proximal := max over base candles of max(open, close)     # highest body
distal   := min over base candles of low                  # lowest wick
zone_height_pct := 100 * (proximal - distal) / proximal
leg_out_run := consecutive exciting green bars from the leg-out
achievement := max(high of leg_out_run) - proximal
legout_atr  := achievement / ATR14(at the leg-out bar)
```

The zone is tracked forward until a close falls below `distal`, at which
point it is dead.

## Entry
A resting **buy limit at the proximal line**, placed before the session opens.
Fill price `min(proximal, open)`.

Every gate below must be readable on the **previous close**. Nothing from the
entry day informs the decision.

## Filters — all five required

| # | condition | source |
| --- | --- | --- |
| F1 | `zone_height_pct >= 2.21` | **data** — the mechanism in §2 of FINDINGS |
| F2 | `legout_atr >= 0.837` | **video A5**, quantified by us |
| F3 | `ATR14 / close * 100 >= 3.24` | data |
| F4 | `100 * (prev_close / proximal - 1) >= 1.19` | data — approach speed |
| F5 | `(prev_close - EMA200) / ATR14 <= 0.96` | **our own prior audit** |

F5 is **not** "near the 200 EMA". It is *not extended above* it, and it admits
names far below: the median trade sits 2.4 ATR under the 200 EMA and 86.6 % of
trades are below it. This buys deep pullbacks in volatile names during selloffs.
| F6 | market volatility regime is high (above) | data |

Thresholds F1-F4 are the training-set 40th/50th percentiles. Every one sits on
a **plateau**, not a spike — see the sensitivity table; each can move ±30 %
without changing the sign or much of the magnitude.

## Stop loss
```
stop = entry - 2.0 * ATR14
```
**Not** the distal line. The video's structural stop earns ~60 % less per trade
because a thin zone's distal sits inside the daily noise: zones under 1.5 %
wide are stopped out 91 % of the time, 28.7 % of them on the entry bar itself.
Fill at `min(stop, open)` so a gap through the level costs what it really costs.

## Target
```
target = entry + 4.0 * ATR14
```
The plateau runs from +3 to +5 ATR. The video's own rule — the proximal line of
the nearest fresh supply zone on the trending timeframe (A11) — is a valid
alternative (+0.148 R vs +0.014 R for a flat 2 R) and is the better rule if you
want a structural target; the fixed ATR target simply tested slightly higher and
needs no weekly zone to exist.

## Time stop
**60 trading days.** The edge saturates by 40-60 bars; beyond that you are
holding for drift.

## Exit precedence
Stop, then target, then time. When both stop and target fall on the same bar the
**stop wins** — intrabar order is unknowable and the optimistic reading is how a
backtest flatters itself.

## No-trade conditions

* Market in the low-volatility regime (F6).
* The open gapped below the distal line — the limit and the stop trigger
  together, so it is not a takeable trade (1.0 % of arrivals).
* `zone_height_pct < 2.21` — the stop would sit inside the noise.
* Any zone already broken (a close below its distal).

## Signal score
**None. Do not build one, and stop using the existing one for ranking.**

Higher GTF trade score → worse outcome, consistently across train, validation
and test (spread −0.204 / −0.195 / −0.196 R). The score correlates −0.216 with
zone width, and width is what actually matters. The prior audit reached the same
conclusion about the production setup score from a different direction. Two
independent studies, same answer: **rank by nothing, filter by F1-F6.**

If a ranking is needed for capacity, rank by `zone_height_pct` descending. It is
the only monotone quality variable we found.

## Availability — this strategy is not always on

Signals by quarter over the audit window: 234, 1010, 358, **0, 0**, 660, 192.
Two full quarters of 2025 produced nothing, and 1,010 of 2,454 trades came from
the Feb-Mar 2025 correction. The volatility gate is doing its job, but the
consequence is a feast-or-famine profile. Size the capital plan for six
consecutive months of no signals.

## Expected behaviour

| | train | validation | test |
| --- | --- | --- | --- |
| trades | 1,213 | 1,693 | 852 |
| win rate | 43.4 % | 41.7 % | 48.4 % |
| avg % per trade | +2.60 | +2.48 | +3.91 |
| avg R | +0.281 | +0.305 | +0.431 |
| profit factor | 1.49 | 1.44 | 1.88 |

On the prior audit's own window (2024-09-04 .. 2026-09-04): 2,454 trades,
396 symbols, 43.3 % wins, **+0.289 R, PF 1.53** — against that audit's gated
S1-S4 record of 2,357 trades, 26.1 % wins, −0.189 R, PF 0.74. De-duplicated to
one trade per zone: 1,637 trades, +0.305 R, PF 1.573.

Whole sample: 3,758 trades, 432 symbols, +2.84 % / +0.326 R per trade, PF 1.54.
Signal frequency ≈ 690 per year across 500 names, ≈ 1.4 per symbol per year.

Portfolio, unlevered, 1 % equity risked per trade, one position per symbol,
12 random selection orders: **CAGR 9.1 % (p10 7.4, p90 11.8), max drawdown
−18.7 %, Sharpe 0.94** at 15 concurrent slots. Correlation with the equal-weight
index **−0.118**.

Benchmark over the same span: buy-and-hold 27.7 % CAGR, −21.4 % DD, Sharpe 1.53.

## Overfitting risk
**Medium-low.** Thresholds are percentiles, not searched values; all sit on
plateaus; walk-forward is 8/10; the result improves out of sample rather than
decaying. Against that: 13 candidates were compared, and the month-block
bootstrap CI on mean percent per trade is `[+0.09, +3.92]` — positive, wide, and
close to zero at the bottom.

---

## Implementation-ready rules

```
GIVEN a daily OHLCV series and today = T (all values read at close of T)

# --- zone construction
exciting(i)   = abs(close[i]-open[i]) > 0.50*(high[i]-low[i])
base(i)       = NOT exciting(i)
green(i)      = close[i] >= open[i]

FOR each maximal run base[a..b] with 1 <= (b-a+1) <= 12:
    IF exciting(a-1) AND exciting(b+1) AND green(b+1):
        proximal = MAX(MAX(open[k],close[k]) for k in a..b)
        distal   = MIN(low[k] for k in a..b)
        n        = count of consecutive exciting green bars from b+1
        achievement = MAX(high[b+1 .. b+n]) - proximal
        legout_atr  = achievement / ATR14[b+1]
        zone is ALIVE while no close[j] < distal for j > b+n

# --- signal for tomorrow
FOR each ALIVE demand zone Z:
    F1 = 100*(Z.proximal - Z.distal)/Z.proximal        >= 2.21
    F2 = Z.legout_atr                                   >= 0.837
    F3 = 100*ATR14[T]/close[T]                          >= 3.24
    F4 = 100*(close[T]/Z.proximal - 1)                  >= 1.19
    F5 = (close[T] - EMA200[T]) / ATR14[T]              <= 0.96
    F6 = market_vol20[T] > market_vol20_median500[T]

    IF F1 AND F2 AND F3 AND F4 AND F5 AND F6:
        signal   = TRUE
        entry    = Z.proximal          (resting buy limit for T+1)
        stop     = entry - 2.0*ATR14[T]
        target   = entry + 4.0*ATR14[T]
        time_stop = 60 trading days after fill
        REJECT the fill if open[T+1] <= Z.distal
```

`market_vol20` is the 20-day realised volatility of an equal-weight index of the
universe; `market_vol20_median500` is its own trailing 500-day median, so the
gate is point-in-time.
