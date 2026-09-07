# Deliverable 3 — Robustness and Rule-by-Rule Ablation

Phases 6 and 7. Everything here is measured **after** the original result in
Deliverable 2 was fixed. Nothing below was fed back into the original run.

Two measurement instruments are used:

* **Portfolio** — the full simulation with capital, position and concurrency
  limits. 145 (Run A) or 489 (Run B) trades. Realistic, statistically thin.
* **Signal-level** — every setup traded independently at one unit of risk, no
  portfolio limits. 3,383 trades in Run B. Statistically powerful, and it is what
  the ablation uses, because comparing rules on 489 trades cannot separate a real
  effect from noise.

---

## 1. Is the result statistically believable?

| Question | Answer | Evidence |
| --- | --- | --- |
| Is profit concentrated in a few trades? | No — and the question inverts | Removing the best 5 trades takes Run B from −175.4 R to −203.0 R and net P&L from −522k to −613k. There is no small set of winners holding the result up, and no small set of disasters dragging it down. |
| Do both years agree? | Yes, all three calendar buckets | Run B average R: 2024 −0.486, 2025 −0.318, 2026 −0.346. Run A: −0.196, −0.136, −0.876. |
| Does it work in any regime? | No | Index above 50 EMA −0.331 R; below −0.700 R; high vol −0.348; low vol −0.368. |
| Is the drawdown acceptable? | No | −24.9% (A) and −52.2% (B), both against a benchmark that fell −21.4% at worst and finished +6.9%. Run B spent 481 of 497 sessions underwater. |
| Is the win rate misleading? | It is *accurate* | 21–22% matches the speaker's stated 22%. The problem is payoff, not frequency: 1.67 R average win against 0.91 R average loss needs a 35% win rate to break even. |
| Is the profit factor healthy? | No | 0.47–0.56. |
| Is expectancy positive? | No | −0.36 R (B), −0.43 R (A). |
| Too few trades to conclude? | No | 3,383 signal-level trades, t = **−13.18**. A negative result this large is not a small-sample artefact. |
| Evidence of overfitting? | Not applicable in the usual sense | Nothing was fitted. The concern runs the other way: no parameter setting anywhere in the sweep produces a positive number. |

**Return-to-drawdown:** −0.90 (A), −1.00 (B). **Longest losing streak:** 25 (A),
28 (B) — consistent with a 20% win rate, and a reminder that even the real system
requires sitting through runs of that length.

---

## 2. Does the *setup* pick stocks that go up?

This is the question that decides everything, because if the selection has an
edge, exits can be re-engineered; if it does not, nothing downstream can help.

Forward returns from the actual fill price, net of the equal-weighted proxy index
over identical dates, against the null of buying **any** stock on **any** day
(same market adjustment, 79,447 observations):

| Horizon | Signals | Signal excess | Null excess | Difference | Welch t |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 bar | 4,301 | −0.231% | −0.156% | −0.075% | −1.51 |
| 3 bars | 4,293 | −0.303% | −0.160% | −0.143% | **−2.12** |
| 5 bars | 4,253 | −0.186% | −0.166% | −0.020% | −0.24 |
| 10 bars | 4,168 | −0.221% | −0.174% | −0.048% | −0.42 |
| 20 bars | 4,030 | −0.078% | −0.196% | +0.118% | +0.74 |

*(Both columns are negative because the proxy index rebalances daily while single
names compound, so every individual stock carries a volatility drag against it.
That is why the null, not zero, is the comparison.)*

**The setup has no measurable forward edge at any horizon.** The only
statistically significant result is *negative*, at the 3-bar horizon — which is
close to the strategy's average 4.6-bar holding period. The mildly positive 20-day
number (t = 0.74) is not significant, and the strategy does not hold that long.

### The video's central claim, tested directly

Rule P-3 — "the more support levels line up at one price, the higher the
probability" — is the intellectual core of the video. On this data it points the
wrong way:

| Levels lining up | Signals | 5-bar excess | 10-bar excess | 20-bar excess |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1,730 | +0.060% | **+0.211%** | **+0.444%** |
| 2 | 1,734 | −0.389% | −0.543% | −0.456% |
| 3 | 691 | −0.262% | −0.447% | −0.346% |
| 4 | 88 | −0.434% | −0.757% | — |

Single-level touches are the only bucket with positive excess return; every
higher-confluence bucket is worse. The mechanism is plausible and worth stating:
a price at which four indicators coincide is a price the stock has spent a lot of
time near, i.e. a stalled, well-worn level rather than a fresh one. The
sensitivity sweep agrees — requiring 2 levels instead of 1 moves average R from
−0.318 to −0.352.

