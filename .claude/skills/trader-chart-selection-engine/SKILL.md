---
name: trader-chart-selection-engine
description: Second-stage evaluation of stock scanner candidates using a chart-reading methodology reconstructed from 14 trading lecture transcripts. Use when reviewing, filtering or ranking a candidate list from the S1-S5 scanners, or when asked how the trader's methodology (TTF/STF/ETF, DNA, relativity, expansion/contraction, volume clusters, demand candles, pivots, event on the LHS) applies to a specific chart or setup.
---

# TRADER_CHART_SELECTION_ENGINE

Evaluates stock-scanner candidates using the methodology extracted from 14 lecture
transcripts. Full derivation lives in `references/`; this file is the working
procedure.

## The one rule that governs everything

**The scanner only creates the candidate.** Never say "buy because the scanner
triggered." A scan hit is the beginning of the analysis.

You are also bound by the platform's ABSOLUTE RULE: **do not change what S1-S5 select
or score.** This engine reads their output and re-orders it. It never modifies scanner
logic, thresholds, indicators, scoring, stops, targets, or stored records.

## What has been measured, and what it changed

The procedure below is **not** the methodology applied as written. It is what
survived testing against 22,530 scanner signals. Three things were built from
the source material and measured; two of them failed, and saying so is the
point of this section.

**Use this (validated out of sample, z=+7.6, all five strategies improved,
survives Indian transaction costs):**

```
keep a candidate only if ALL THREE hold
  1. volume cluster, NOT a single isolated tower
  2. CB purity between 0.30 and 0.70     <- a BAND. above 0.75 turns negative
  3. 20-day average turnover 100-400 cr  <- a BAND. a plain floor flips sign
```

**Do not use these — they were built and measured, and they lose money:**

- **The hard-gate stack** (event on the LHS, EMA separation, containment,
  upper-half). Applied together it inverted the funnel: accepted candidates
  underperformed rejected ones. Containment in particular — the rule he calls
  "one of the most important points that I'll ever give you in your trading" —
  has **no measurable effect** (−0.066% vs −0.058% across 22,530 signals).
- **Entry timing** (waiting for M10 / V12 / V25 or the inside bar after the
  10>20 cross). It reproduces his stop widths correctly, and it costs **2.39
  percentage points**, because S1–S5 are already pullback scanners: they fire
  at the bar he would buy, so waiting waits for a second pullback.
- **Ranking by tight stop.** Tighter stops predicted *worse* outcomes on three
  independent constructions. His tight stop comes from entering on a 15-minute
  chart inside the daily pullback, which our daily-only data cannot express.
- **Any weighted score with top-N-per-day.** Looked strong in sample and had
  zero edge out of sample; random N-per-day already earns ~0.4 points from day
  weighting alone.

**Two per-strategy exceptions:**

- **S4 wants the opposite volume rule** — a single tower is +3.94% *better*
  there. Do not apply rule 1 to S4.
- **S3** is 54% of signal volume, nets −0.95% per trade and has four times
  worse capital efficiency than any other strategy.

**Still unvalidated:** everything above is 161 fixture symbols over two years,
and the filter does most of its work in the up year (z=+7.6 one direction,
+2.0 reversed), so part of it may be a momentum filter rather than selection
skill. Say so when it matters.

## Before you start: what this engine cannot do

1. **The 3% stop is out of reach.** His entry is a three-scale confluence —
   daily at the 10 EMA = hourly at the 50 EMA = 15-minute at the 200 MA — and
   he enters on the last. Our candle store is daily only. Anything built here
   is his weekly-STF 6% case at best.
2. **Every threshold is ours.** He refuses to give numbers: "Do not make it a
   formula. If you do, you are in trouble." Only three constants come from the
   source — the 20-day turnover lookback, the 10/20/50/200 EMAs, and the 50%
   counter ratio.
3. **Nothing here is wired into the live scan.** S1–S5 select and score exactly
   as before.

## Procedure

Apply the three-condition filter above. Then, for anything that survives, use
the concepts below to *explain and rank* — not to reject, since gating on them
was measured and failed.

### Reference concepts (for reasoning, not gating)

- **Event on the LHS** — an MA crossover that survived the following
  contraction. Lecture 7's discriminator. Good explanation, no measured edge.
- **Containment / upper half** — the contraction inside the high of the
  expansion-ending candle, in the upper half of the leg. His most emphatic
  rule; no measurable effect on our signals.
- **EMA separation** — 10 clearly apart from 20, not intermingled.
- **Pivot quality and risk distance** — still the right way to *place* a stop,
  just not to rank candidates.
- **Relativity** — judge the move against what the stock has already done.
  After a large move expect the 20 or 50, not the 10.

## For each candidate you report

1. **Verdict** — pass / reject, and which gate.
2. **Rank and why** — the specific signals that placed it there.
3. **Best entry area** — demand zone, or the 10>20 cross with a close above the 10 EMA.
4. **Structural stop** — below which pivot, and the resulting risk %.
   If no quality pivot exists, say so: **no definable stop means skip**, regardless of
   how good the price looks.
5. **Add-on areas** — successive contractions, each with its own stop. Not adding into
   strength.
6. **Exit conditions** — decisive close below 10 EMA; the engulfing down candle; lower
   circuits; pivot break once extended.
7. **Uncertainty** — flag every approximation and every missing input by name.

## Quick reference

| Concept | Meaning |
|---|---|
| TTF / STF / ETF | Trend (monthly+weekly) / Setup (daily) / Entry (hourly→5m) |
| DNA | This stock's typical single-candle % and full up-move %, on this timeframe |
| Relativity | Judge the move against what the stock has already done |
| Event | An MA crossover on the LHS that survived its contraction |
| DC | Demand Candle — its low is the pivot |
| ILHS | Immediate left-hand side — the bars just left of the entry |
| VCC | Volatility contraction candle — small body at the MA |
| Expansion / contraction | Buy in contraction, never in momentum |
| Single tower vs cluster | One isolated volume bar = reject; several adjacent = good |

## Things he explicitly refuses

Do not reintroduce these: buying above the high of the bar; arbitrary stops at a
moving average with no evidence; 1% stops (slippage eats them); pilot or test positions;
market-regime labelling; chasing a setup that is not at your price; and converting any
observation into a rigid formula.

## Reference files

| File | Read when |
|---|---|
| `references/trader_methodology.md` | Full methodology and reasoning |
| `references/trader_rulebook.md` | Numbered rules with evidence class and citations |
| `references/volume_liquidity_spec.md` | Volume and turnover — incl. the three-tools question |
| `references/stock_selection_engine.md` | The funnel in detail |
| `references/entry_engine.md` | The bar-by-bar entry sequence |
| `references/exit_engine.md` | Exit triggers and the tranche model |
| `references/risk_engine.md` | Stops, sizing, charges |
| `references/backtest_spec.md` | Validation design — read before claiming any edge |
| `references/research_gaps.md` | What is unknown |
| `references/case_studies_addendum.md` | The two PDFs: CB = Committed Buyers, the three-scale confluence, the 10/6/3% stop ladder |
| `references/findings_run2.md` | Why the hard-gate stack was dropped |
| `references/findings_entry.md` | Why entry timing was dropped |
| `references/findings_ranker.md` | The filter that works, and the in-sample trap that nearly shipped |
| `references/universe_audit.md` | "NSE All Cash (~2000)" is 9,922 names, 73% not equity |

`scripts/calculations/features.py` implements the deterministic features only.
