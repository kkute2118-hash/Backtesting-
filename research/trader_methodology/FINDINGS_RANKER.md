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