---

## 3. Positive controls — proof the harness can produce gains

| Control | Trades | Return | Win rate | PF | Avg hold |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buy-and-hold ~25 names, no stop, no filters | 50 | −2.47% | 34.0% | 0.84 | 248 bars |
| Same, 20-bar holding period | 625 | −6.92% | 46.9% | 0.92 | 20 bars |
| **The video's full selection gates, stop removed, 60-bar hold** | 200 | **−12.02%** | 41.5% | 0.79 | 57 bars |
| *Reference: equal-weight index* | — | *+6.90%* | — | — | — |
| *Reference: median stock* | — | *−3.81%* | — | — | — |

The unfiltered buy-and-hold control lands at −2.5%, between the median stock
(−3.8%) and the daily-rebalanced index (+6.9%) — which is where an unselective
basket of 25 names paying costs should land. So the engine is not manufacturing
losses.

The third row is the important one: **apply the video's selection rules, remove
the stop entirely, and hold for three months, and the result is worse than
buying at random.** The losses are not an artefact of tight stops or of the
9 EMA trail. The stock selection is the problem.

---

## 4. Parameter sensitivity (original strategy untouched)

Signal-level average R. **Every cell is negative.** The baseline is Run B,
`avg R = −0.318` on 3,383 trades.

| Parameter | Value → avg R (n) |
| --- | --- |
| RS rank floor | 0: −0.304 (4,818) · 50: −0.323 · 60: −0.327 · **70: −0.318** · 80: −0.284 · 90: −0.225 (1,364) |
| ADR floor % | 0: −0.332 · 1.5: −0.332 · **2.0: −0.318** · 3.0: −0.281 · 4.0: −0.178 (793) |
| Breadth floor | 0: −0.319 · 0.30: −0.319 · **0.40: −0.318** · 0.50: −0.340 |
| Stop ceiling % | 2.5: −0.465 (1,079) · 3.0: −0.425 · 4.0: −0.351 · **5.0: −0.318** · 8.0: −0.278 |
| Touch tolerance | 0.25%: −0.317 · **0.5%: −0.318** · 1%: −0.309 · 2%: −0.307 |
| Dip depth (ATR) | 0.5: −0.325 · **1.0: −0.318** · 2.0: −0.290 · 3.0: −0.139 (215) |
| Confluence required | 0: −0.298 · **1: −0.318** · 2: −0.352 · 3: −0.323 |
| Entry window (bars) | **1: −0.318** · 2: −0.336 · 3: −0.340 · 5: −0.344 |
| Partial size | 0%: −0.331 · **15%: −0.318** · 33%: −0.303 · 50%: −0.288 |
| Close-position floor | 0: −0.335 · 0.35: −0.314 · **0.50: −0.318** · 0.65: −0.331 |
| Anchored-VWAP anchor lookback | 30: −0.315 · **60: −0.318** · 90: −0.318 · 120: −0.321 |
| RS lookback (days) | 21: −0.285 · **63: −0.318** · 126: −0.270 |
| Partial targets (R) | none: −0.331 · (2): −0.323 · (3): −0.325 · (2,4): −0.317 · **(3,5): −0.318** · (4,8): −0.321 · (1,2): −0.313 |

Two observations worth carrying into the spec:

1. **The parameters barely matter.** Across 13 parameters and 48 settings the
   average R moves between −0.14 and −0.47. There is no ridge, no cliff, no
   sweet spot — the whole surface is flat and negative. This is the opposite of
   an overfitting signature, and it is also the opposite of an edge.
2. **The stop-ceiling row contradicts the video's headline argument.** The
   speaker's key slide (30:44) says tightening the stop from 3% to 1.5%
   multiplies your R and is worth eight losing trades. On daily Indian bars,
   tightening the ceiling from 5% to 2.5% takes average R from −0.318 to −0.465
   — it makes things *worse*, because a tighter ceiling selects only the
   narrowest setup bars, which are then whipsawed. The argument is sound for his
   intraday entries and does not transfer to daily bars.

---

## 5. Exit-rule readings (AMBIG-3)

The video never says when the "first close below the 9 EMA" rule starts to bind.
All readings tested:

