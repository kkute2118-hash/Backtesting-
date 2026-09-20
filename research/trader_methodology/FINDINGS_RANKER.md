# Findings — filtering works, ranking does not

Third construction tried. Gates failed (run 2), entry timing failed
(FINDINGS_ENTRY), and **a plain filter on three components works** — while the
weighted score with top-N-per-day, which looked best in sample, has no edge out
of sample at all.

Golden fixture: 161 symbols, 22,530 signals, 2025 and 2026.

---

## The trap I walked into, recorded because it nearly shipped

The weighted score, taking the top 3 per day, looked convincing in sample:

| | n | mean | edge over random 3/day |
|---|---|---|---|
| Top 1/day | 417 | +1.34% | **+1.24%** (~3.0 sd) |
| Top 3/day | 1,251 | +0.91% | **+0.69%** (~3.2 sd) |

Three standard deviations over a random control of the same size. I was about
to report it.

**Out of sample it is worth nothing:**

| bands fitted on 2025, applied to 2026 | |
|---|---|
| top 3/day by score | +0.958% |
| random 3/day | **+1.018%** |
| edge | **−0.061% (−0.2 sd)** |

And with the original hand-set bands, the 2026 edge is **−1.93%** — actively
harmful.

Two separate mistakes, both worth naming:

1. **The bands were read off the same data I then measured on.** Exactly the
   best-of-N failure `BACKTEST_SPEC.md` §6 warns about, which I wrote and then
   walked into.
2. **Top-N-per-day is the wrong construction.** Random 3/day returns +1.079% in
   2026 against +0.691% for all signals. Picking any three per day is worth ~0.4
   points on its own, purely from day weighting. That effect is larger than the
   signal, so it swamps it — and a naive comparison against "all signals" would
   have credited it to the ranking.

---

## What survives: the components, as a plain filter

First, which components keep their sign across both years, with no fitting:

| component | 2025 gap | 2026 gap | holds |
|---|---|---|---|
| not a single tower | +0.880% | +0.472% | **yes** |
| CB purity ≥ 0.35 | +0.645% | +0.970% | **yes** |
| CB purity in [0.35, 0.75] | +0.559% | +1.124% | **yes** |
| turnover in [60, 400] cr | +1.266% | +1.158% | **yes** |
| cluster fraction ≥ 0.30 | −0.727% | +0.733% | no — flips |
| turnover ≥ 40 cr (plain floor) | −0.114% | +1.112% | no — flips |

Note the two that flip. A plain turnover *floor* is not stable; a turnover
*band* is. That matches the earlier quartile finding where the top turnover
quartile was the worst performer, and it matches the author calling ₹80 cr
"pretty healthy, **not the best**".

### The filter

```
keep if:  NOT a single tower of volume
      AND CB purity between 0.35 and 0.75
      AND 20-day average turnover between 60 and 400 crore
```

No weights. No top-N-per-day. No score. Just keep or drop.

| | kept | dropped | gap | kept R |
|---|---|---|---|---|
| 2025 | +0.596% (n=1,149) | −0.790% | +1.386% | +0.085R |
| **2026** | **+2.522%** (n=1,528) | +0.361% | **+2.161%** | **+0.360R** |

Against a random subset of **the same size** — the control that matters, since
it removes both the day-weighting effect and the smaller-sample effect:

| | kept | random same-size | z |
|---|---|---|---|
| 2025 | +0.596% | −0.640% (sd 0.318) | **+3.9** |
| 2026 | +2.522% | +0.683% (sd 0.263) | **+7.0** |

---

## Properly held out

The band edges above had still seen both years. So: choose them on 2025 alone
(best of 36 combinations, deliberately optimistic in-sample), then apply
untouched to 2026.

Chosen on 2025: CB purity **[0.30, 0.70]**, turnover **[100, 400]** cr.
In-sample 2025 gap +1.453% — inflated by construction, ignore it.

**2026, never seen by the band selection:**

| | n | mean |
|---|---|---|
| kept | 1,637 | **+2.446%** (R **+0.349**) |
| dropped | 8,356 | +0.348% |
| gap | | **+2.098%** |
| random same-size | | +0.697% (sd 0.229) |
| **z** | | **+7.6** |

And every strategy improves on the held-out year:

| | all 2026 | filtered |
|---|---|---|
| S1 | +1.10% | **+2.79%** |
| S2 | +0.72% | **+4.90%** |
| S3 | +0.04% | **+1.07%** |
| S4 | +3.90% | **+6.56%** |
| S5 | +3.57% | **+5.73%** |

5 of 5 — against the ≥3 of 5 criterion in `BACKTEST_SPEC.md`.

---

## The caveat that stops this being a finished result

**The reverse direction is much weaker.** Bands chosen on 2026 and applied to
2025 give z = **+2.0**, not +7.6.

2025 was a losing year overall (−0.663% mean) and 2026 a winning one (+0.691%).
The filter does far more work in the good year. That is consistent with it
being partly a **momentum or beta filter** rather than pure selection skill —
it keeps the names that participate when the market pays, and in a year that
does not pay it only reduces the damage.

