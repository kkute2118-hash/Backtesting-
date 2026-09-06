# What the GTF course actually taught us

Research outcome, not a summary. Every number below comes from the scripts in
this directory, run over 104,592 demand-zone arrivals across 475 Nifty 500
symbols, 2021-04-12 to 2026-08-07.

Three things are kept apart throughout, because they are not the same thing:
**what the video claims**, **what our data shows**, **what we should implement**.

---

## 0. Headline

The video's *zone construction* is worth having. Its *quality score is
inverted* — it is a proxy for zone thinness, and thin zones die in the noise.
Its *filters* are, with two exceptions, unsupported. The strategy exactly as
taught does not clear costs.

A hybrid of the video's zone geometry, one video concept it never quantified,
two features the data found, and the 200 EMA relationship from our own prior
audit **does** survive every test we could throw at it — at +2.8 % per trade,
+0.33 R, profit factor 1.54, improving from train to validation to test. It is
also, unlevered, worse than buying the index over this window.

---

## 1. Setting the bar: is it a bull market or an edge?

Everything else is meaningless without this. For every real arrival we drew a
**matched placebo**: same symbol, same calendar month, same planned risk in
percent, random bar. Identical geometry, identical regime, no zone.

| exit | GTF arrivals | matched placebo | edge |
| --- | --- | --- | --- |
| 1 R target | −0.119 R | −0.177 R | +0.058 |
| 2 R target | +0.002 R | −0.126 R | **+0.128** |
| 3 R target | +0.071 R | −0.093 R | **+0.164** |

Month-block bootstrap, 95 % CI on mean R at 2 R: arrivals `[−0.071, +0.078]`,
placebo `[−0.199, −0.049]`.

**The zone carries real information — it beats the placebo decisively. It does
not, on its own, clear costs.** Both statements matter.

### A bug worth recording

The first version of this study put the *entry bar's own high* in the forward
path. A stock that crashed into a zone and bounced the same day was scored as a
win, even though the high may have printed before the low that filled us. That
single defect was worth **+0.28 R per trade** — it turned a flat result into an
apparently excellent one. Targets are now measured from bar 1; the stop is still
allowed on bar 0, because that asymmetry is the conservative one.
`test_no_target_can_be_recorded_on_the_entry_bar` pins it.

---

## 2. The video's claims, one at a time

Mean R at a 2 R target. `agree3` = the sign is the same in train, validation and
test — the only column that separates a relationship from a coincidence.

| # | claim | train | val | test | verdict |
| --- | --- | --- | --- | --- | --- |
| A12 | **trade score is monotone in outcome** | 1/7 → +0.236, 7/7 → +0.028 | same | same | **rejected — inverted** |
| A4 | fresh beats tested | +0.061 / +0.112 / +0.121 | | | **rejected — backwards** |
| A12b | fewer base candles are better | 1-3: +0.054, 6+: +0.218 | | | **rejected — backwards** |
| A12c | 1 leg-out **+ gap** scores like 2 leg-outs | gap bucket is the worst of the four | | | **rejected** |
| A12d | more leg-outs are better | +0.093 / +0.108 / +0.132 | ✓ | ✗ | weak, survives width control |
| A6 | leg-out must close above the leg-in high | +0.082 vs +0.108 | | | **not supported** as a standalone gate |
| A7 | buy demand only in an uptrend | up +0.105, down +0.089 | inverts | | **not supported** |
| A9 | curve position decides buyer or seller | no ordering; weekly curve runs the *wrong* way in train | | | **rejected** |
| A2 | reversal (DBR) vs continuation (RBR) | +0.104 vs +0.071 | | | no material difference |
| A13 | execution stacked on location is best | +0.029 vs +0.099 | | | **rejected — worse** |
| A5 | leg-out must have "achievement" | spread +0.022 / +0.123 / +0.057 after controlling for width | ✓ | ✓ | **supported** |
| A11 | target = opposing zone on the trending timeframe | +0.148 R vs +0.014 R for a flat 2 R | | | **supported** |

### Why the score is inverted — the mechanism

This is the most useful thing in the study.

```
corr(GTF trade score, zone width) = −0.216
corr(base-candle count, zone width) = +0.462
```

A "7 out of 7" zone is, by construction, **one narrow base candle with an
explosive leg-out** — which is a *thin* zone. And thin zones lose:

