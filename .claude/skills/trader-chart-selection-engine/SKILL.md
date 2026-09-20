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

## Before you start: what this engine cannot do

State these when they matter, rather than papering over them.

1. **The blue-candle criterion is missing.** The author selects on candle colour from
   an overlay he never defines (RG-01). A first-order filter is absent.
2. **Almost every threshold is fitted by us, not stated by him** (RG-02). Say so when
   you use one.
3. **Candle quality is an approximation** (RG-03). `body/range` is a proxy, not his
   rule.
4. **None of this is validated yet.** Until `references/backtest_spec.md` has been run
   and passed, every verdict is a hypothesis. Do not present output as a tested edge.

## Procedure

Work the gates in order. Stop at the first hard failure and say which gate failed.

### Gate 1 — Liquidity (hard)
20-day average turnover in rupees crore. **20 days, not 21** — that is the author's
period, explicit in the transcripts.
- Below ~₹3 cr/day: reject, he calls this "extremely less".
- ~₹80 cr/day and up: he calls this "pretty healthy".
- Rising average turnover through the expansion is confirmation.

### Gate 2 — Event and EMA structure (hard)
- An MA crossover on the left-hand side: 10>20, 10>50, 20>50, or all four converging.
  This is his **primary filter**.
- **The crossover must have survived the following contraction.** A cross that reverted
  is not an event. This is the single strongest discriminator in the corpus.
- EMA10 must be **clearly separated** from EMA20. Intermingled means range means reject.
- 10 > 20 > 50 on the daily.
- Strong optional filter: weekly 10>20 and 20>50. He skips the stock without it.
- Bonus: all four EMAs compressed at one price. Rare, and the strongest setup he shows.

### Gate 3 — Structure (hard where computable)
- **Containment**: the whole contraction stays inside the high of the candle that ended
  the expansion. He calls this "one of the most important points that I'll ever give
  you."
- **Upper half**: the contraction sits in the upper half of that range.
- **Proportionality**: contraction time and depth must match the expansion. A 60% move
  in 6 days is not resolved by 8 days of pause.
- **Counter rule**: any red candle larger than the expansion candles must be countered
  by a later up candle retracing ≥50%, ideally engulfing. Candles hovering below 50% of
  a big red candle mean selling pressure on the ILHS — do not buy.
- **Volume cluster**, not a single tower. He rejects charts with one big volume bar and
  average volume either side.
- Not forming in the lower half of the prior down move.

### Gate 4 — Event risk (hard)
No earnings imminent, unless already deep in profit. He will not enter in anticipation
of earnings.

### Rank the survivors
**Primary: risk distance** — entry to structural pivot, ascending. This is his own
logic: tighter stop means bigger position means the trade is worth the slot. If you use
one signal, use this.

Secondary: MA proximity (candle opens near the MA *and* closes near the MA is his best
case), candle quality, pivot quality, volume cluster score, turnover trend, DNA-to-risk
ratio, contraction tightness, extension penalty.

**Emit 2-3 candidates, not a threshold-passing list.** His position sizing (35-40%
starting) structurally limits concurrent positions, and opportunity cost is an explicit
rejection reason: "if I have stocks which I showed you at number one, number two, why
would I go for this one?"

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

`scripts/calculations/features.py` implements the deterministic features only.