That is still useful. It is not the same claim as "this picks better stocks in
all conditions", and it should not be reported as one.

---

## Where this leaves things

**What works:** a three-condition filter, all three conditions taken straight
from the source material — volume cluster vs single tower (lecture 1), CB
purity as a band (the user's definition plus the PDFs' glossary), and turnover
as a band (lecture 12's 20-day average).

**What does not:** the hard-gate stack, entry timing, and any weighted score
with top-N-per-day.

**Still owed before this goes anywhere near live:**
1. Transaction costs, including non-deductible STT — lecture 13's whole point,
   and untested here.
2. The full store instead of 161 fixture symbols and two years.
3. Permutation and circular-shift nulls, not just the random-subset control.
4. A third year, so "holds in both directions" can be tested properly rather
   than inferred from one asymmetric pair.

---

## Costs (added after the fact — lecture 13's argument, tested)

The author spends half of lecture 13 arguing that Indian charges can invert a
strategy, because **STT is not deductible** against short-term capital gains.
His worked example turns a ₹4 lakh gain into a ₹2.8 lakh loss. A backtest of
his method that ignores costs is testing the wrong thing.

Applied to the held-out 2026 result, at ₹35,000 a trade (his stated 35–40% of
a ₹1 lakh book):

| slippage | round trip | kept, net | dropped, net | all signals, net |
|---|---|---|---|---|
| optimistic (0.05%/side) | 0.393% | **+2.053%** | −0.045% | +0.298% |
| realistic (0.15%/side) | 0.593% | **+1.853%** | −0.245% | +0.098% |
| pessimistic (0.30%/side) | 0.893% | **+1.553%** | −0.545% | **−0.202%** |

**Costs make the case for the filter stronger, not weaker.** At realistic
slippage the unfiltered strategy nets +0.098% a trade — indistinguishable from
zero — and at pessimistic slippage it is **negative**. The filtered set clears
+1.5% net in every scenario.

That is precisely his argument, reproduced: the edge has to be big enough to
pay the charges, and a strategy that trades everything the scanner finds is
not.

Cost breakdown per round trip at realistic slippage:

| | ₹ | % |
|---|---|---|
| slippage | 105.00 | 0.300% |
| **STT (non-deductible)** | **70.00** | **0.200%** |
| brokerage (capped ₹20/order) | 21.00 | 0.060% |
| stamp duty | 5.25 | 0.015% |
| GST | 4.17 | 0.012% |
| exchange + SEBI | 2.15 | 0.006% |
| **total** | **207.57** | **0.593%** |

Slippage dominates, and it is the one figure here that is an assumption rather
than a published rate — which is why three scenarios are shown rather than one.
The author says so himself: *"1% at times goes in buying and selling, combined
slippage"* on a good position size, which is worse than even the pessimistic
row above.

**Caveat on trade count:** 1,637 filtered signals in 2026 is signals, not
positions. With 3 concurrent slots and a median 18-bar hold, a year is roughly
40–50 actual trades, so the per-trade net is the number that matters rather
than the signal count. A full portfolio simulation with slot contention is
still owed.

---

## Nulls (added) — the effect is real but smaller than the headline

`BACKTEST_SPEC.md` §6 asks for permutation and circular-shift nulls, not just
a random-subset control. Running them decomposes the +2.098% held-out gap, and
the decomposition matters.

| null | what it holds fixed | null mean | z |
|---|---|---|---|
| 1. plain label shuffle | nothing | −0.001% | **+7.1** |
| 2. **shuffle within each day** | **the number kept per day** | **+0.882%** | **+4.3** |
| 3. circular shift per symbol | each series' own time structure | −0.049% | **+2.8** |

**Null 2 is the one that matters**, and it answers the doubt raised above about
this being a momentum filter. It keeps the count kept per day identical and
reshuffles *which* stocks those are, so any advantage that comes merely from
being active on good days is present in the null too.

Its null mean is **+0.882%**, not zero. That is the day-selection component
made visible: days on which many signals pass the filter are simply better
days. So of the +2.098% raw gap:

- **~0.88 points (42%) is choosing better days**
- **~1.22 points (58%) is choosing better stocks within a day**, at z = +4.3
  across 175 days with within-day contrast

Both are worth having — being active when the market pays is a real effect,
not a cheat — but they are different claims and the headline conflated them.
**The genuine stock-selection edge is roughly 1.2 points, not 2.1.**

Null 3 breaks the alignment between the components and returns while keeping
each series' own persistence intact, which is the test that matters for
turnover (a highly persistent series). It survives at **z = +2.8** — clearly
positive, and clearly weaker than the naive +7.1.

### Revised summary of the result

| claim | support |
|---|---|
| the kept group beats a random draw | z = +7.1 |
| ...beats a random draw *on the same days* | z = +4.3 |
| ...is not an artefact of persistence | z = +2.8 |
| net of realistic costs | +1.853% vs +0.098% unfiltered |
| holds on all five strategies | yes, held-out year |

The result stands. Its size should be quoted as **~1.2 points of stock
selection**, with the rest attributable to when it is active.