| planned risk | stop-out rate within 60 bars | stopped on the entry bar | avg R @2 R (with cost) | (zero cost) |
| --- | --- | --- | --- | --- |
| < 1.5 % | **91.2 %** | **28.7 %** | −0.221 | +0.024 |
| 1.5-2.5 % | 86.3 % | 14.6 % | −0.024 | +0.094 |
| 2.5-4 % | 80.3 % | 7.7 % | +0.060 | +0.133 |
| 4-6 % | 74.1 % | 3.8 % | +0.124 | +0.172 |
| > 6 % | 61.2 % | 1.6 % | +0.180 | +0.209 |

Two forces, both real, roughly half each. A 0.23 % round-trip cost is **0.22 R**
on a 1 %-risk zone and 0.03 R on a 6 % one. And a stop a fraction of a percent
under the entry sits *inside the daily noise* — it gets taken out on the entry
bar more than a quarter of the time.

The video optimises for a quality that the market charges you for. This is the
same shape as the prior audit's finding that our own setup score was inversely
predictive, arrived at from a completely different direction.

---

## 3. What the data found that the video did not

Feature spread (top quintile minus bottom), **controlled for zone width** so
width cannot drive the answer, in all three periods:

| feature | train | val | test | reading |
| --- | --- | --- | --- | --- |
| `n_base` | +0.105 | +0.069 | +0.039 | more base candles is *better* — contra A12 |
| `prev_close_pct` | +0.037 | +0.108 | +0.149 | speed of approach: a fast drop into the zone beats a grind |
| `atr_pct` | +0.026 | +0.088 | +0.203 | volatility helps |
| `legout_atr` | +0.022 | +0.123 | +0.057 | **A5 quantified** — the video's own idea, given a number |
| `relvol` | +0.017 | +0.078 | +0.021 | volume helps slightly. The video mentions volume 14 times in 52 hours |
| `dist_ema20_atr` | −0.002 | −0.092 | −0.089 | deeper pullbacks are better |
| `turnover_cr` | −0.186 | −0.149 | −0.058 | illiquid names do better — **probably not harvestable** |
| `target_r_available` | −0.214 | −0.080 | −0.012 | a *near* opposing zone is better, contra the ≥2 R gate |

`turnover_cr` is the one we deliberately do not use. A −0.19 spread toward the
least liquid quintile is exactly what impact cost eats, and our 0.23 % model
does not price it.

---

## 4. Exits: the video's stop is the wrong one

Average **percent per trade** (size-neutral) on train, 60-bar cap, real minus
the matched placebo in brackets:

