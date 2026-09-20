# STOCK_SELECTION_ENGINE

The answer to the master prompt's core question: **how to reduce ~100 scanner
candidates to a handful of high-quality setups.**

This engine runs strictly **after** S1–S5. Under the ABSOLUTE RULE it changes nothing
about what the scanners select or score. It only re-orders and filters their output.

---

## 1. Design constraint: the author's own refusal

Before any funnel, the tension has to be named. The author explicitly rejects the thing
we are being asked to build:

> "you just cannot blindly make it a pattern or a formula" — lecture 4
> "**Do not make it a formula. If you do, you are in trouble.**" — lecture 7
> "I've seen people make formulas — the gap should be more in 20 and 50 — **but that's
> not the way.**" — lecture 7

He is not saying the observations are wrong. He is saying they are **contextual**: the
same candle is good or bad depending on what sits to its left and which cycle the
higher timeframe is in.

**How this document resolves it.** Two tiers, never mixed:

- **Tier 1 — Hard gates.** Only rules the author states as requirements and that are
  fully computable from OHLCV. These may reject a candidate outright.
- **Tier 2 — Soft ranking.** Approximations of his quality judgements. These may
  **re-order** candidates but never reject them.

If a candidate fails only Tier 2, it ranks low but stays visible — which mirrors the
author's own "left" category (declined on quality, outcome accepted) rather than
pretending the judgement is mechanical.

---

## 2. Gate 1 — Liquidity (EXPLICIT, hard)

The author's own first check, before he looks at the chart at all.

```
PASS if avg_turnover_20d >= TURNOVER_FLOOR_CR
```

- Lookback: **20 trading days** (L-01, EXPLICIT — lines 10074, 10091).
- Floor: **no transcript value.** Observed band: ₹2.5 cr rejected, ₹80 cr "pretty
  healthy". Our platform's existing ₹40 cr/day floor sits inside that band and is not
  contradicted by anything in the corpus.

**Recommendation:** start at our existing ₹40 cr so this gate is a no-op against the
current entry-evidence filter, then sweep it in the backtest. That way any measured
improvement is attributable to gates 2–4 rather than to a liquidity change we smuggled
in.

Optional, DERIVED: reject where `avg_turnover_20d` is **falling** through the
expansion (L-07 inverted).

---

## 3. Gate 2 — Event and EMA structure (EXPLICIT, hard)

All four conditions must hold on the STF (daily).

| Condition | Rule | Notes |
|---|---|---|
| An MA crossover occurred on the LHS within a lookback window | E-02, E-03 | 10>20, 10>50, 20>50, or all four converging |
| That configuration **survived** the following contraction | E-06 | The lecture-7 discriminator — the strongest computable idea in the corpus |
| `abs(EMA10 − EMA20)/close >= MIN_EMA_SEP` | E-07 | Rejects the "intermingled" case |
| `EMA10 > EMA20 > EMA50` at the candidate bar | E-03 | |

**Optional strong filter (EXPLICIT, lecture 8):** require the *weekly* `EMA10 > EMA20`
and `EMA20 > EMA50`. The author states this as a personal hard rule —
"for me to take a trade I need 10 above 20, 20 above 50. **If I don't get that, I'm more
than happy to skip this stock.**" Worth testing as a separate ablation arm: it is
likely to be one of the highest-selectivity filters available.

**Bonus, not a gate (EXPLICIT, lecture 7):** flag candidates where all four EMAs are
compressed within a narrow band. This is the configuration the author describes as
requiring no further work from the stock, and it preceded the largest move in his
worked examples. Use it as a **ranking boost**, not a filter — there will be very few
such candidates.

---

## 4. Gate 3 — Structure (EXPLICIT concepts, hard where computable)

| # | Condition | Rule | Computability |
|---|---|---|---|
| 3a | Contraction contained within the expansion-ending candle's high | K-01 | C — exact |
| 3b | Contraction low in the **upper half** of that candle's range | K-02 | C — exact |
| 3c | Contraction duration proportionate to expansion magnitude | K-05 | A — needs a ratio |
| 3d | No red candle in the contraction larger than the expansion candles, **unless countered** | K-11, P-04 | C — exact |
| 3e | A quality pivot exists on the ILHS → a definable stop | P-06 | A — needs a quality proxy |
| 3f | Volume cluster present, not a single tower | V-01, V-02 | A — needs an elevation multiple |
| 3g | Setup not in the lower half of a prior down move | K-12 | C — exact |

**3a and 3b are the highest-value gates in this document.** They are exactly stated —
"one of the most important points that I'll ever give you in your trading" — completely
unambiguous, and computable with no free parameters beyond identifying the
expansion-ending candle.

**3d** in code:

```python
big_red = red candles in the contraction where abs(pct) > max(expansion_candle_pct)
for candle in big_red:
    if not exists(later up candle with body >= 0.5 * candle.body):   # P-04
        REJECT
```

---

## 5. Gate 4 — Event risk (EXPLICIT, hard)