| Reading | Signal avg R | Win rate | PF | Portfolio return | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Trail from entry (literal)** | **−0.318** | 22.3% | 0.55 | **−52.2%** | −52.2% |
| Trail arms after +1 R | −0.345 | 21.0% | 0.61 | −31.6% | −34.2% |
| Trail arms after +2 R | −0.350 | 16.8% | 0.62 | −29.5% | −36.2% |
| No trail, 10-bar time exit | −0.336 | 24.3% | 0.59 | −45.4% | −46.9% |
| No trail, 20-bar time exit | −0.358 | 20.3% | 0.59 | −31.8% | −34.8% |
| No trail, 60-bar time exit | −0.319 | 15.9% | 0.65 | **−24.1%** | −34.0% |
| Trail after +1 R, no partials | −0.361 | 20.9% | 0.59 | −33.1% | −35.6% |

The best exit reading still loses 24% over two years. Note the divergence between
the two columns: the portfolio improves when the trail is loosened (fewer, longer
trades means less turnover and less cost), while signal-level R gets slightly
worse. Neither comes close to breaking even.

**Cost sensitivity.** Setting all costs and slippage to zero moves Run B from
−52.2% to −39.6%, and signal average R from −0.318 to −0.199. Costs are about a
quarter of the damage. Three quarters is the strategy.

**Intrabar path sensitivity.** The benign assumption (a bar that both triggers
and breaches the stop did the breach first, before the position existed) moves
Run B from −52.2% to −43.9%. Directionally material, not decisive.

---

## 6. Out-of-sample: the three years before the window

Same rules, no changes, 2021-10-01 → 2024-09-04:

| | Run A (literal) | Run B (5% ceiling) |
| --- | ---: | ---: |
| Portfolio trades | 348 | 820 |
| Portfolio return | −33.3% | −38.7% |
| Win rate | 20.1% | 26.3% |
| Profit factor | 0.68 | 0.78 |
| Expectancy | −0.227 R | −0.159 R |
| Max drawdown | −36.9% | −49.3% |
| Signal-level n | 406 | 5,896 |
| Signal-level avg R | −0.177 | **−0.016** |
| Signal-level t | −1.41 | **−0.60** |

This is the most interesting result in the study. Over 2021–2024 — a strong bull
run for Indian mid-caps — the **signal itself is statistically flat** (−0.016 R,
t = −0.60 on 5,896 trades), not negative. Yet the **portfolio still loses 38.7%**,
because a flat signal traded with round-trip costs, a 20–26% win rate and a
trailing exit that clips winners bleeds capital steadily.

Read together with the two-year window: the setup is worth approximately zero
before costs in a friendly market, and worth less than zero in the recent one.
Neither period supports it.

---

## 7. Phase 7 — rule-by-rule ablation

One rule removed at a time from Run B, measured on unconstrained signals.
`Δ avg R` is *(variant − full strategy)*; a **positive** Δ means removing the rule
**improved** results, i.e. the rule was costing money.

| Variant | n | Avg R | Δ avg R | Win % | PF | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **full_strategy** | 3,383 | −0.318 | — | 22.3 | 0.55 | baseline |
| no_higher_low | 4,426 | −0.292 | **+0.026** | 22.5 | 0.59 | **harmful rule** |
| no_pullback_touch | 3,593 | −0.298 | **+0.020** | 22.6 | 0.58 | **harmful rule** |
| no_market_gate_at_all | 5,049 | −0.300 | **+0.018** | 22.9 | 0.57 | harmful (see note) |
| no_relative_strength | 4,843 | −0.305 | +0.013 | 22.2 | 0.57 | harmful |
| no_fresh_leg | 3,669 | −0.308 | +0.010 | 22.5 | 0.56 | neutral/harmful |
| no_market_slope | 3,796 | −0.309 | +0.009 | 22.6 | 0.56 | neutral |
| no_daily_trend | 3,627 | −0.312 | +0.006 | 22.7 | 0.55 | neutral |
| no_liquidity | 3,416 | −0.318 | −0.000 | 22.3 | 0.55 | neutral |
| no_ema150 | 3,384 | −0.318 | −0.000 | 22.3 | 0.55 | **inert** — removing it changes 1 signal |
| no_breadth | 3,390 | −0.319 | −0.001 | 22.3 | 0.55 | inert |
| no_weekly | 3,937 | −0.326 | −0.008 | 22.5 | 0.55 | mildly helpful |
| no_real_dip | 4,378 | −0.327 | −0.009 | 22.1 | 0.56 | mildly helpful |
| no_market_trend | 3,519 | −0.331 | −0.013 | 22.1 | 0.54 | mildly helpful |
| no_partials | 3,383 | −0.331 | −0.013 | 22.1 | 0.54 | mildly helpful |
| no_adr | 3,596 | −0.332 | −0.014 | 22.1 | 0.53 | mildly helpful |
| no_reversal_close | 4,662 | −0.335 | −0.017 | 21.7 | 0.54 | **helpful** |
| no_ema9_trail | 3,383 | −0.358 | −0.040 | 20.3 | 0.59 | **most helpful rule** |
| stock_gate_only | 9,001 | −0.328 | −0.010 | 21.9 | 0.56 | — |

