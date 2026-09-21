# Forward-test selection criteria — every gate, every strategy

What actually decides whether a stock is entered into the forward-test book,
read off the code rather than off memory. Sources:

| stage | function | file |
|---|---|---|
| 0–1 | `resolve_universes`, `load_scan_dataset` | `backend/app/engine/core.py` |
| 2   | `clean_liquid_universe`                  | `backend/app/engine/core.py:3341` |
| 3   | `strategy_signal`                        | `backend/app/engine/core.py` |
| 4   | `entry_filter_verdict`                   | `backend/app/engine/core.py:12004` |
| 5   | score (display only)                     | `backend/app/engine/core.py:12200` |
| 6   | `forward_selection_verdict`               | `backend/app/engine/trader_layer.py` |
| 7–9 | `add_forward_candidates`                 | `backend/app/engine/core.py:12433` |

---

## The funnel

```
            SCAN_UNIVERSE  (default "Nifty 500"; last build ran NSE All Cash)
                    |
                    v
  0  UNIVERSE       resolve_universes() -> tickers
                    |
                    v
  1  STORE DEPTH    >= 260 stored daily bars, and >= 260 rows after features_fast()
                    |                                    (fewer -> "too_short", invisible)
                    v
  2  SAFETY GATE    clean_liquid_universe(), SAME for all five strategies
                    |   >= 60 bars
                    |   advanced_small_micro_safety status != REJECT
                    |   safety score      >= 60
                    |   close             >= Rs 20
                    |   price-action score>= 55
                    v
  3  STRATEGY RULES  <-- THE ONLY STAGE THAT DIFFERS BY STRATEGY
       +--------+--------+--------+--------+--------+
       |  S1    |  S2    |  S3    |  S4    |  S5    |     ALL rules of one
       |monthly |EMA     |EMA50   | SEPA   |pocket  |     strategy must pass;
       |inside  |cross   |pullback|watch-  |pivot   |     no partial credit
       |bar     |seq     |        |list    |variant |
       +--------+--------+--------+--------+--------+
                    |
                    v
  4  ENTRY EVIDENCE FILTER   entry_filter_verdict() -- NaN FAILS, never passes
                    |
          +---------+----------------------------+
          | turnover >= Rs 40 cr  (ALL FIVE)     |   median of close x volume
          +---------+----------------------------+   over the last 20 bars
                    |
          +---------+---------+                  +---------------------+
          | S1 S2 S3 S5       |                  | S4 only             |
          | ATR(14) >= 4% of  |                  | sector rank <= 3    |
          | close             |                  | of the 14 real NSE  |
          |                   |                  | index sectors; no   |
          |                   |                  | index membership =  |
          |                   |                  | reject              |
          +---------+---------+                  +----------+----------+
                    |                                       |
                    +-------------------+-------------------+
                                        v
  5  SCORE          computed, shown, persisted -- GATES NOTHING.
                    (5-year check: score deciles are non-monotonic over
                     117,282 signals -- 0.86, 1.71, 1.73, 2.19, 0.83, 0.91,
                     1.69, 0.55, 1.12, 1.70. It does not rank.)
                    daily_job.step_add() takes min_score and ignores it.
                    (min_score=85 in the API schemas is a DISPLAY threshold.)
                                        |
                                        v
  6  TRADER LAYER FILTER   *** OFF as of the 5-year run ***
                    |   APPLY_FORWARD_TRADER_FILTER = False
                    |   The CB purity >= 0.60 gate held on 2025-2026 and did
                    |   not hold on 2022-2026 (FINDINGS_DEEP.md). The module,
                    |   its tests and the skip_reason plumbing all stay; one
                    |   flag re-enables it. When ON, after a 400-bar load:
                    |     < 60 bars                      -> reject
                    |     avg_turnover_20 uncomputable   -> reject
                    |     turnover outside [40 cr, 1e9]  -> reject
                    |     no up bar in the last 10 bars  -> reject
                    |     CB purity outside [0.60, 1.01] -> reject
                    |     single-tower rule: OFF (APPLY_TOWER_RULE = False)
                    |   Rejections are written to scanner_signals.skip_reason.
                    |   Broken import fails OPEN; missing data fails CLOSED.
                    v
  7  DEDUPE         one position per stock, across all strategies and all dates
                    |   symbol already ACTIVE in forward_tests  -> skip
                    |   several strategies same day -> slot priority wins:
                    |        S4_SEPA = 0,  S5_POCKETPIVOT = 1,  S1/S2/S3 = 2
                    |   (applied BEFORE dedupe so a per-strategy exemption can bite)
                    v
  8  RECORDABLE     strategy in {S1,S2,S3,S4_SEPA,S5_POCKETPIVOT}
                    |   entry finite and > 0
                    |   SL finite
                    |   target finite  -- EXCEPT S5, which trails and has none
                    v
  9  STOP / TARGET  S1 S2 S3 S4 : SL = entry x 0.93 (7%), target = entry + 3R
                    S5          : SL = _s5_initial_stop(); no target;
                                  PocketPivotSLStateMachine trails
                                  (10 EMA / 50 EMA, 35-day grace)
                    v
 10  RESOLUTION     completed daily candles only. Never intraday.
```