Reject candidates with earnings inside the next `N` sessions, unless already deep in
profit (lecture 12). For a fresh scan candidate, "already in profit" never applies, so
this is a simple exclusion.

`N` is not stated. Two sessions is a reasonable starting value and is itself a
parameter.

---

## 6. Tier 2 — Ranking the survivors

**Primary sort: risk distance.** `(entry − pivot_stop) / entry`, ascending.

This is the author's own logic, stated as a causal chain in lecture 10 — smaller stop
→ larger position → the trade is worth taking — and reinforced by the 7%→2% example in
lecture 12. If only one ranking signal is used, it should be this one.

**Secondary signals**, each normalised and weighted:

| Signal | Proxy | Class |
|---|---|---|
| Candle quality (expansion) | mean `body / (high − low)` over expansion bars | A — RG-03 |
| Pivot quality | pivot candle's `body/range`, counter ratio vs prior red | A |
| MA proximity (lecture 5 case 2) | `abs(open − MA)/MA` and `abs(close − MA)/MA`, both small | **C — exact** |
| Volume cluster score | fraction of expansion bars elevated | A |
| Turnover trend | slope of `avg_turnover_20d` across the expansion | **C — exact** |
| DNA-to-risk ratio | `DNA_expected_move / risk_distance` | C, given a DNA estimate |
| Contraction tightness | mean range of contraction bars / mean range of expansion bars | **C — exact** |
| Extension penalty | distance above the monthly EMA10, or months since the monthly event | C |
| Contraction number | penalise base 3+ | C |

Four of these are exact. The weighting across all of them has **no transcript basis**
and must be fitted — which means it must be fitted on a training period and evaluated
out of sample, per Section 34.

**Do not construct a 0–100 score and present it as the author's.** Section 28 of the
master prompt forbids a fake score, and the author's own refusal (G-01) forbids it more
directly. Report the component signals alongside any composite, and be explicit that
the composite is ours.

---

## 7. Hard cap on output

**EXPLICIT — the author treats selection as ranking against opportunity cost, not as
threshold-passing:**

> "the **opportunity cost** for picking up stocks like this turns out to be a lot when
> you compare the stocks which we have seen... and that is the reason this was not
> picked." — lecture 10

> "if I have stocks which I showed you at number one, number two, **why would I go for
> this one?**" — lecture 10

> "rather than chasing stocks like this at not your favourable price, it's better to
> actually look for stocks which are doing **this** right now." — lecture 12

So the engine should emit a **fixed small number of candidates** (the top N by rank),
not "everything above a threshold". With the author's stated position sizing of 35–40%
starting size, **N is structurally limited to 2–3 concurrent positions.**

This also matches our platform's existing forward-test constraint of one position per
stock, and the user's earlier stated intent of taking the best three trades at 25%
capital each.

---

## 8. What this engine cannot do

Stated plainly so it is not misrepresented downstream:

1. **It cannot reproduce the blue-candle criterion (RG-01).** The author counts blue
   candles and rejects stocks showing white candles in the expansion. We do not know
   what makes a candle blue. This is a first-order criterion and it is missing.

2. **Every threshold is ours.** The author supplies almost no numbers. Gate 1's floor,
   the EMA separation minimum, the volume elevation multiple, the contraction
   proportionality ratio — all fitted. Each is an overfitting opportunity and must be
   swept, not tuned to a single value.

3. **"Candle quality" is an approximation.** `body/range` is a reasonable proxy for
   "full body, minimal wick" but the author also weighs *where* the candle sits, what
   preceded it, and what the higher timeframe is doing. A scalar cannot capture that.

4. **Context-dependence is structurally lost.** Lecture 7's central lesson is that two
   visually identical candles produce opposite outcomes depending on context. A gate
   applied uniformly across candidates cannot express that. Gates 3a/3b and E-06
   capture *some* context; they do not capture all of it.

5. **It is unvalidated.** Nothing in this document has been tested. Section 30 makes
   backtesting mandatory before any claim, and Section 37 says: no data, no claim.

---

## 9. Expected behaviour (a hypothesis, not a result)

Given ~100 candidates from S1–S5:

| Stage | Expected survivors | Basis |
|---|---|---|
| After Gate 1 (liquidity) | ~60–90 | Our entry-evidence filter already applies a ₹40 cr floor, so this should be close to a no-op |
| After Gate 2 (event/EMA) | ~25–50 | The EMA-separation and event-survival conditions are genuinely selective |
| After Gate 3 (structure) | ~5–20 | Containment (3a/3b) should be the largest single reduction |
| After Gate 4 (earnings) | ~5–18 | |
| After top-N cap | **2–3** | Position sizing constraint |

**These numbers are a hypothesis to be measured, not a prediction.** The author's own
weekly scan produced 57 candidates in the week he describes, from which he took one
trade — a reduction of roughly 50:1. If our funnel produces a similar ratio, that is
weak corroboration; if it produces 30 candidates a day, something is wrong.