| stop | +2 ATR | +3 ATR | +4 ATR | +5 ATR | +6 ATR |
| --- | --- | --- | --- | --- | --- |
| **distal line (the video's)** | 0.61 | 0.92 | 1.10 | 1.16 | 1.07 |
| distal − 0.5 ATR | 0.94 | 1.37 | 1.55 | 1.52 | 1.29 |
| entry − 1.5 ATR | 1.00 | 1.48 | 1.66 | 1.64 | 1.39 |
| **entry − 2.0 ATR** | 1.21 | 1.69 | **1.78** | 1.61 | 1.18 |
| entry − 3.0 ATR | 1.45 | **1.81** | 1.55 | 0.96 | 0.14 |

The edge over the placebo is a flat **+0.82 to +1.25 % plateau across the whole
grid** — the information is in the entry, not the exit. But the *absolute*
return is not flat: a volatility-scaled stop at **entry − 2 ATR** earns about
60 % more per trade than the video's distal stop, because it stops guessing that
one base candle's low is a meaningful level.

In R the distal stop looks best (+0.53 edge vs +0.16). That is the leverage
illusion: R rewards the tightest stop with size nobody can actually take. Percent
of capital is the honest unit here, and it says the opposite.

Holding period: the edge saturates by 40-60 bars (+0.51 → +0.53 R). 60 bars.

---

## 5. Candidate strategies

Exit fixed at entry − 2 ATR / +4 ATR / 60 bars. Thresholds are train medians,
never touched to validation or test.

| candidate | train avg % | val | test | PF train/val/test |
| --- | --- | --- | --- | --- |
| C0 every GTF arrival | 1.78 | 0.40 | **−0.26** | 1.44 / 1.08 / 0.94 |
| C1 **video Version A**, all its filters | 2.69 | 0.38 | 0.74 | 1.69 / 1.07 / 1.18 |
| C2 video 7/7 trade score only | 1.96 | 1.44 | 0.49 | 1.47 / 1.31 / 1.12 |
| C9 width + achievement + vol + speed | 2.34 | 1.42 | 1.60 | 1.43 / 1.25 / 1.31 |
| C11 C9 + liquidity floor | 1.45 | 1.08 | 1.38 | 1.25 / 1.18 / 1.27 |
| **C12 C9 + near 200 EMA** | 1.96 | **2.05** | **2.18** | 1.35 / 1.36 / **1.44** |
| **C13 C12 + high-volatility regime** | **2.60** | **2.48** | **3.91** | 1.49 / 1.44 / **1.88** |

C0 and C1 both decay out of sample. **C12 is the only candidate that improves**,
and it is the Phase-15 hybrid: video zone geometry + our own prior audit's
200 EMA proximity relationship. C13 adds the one no-trade condition the data
insisted on.

---

## 6. Trying to break C13

| test | result |
| --- | --- |
| **Parameter sensitivity** | plateaus or monotone everywhere. 200 EMA cut flat from 0.4 to 3.0 ATR (+2.18 → +1.76). No spikes. |
| **Walk-forward**, 6-month windows, no refit | **8 of 10 positive** |
| **Cross-stock**, 432 symbols | 62.5 % profitable; median symbol +2.09 %/trade; top 5 = 7.5 % of gross profit; top 20 = 24.1 % |
| **Drop the 10 best symbols** | still +1.69 %/trade, PF 1.31 |
| **Matched placebo** | C13 +2.05 % vs placebo −1.65 % |
| **Bootstrap 95 % CI** (month blocks) | `[+0.09, +3.92]` — excludes zero, but only just, and it is wide |
| **Survivorship probe** | corr(symbol edge, symbol buy-and-hold) = **0.066**. The *worst* buy-and-hold quintile — median −5.5 % over 5.5 years — still averages **+2.29 % per trade**. The edge does not run through "stocks that went up anyway". |
| **Regime** | works in high volatility (+2.84 %), **loses in low volatility (−1.08 %)**. This is a no-trade condition, not a curiosity. |
| **Selection variance**, 12 random orders | CAGR p10 7.4 %, median 9.1 %, p90 11.8 % at 15 slots — tight |

### Where it fails

**Unlevered, it loses to buying the index.**

| | CAGR | max DD | Sharpe |
| --- | --- | --- | --- |
| C13, 15 slots, 1 % risk, no leverage | 9.1 % | −18.7 % | 0.94 |
| C13, 20 slots | 9.5 % | −17.4 % | 1.03 |
| **equal-weight universe, buy and hold** | **27.7 %** | −21.4 % | **1.53** |

Capacity binds hard: 3,758 signals, ~450 taken. And correlation of daily
strategy returns with the index is **−0.118**.

So the honest verdict is not "we found a better strategy". It is: *we found a
real, robust, essentially uncorrelated positive-expectancy signal, in a window
where a raging bull market beat it comfortably on its own terms.* Its value is
as an overlay or a selection layer, not as a replacement for being invested.

---

## 7. Answers to the brief

**What did the video actually teach us?** That a demand zone — leg-in, base,
leg-out, marked body-to-wick — locates information. The placebo test says so at
+0.13 R. Nothing else in 52 hours survives contact with the data as stated.

**Which ideas are supported?** Zone construction (A1-A3). Leg-out achievement
(A5) — the one thing the video insisted on but never quantified, and the data
agrees once you give it a number. The target-at-the-opposing-zone rule (A11).

**Which are not?** The 7-point trade score, and every component of it:
freshness, base-candle count, and the gap-equals-two-leg-outs equivalence. The
curve/location model. The trend gate. The closing concept as a standalone gate.
Pattern type. "Fully coinciding". The ≥2 R filter, which selects *against* the
better trades.

**What should we take?** Zone geometry, the leg-out achievement measure, and the
knowledge that zone *width* is the variable that matters — inverted from how the
video ranks it.

**What should we ignore?** The trade score. It is worse than nothing: it is
confidently backwards, and a scanner that ranks by it will systematically
surface the trades most likely to be stopped out.

**Did we discover a better strategy?** We discovered a better *signal*
(C13: +2.8 %/trade, +0.33 R, PF 1.54, improving out of sample, uncorrelated with
the index). We did not discover a better *portfolio* than being long this
universe over 2021-2026.

**What should change in the current system?**

1. Stop using the setup score as a ranking. Two independent studies now say it
   is inversely predictive.
2. Add a **zone-width floor** wherever a stop is derived from structure. A stop
   inside the noise is not a tight stop, it is a donation.
3. Replace structural stops with **volatility-scaled** ones (entry − 2 ATR).
4. Keep the 200 EMA proximity filter. It is the only relationship that has now
   reproduced across two entirely different signal populations.
5. Add the market-volatility no-trade gate.

---

## 7b. The prior audit's own window, and the actual trades

Run on **2024-09-04 .. 2026-09-04**, the exact window
`research/strategy_config.proposed.json` used, so the numbers sit next to that
file's headline rather than floating free. Trade counts land within 4 % of each
other, which makes it close to like-for-like.

| | trades | symbols | win % | avg R | PF | max DD |
| --- | --- | --- | --- | --- | --- | --- |
| every GTF arrival | 43,741 | 475 | 31.3 | −0.082 | 0.93 | — |
| C12, five filters | 3,001 | 401 | 40.1 | +0.190 | 1.36 | −404 % |
| **C13** | **2,454** | 396 | **43.3** | **+0.289** | **1.53** | −292 % |
| *prior audit, gated S1-S4* | *2,357* | — | *26.1* | *−0.189* | *0.74* | *−629.5 R* |

Inside that window: 2024-09 → 2025-06 (which overlaps the training tail)
+0.213 R; 2025-07 → 2026-09, fully held out, **+0.431 R, PF 1.88, 48.4 % wins**.

**One trade per zone.** 40 % of zones are entered more than once, so the raw
count double-counts. De-duplicated to the first arrival only: 1,637 trades,
43.8 % wins, +2.97 %, **+0.305 R, PF 1.573** — slightly *better* than the
undeduplicated figure, so the repeats were not carrying it.

Outcome mix: 1,207 stops, 1,063 targets, 184 time exits. Median hold 14 bars.
Every trade is in `trades_audit_window.csv` with the zone's bar coordinates;
`chart_check.py` prints the raw candles so any of them can be checked by eye.

### Two things that only showed up in the trade list

**The gate goes dark.** Signals by quarter: 234, 1010, 358, **0, 0**, 660, 192.
Two full quarters in 2025 produced nothing at all, and 1,010 of 2,454 trades
came from the Feb-Mar 2025 correction alone. This is a feast-or-famine,
event-driven strategy, not a steady one. Any capital plan has to survive six
months of no signals.

**Zones wait a long time.** Median 22 bars from formation to the arrival, but
the 75th percentile is 177 bars and the best cohort is `>150 bars` (+0.43 R).
The video says this explicitly — its own example waits two years. Only the
61-150 bar band is negative (−0.05 R).

### Two reporting bugs found by looking at the trades

* **R was divided by the realised fill, not the planned risk.** When an open
  gapped down to just above the stop, realised risk collapsed to 0.99 % against
  a 12 % plan and a normal winner scored 39.5 R. It hits 0.38 % of arrivals —
  enough to move a mean. R is now measured against the planned risk, which is
  also what the position was sized on. Percentages were never affected.
* **The outcome label counted "neither hit" as a stop**, so time exits were
  being reported as stop-outs.

### A description of mine that was wrong

Filter F5 was described as "near the 200 EMA". It is not. `dist_ema200_atr
<= 0.96` is **"not extended above the 200 EMA"**, and it admits names far below
it: the median trade sits 2.4 ATR *below* the 200 EMA and **86.6 % of trades are
below it entirely**. The strategy buys deep pullbacks in weak-looking, volatile
names during selloffs. That is a materially different picture from "near the
200 EMA" and it is the accurate one.

---

## 8. What this study cannot tell you

* **Survivorship.** Today's Nifty 500 applied to the whole window. The probe in
  §6 bounds the channel but cannot conjure the delisted names.
* **Corporate actions.** Still unverified — the prior audit's open item. A split
  in the store would manufacture a false zone and a false arrival.
* **One market, one regime.** 5.5 years, one country, one of the strongest bull
  runs in its history. The low-volatility result is the closest thing to an
  out-of-regime sample and it is negative.
* **Only the long side.** Supply zones are detected but untested; symmetry is an
  assumption, not a finding.
* **Only daily execution.** The video's HIT/DIT sets need intraday candles we do
  not store. MIT is the set our data can express, and it is also the one the
  instructor recommends.
* **13 candidates were compared.** C13's bootstrap CI is `[+0.09, +3.92]`.
  Apply a multiple-comparison haircut before believing the upper half of it.