---

## Stage 3, side by side

Everything in this table is frozen scanner logic and was not touched.

| | **S1** | **S2** | **S3** | **S4_SEPA** | **S5_POCKETPIVOT** |
|---|---|---|---|---|---|
| timeframe of the rule | monthly + weekly | daily + monthly/weekly RSI | daily + weekly | monthly | daily |
| core structure | monthly bar opens **and** closes inside the previous monthly range | exactly one recent bullish EMA cross (20/50 or 50/200), no bearish cross in 20/10 bars | close inside ±4% of EMA50 | monthly EMA10 crosses above EMA20, **or** monthly close reclaims EMA10 | an enabled pocket-pivot variant fires today |
| trend filter | monthly close ≥ monthly EMA15; (mclose−mema10)/mema10 ≤ 0.30 | EMA50 ≥ EMA250; (close−EMA10)/EMA10 ≤ 0.04 | close ≥ EMA200 | monthly EMA10 ≥ EMA20 | (variant-internal) |
| momentum | weekly RSI ≥ 50, monthly RSI ≥ 50, monthly 20-bar max ≥ 20 | monthly RSI ≥ 55, weekly RSI ≥ 50, 30-day max daily move ≥ 5% | weekly RSI ≥ 40 | monthly momentum ≥ 20%, monthly RSI ≥ 50 | (variant-internal) |
| rest / contraction | — | today inside yesterday's range; last two days' returns within −4%…+5% | — | — | — |
| own liquidity floor | vol20 ≥ 15,000; close ≥ 15 | vol20 ≥ 10,000; close ≥ 15 | EMA(VWAP20,20) × vol20 ≥ ₹15 cr | vol30 ≥ 50,000; close ≥ 20 | **none by design** (variant filter: ATR ≥ 4%, gap ≥ 0.36%) |
| stage-4 rule it gets | ATR | ATR | ATR | **sector rank** | ATR |
| exit style | 7% / 3R | 7% / 3R | 7% / 3R | 7% / 3R | trailing, no target |
| slot priority | 2 | 2 | 2 | **0** | 1 |

Note S3's own liquidity rule (₹15 cr) is weaker than stage 4's ₹40 cr floor, so
stage 4 binds. S5 carries no price floor at all — stage 2's ₹20 and stage 4's
₹40 cr are what keep it out of an illiquid name.

---

## Stage 4 in numbers

```
ENTRY_MIN_TURNOVER_CR   = 40.0     all five strategies
ENTRY_MIN_ATR_PCT       = 4.0      S1, S2, S3, S5
ENTRY_SECTOR_RANK_MAX   = 3        S4 only
ENTRY_SECTOR_LOOKBACK   = 21       relative strength window
ENTRY_FILTER_BY_STRATEGY = {1:atr, 2:atr, 3:atr, 4:sector, 5:atr}
```

Turnover is the **median** of `close × volume` over the last 20 bars, in crore —
a median, so one blow-off day cannot carry a name over the floor.

S4's sector rank is computed over the **14 sectors with a real NSE index**, not
all 22. Ranking all 22 measurably degraded it (PF 3.07 vs 1.98 → 2.95 vs 2.31,
p(mean) 0.103).

---

