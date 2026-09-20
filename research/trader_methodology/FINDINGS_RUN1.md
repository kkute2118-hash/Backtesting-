# Findings — run 1 (golden fixture)

**Status: preliminary and not sufficient to act on.** Run on the golden fixture —
161 symbols, 679 bars, only 2 calendar years — because the 2000-stock build was
still downloading. No transaction costs, no train/test split. Numbers here will
move on the real store.

Every arm trades the **same** S1–S5 signal set. Scanner logic untouched.

---

## Headline

| Arm | n | win | mean % | mean R |
|---|---|---|---|---|
| BASELINE, all signals | 22,530 | 29.3% | −0.06% | −0.009R |
| MODEL A, hard gates passed | 241 | 28.6% | +0.35% | **+0.049R** |
| gates rejected | 22,289 | 29.3% | −0.07% | — |
| MODEL C, gates + author exit | 241 | 27.0% | −0.55% | −0.035R |

**R-multiples are the fair comparison**, not raw %: the two exits risk different
amounts per trade, and a tighter stop buying more size is the entire basis of his
claim that the edge is in the entry price.

**The falsification check passes.** Accepted candidates beat rejected ones by
+0.41%/trade. The author's own test — "if the trades you left all are moving up and
the ones I'm picking are all coming down, then there is a big, big, major fault in
your framework" — does not fire. The funnel is at least pointed the right way.

**But the edge is small and the pass criteria in `BACKTEST_SPEC.md` are not met:**

- **Only 2 years available.** 2025 was −0.35%, 2026 +1.00%. The improvement is
  carried by one year. Criterion 3 (positive in ≥4 of 5 years) cannot even be
  evaluated.
- **Only 1 of 5 strategies improves.** Criterion 4 fails outright — see below.
- **n = 241** from 22,530. A 1.1% pass rate is thin, and near the useful floor.

---

## The gates hurt the strategies that were already working

| Strategy | all signals | gates passed | verdict |
|---|---|---|---|
| S1 | +0.14% (n=8,809) | **−0.62%** (n=137) | worse |
| S2 | −0.31% (n=863) | **+2.11%** (n=50) | much better |
| S3 | −0.36% (n=12,127) | −1.61% (n=2) | effectively eliminated |
| S4 | **+3.00%** (n=413) | +1.03% (n=43) | worse |
| S5 | +2.35% (n=318) | +2.33% (n=9) | unchanged |

S4 and S5 were already the best performers and the gates made S4 worse and left S5
alone. The whole aggregate improvement comes from S2. **A layer that only helps one
strategy is not the general second stage we set out to build**, and applying it
uniformly across all five would destroy value on S4.

---

## What actually carries information

Testing the components individually is far more informative than the gate stack.

### CB purity works — this is your concept, and it measures

All signals, sorted into quartiles by the CB purity of their expansion:

| CB purity quartile | n | mean return |
|---|---|---|
| Q1 (lowest) | 5,937 | **−1.06%** |
| Q2 | 6,828 | −0.74% |
| Q3 | 4,944 | **+1.63%** |
| Q4 (highest) | 4,821 | +0.40% |

The bottom half is clearly worse than the top half — a spread of roughly 1.7
percentage points between Q1 and Q3. It is not monotonic at the top, which is worth
understanding rather than smoothing over.

### Volume cluster vs single tower works

| | n | mean return |
|---|---|---|
| Not a single tower | 18,452 | +0.06% |
| **Single tower of volume** | 4,078 | **−0.62%** |

A 0.68-point gap, on a large sample, from a rule stated plainly in lecture 1. This
is the cleanest confirmation of a transcript rule so far.

### Turnover is NOT monotonic — the highest quartile is the worst

| Turnover quartile | n | mean return |
|---|---|---|
| Q1 (lowest) | 5,633 | −0.55% |
| Q2 | 5,632 | +0.31% |
| Q3 | 5,632 | **+0.88%** |
| Q4 (highest) | 5,633 | **−0.89%** |

This matters for how the liquidity gate should be built. "More turnover is better"
is wrong on this data — the best band is upper-middle, and the most liquid names are
the worst performers. It is at least consistent with the author calling ₹80 cr
"pretty healthy, **not the best**" and insisting adequacy is relative to account
size rather than absolute.

---

## Two anomalies that contradict the methodology

**1. The gates select for *wider* stops, not tighter.**
Median pivot stop: 4.83% across all signals, **6.01%** among gates-passed. The
methodology predicts the opposite — better entries should mean tighter stops. Most
likely the containment and upper-half gates favour setups sitting near the top of a
contraction, which is further from the last pivot low. Needs investigating; it
undercuts the main reason to want this layer.

**2. The gates select *against* CB purity.**
Mean CB purity: 0.217 among passed, 0.252 among rejected. The hard gates and the
single best soft signal are pulling in opposite directions — a design fault in the
gate stack, not in either component.

---

## On MODEL C (the author's exit)

It underperforms here (−0.035R vs +0.049R), but the comparison is not clean and
should not be read as a verdict on his exit:

- **The entry is not his.** MODEL C applies his exit to *our scanner's* entry bar.
  He enters at the point-5 confluence or the 10>20 cross, not on an S1–S5 trigger.
  This tests a hybrid that is neither system.
- **The tranche model is missing.** Selling 74–80% into the first strong expansion
  and trailing the rest is where much of his stated return comes from. Not yet
  implemented.
- It does cut losses hard: median loss −0.33R against baseline's −1.00R, and only
  51 of 241 exits hit the stop — 190 left on the 10-EMA rule. Median hold 6 bars
  against baseline's 18. It is a fast, small-loss exit that also truncates winners.

---

## What this changes

1. **Do not ship the gate stack as specified.** It fails its own pass criteria and
   degrades S4.
2. **Re-scope toward ranking, not gating.** CB purity and single-tower carry signal
   as continuous measures across 22,530 samples; the hard gates reduce to 241 and
   lose the strategies that worked. MODEL B (rank, don't reject) is now the more
   promising arm and has not been run.
3. **Fix the stop-width anomaly before anything else** — a layer that widens stops
   defeats the point you care about most.
4. **Rerun on the full store.** Two years and 161 symbols is not enough to conclude
   anything; the 2000-stock build exists precisely for this.