Every year agrees: in the by-year breakdown (`ablation.json → ablation_by_year`),
**every variant is negative in 2024, 2025 and 2026 without exception.**

### Classification

| Class | Rules | Note |
| --- | --- | --- |
| **Essential** | *none* | No rule's removal takes the strategy from profitable to unprofitable, because it is never profitable. |
| **Helpful** (removal costs ≥0.01 R) | 9 EMA trailing exit (X-5, +0.040) · reversal close (P-5, +0.017) · ADR floor (U-1, +0.014) · partials at 3R/5R (X-2, +0.013) · index-above-50 EMA gate (M-1, +0.013) | These are real but tiny — the largest is worth 0.04 R against a −0.32 R hole. |
| **Neutral** (\|Δ\| < 0.01 R) | liquidity floor (U-5) · 150 EMA (T-4) · breadth (M-3) · daily trend stack (T-2/T-3) · index slope (M-2) · weekly veto (T-7) · dip depth (P-8) | The 150 EMA filter changes exactly **one** signal out of 3,383 — it is fully redundant with the other trend conditions. |
| **Harmful** (removal helps ≥0.01 R) | higher-low structure (T-6, −0.026) · the pullback touch itself (P-2/P-3, −0.020) · the whole market gate (M-1..M-3 together, −0.018) · relative strength ≥70 (U-3, −0.013) | Note that removing the *entire* market gate helps while removing the trend component alone hurts: the gates interact, and the combined effect is a wash. |
| **Untestable** | theme/sector (U-2) · intraday trigger and timing (C-1…C-5) · no-chase (N-1) · alternative stop candles (R-2, R-3) · discretionary sizing (Z-2) · everything in rulebook §11 | Missing data or human judgement. |

The single most damning line: **removing the pullback requirement entirely — the
thing the video is about — improves the result.** What is left after removing it
is "a trending, liquid, high-RS stock breaks yesterday's high", which is simply a
worse-than-random momentum entry on this data.

---

## 8. Why the video's result does not reproduce here — the four candidate reasons

Ranked by how much of the gap each explains, with what supports it.

1. **Market and instrument.** He trades US high-ADR momentum names (4–10% ADR,
   quantum/AI/nuclear themes) in 2025. The test universe is Indian large- and
   mid-caps with a median ADR of 3.5%. Support: filtering to the fastest names
   (ADR ≥ 4%) is the single best parameter change in the sweep (−0.178 vs
   −0.318), and it is still negative — but it moves in the direction that says
   the payoff tail needs volatility the Indian universe rarely offers.
2. **Timeframe.** His entry, his stop and his no-chase rule are intraday. His
   stops are 1–2.5% against moves of 20–50%, giving 10–30 R winners. The daily
   translation risks a full daily range (median 3.4%) for the same move, giving
   at best 5–7 R winners — and the observed average win is 1.67 R. This is
   structural: **the R-multiple denominator is set intraday, and the supplied
   data cannot reproduce it.**
3. **Regime and selection.** The 2024–2026 Indian window was flat-to-choppy for
   momentum: the equal-weight index gained 6.9% while the median stock lost
   3.8%. Chop is the exact regime the speaker names as his worst (his own −26%
   December). This is a real handicap — but the 2021–2024 out-of-sample was a
   strong bull market and the signal was still only flat.
4. **Discretion.** By his own account roughly half of one bad month's trades
   broke his rules, he has no strict sell rule, and he moves his anchored-VWAP
   anchor until it fits. Whatever the mechanical rules omit, that residue is
   where his edge would have to live — and it is unmeasurable from a transcript.

**What cannot be concluded:** that the speaker has no edge. Nothing here tests
his strategy on his market at his timeframe. What is shown is narrower and
firmer: **the daily-bar, Indian-equity translation of these rules has no edge,
and the specific claims that could be tested — confluence, tight stops — do not
hold on this data.**