## Stage 6 in numbers — currently inactive

`APPLY_FORWARD_TRADER_FILTER = False`. The parameters below are what a
re-enable would use, and the reasoning under them is the record of what was
tried.

```
CB_MIN               = 0.60    floor only
CB_MAX               = 1.01    i.e. no ceiling
TURNOVER_MIN_CR      = 40.0    duplicate of stage 4, deliberately
TURNOVER_MAX_CR      = 1e9     i.e. no ceiling
EXPANSION_TAIL_BARS  = 10
APPLY_TOWER_RULE     = False
TOWER_RULE_EXEMPT    = set()
```

**CB purity** = of the *up* bars in the last 10 sessions, the share that were
Committed-Buyer days. A day is a CB when its return is at or above the 80th
percentile of that stock's **own** positive daily returns over the trailing 250
sessions (min 40 observations). So it is relative to the stock, causal, and
needs no fixed percentage — which is the point: a 6% day is a CB in one name
and unremarkable in another.

`>= 0.60` means: **at least 6 of every 10 up days in the run were exceptional
for that stock.** White candles interleaved in the expansion are exactly the up
days that were not CBs.

### Why this rule survived two years and then did not survive five

On 2025-2026 the 0.60 floor was the only threshold positive in both years
under the within-day permutation null (z = +3.4 and +3.0), with 0.30 and 0.40
failing outright. On 2022-2026, same matched test, same restriction to
live-equivalent signals (already past the Rs 40 cr floor):

| year | 2022 | 2023 | 2024 | 2025 | 2026 | ALL |
|---|---|---|---|---|---|---|
| mean diff | **-4.05%** | +0.90% | -0.11% | -0.53% | +2.18% | **-0.15%** |
| t | -6.53 | +1.15 | -0.24 | -0.83 | +3.06 | -0.52 |

Two positive years of five, flat overall, and the one large effect is
negative. The pooled figure is still +0.54%, but that comes from *which days*
the gate is active rather than which stock it picks on a given day - a timing
claim two good years cannot carry. Gate turned off; see `FINDINGS_DEEP.md`.

Everything else measured got cut earlier, and each cut is recorded:

| construction | verdict |
|---|---|
| hard-gate stack (CB + cluster + turnover + tower) | inverted the funnel; accepted trailed rejected by 0.94%/trade |
| turnover **ceiling** | harmful on the real store — it was a mega-cap proxy on the 161-name fixture |
| single-tower rule | flips sign between years; no stable edge |
| CB band 0.30–0.70 | both bounds wrong |
| CB floor 0.60 — the one rule that survived 2 years | no edge over 5 years; gate now off |
| weighted score, top-N/day | zero edge out of sample |
| ranking by tight stop | backwards on three independent constructions |
| M10/V12/V25 entry timing | cost 2.39 points; the scanners already fire at his entry bar |
| his 10-EMA trailing exit | −52.9%; median 2-bar hold |

---

## What is NOT a gate

- **Score / Adaptive Score / Learned Rank** — computed and displayed, gates
  nothing. `step_add()` documents that it accepts `min_score` and ignores it.
- **Regime** — recorded on the row, never used to reject.
- **Market or index demand zone** — tested, negative for all five.
- **Sector-at-support** — adds nothing on top of ATR.
- **Turnover ceiling, tower rule, marking/score gate** — all rejected, all
  deliberately absent.

---

## Known holes, not fixed because the scan logic is frozen

1. **Universe.** "NSE All Cash (~2000)" resolves to 9,922 names, of which 4,325
   are Sovereign Gold Bonds and only 2,688 are actual EQ series. The SME
   exclusion checks a symbol suffix while SME lives in `SEM_SERIES`, so it does
   not fire. Reported in `UNIVERSE_AUDIT.md`; no change made.
2. **Daily bars only.** His 3% stop comes from a three-scale confluence
   (daily 10 EMA → hourly 50 EMA → 15-min 200 MA). With daily candles the same
   trade is a 6–10% stop, which is why stage 9 uses 7%.
3. **Trade count.** ₹1 lakh over 3 slots is ~26 trades/year against a
   tail-carried payoff; only 41% of allocation orderings were profitable. The
   binding constraint is the number of trades, not the selection.
