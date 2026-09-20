# Findings — run 2 (golden fixture), and a correction to run 1

**This supersedes `FINDINGS_RUN1.md`. Run 1's headline was wrong.**

Same data as run 1 — golden fixture, 161 symbols, 679 bars, two calendar years,
22,530 S1–S5 signals, no costs, no train/test split. The difference is two bug
fixes in the layer.

---

## The correction

Run 1 reported the hard gates at **+0.049R** against a **−0.009R** baseline, with
the falsification check passing. That came from a misimplemented rule.

**What was wrong.** Lecture 4 says the contraction should sit "in the upper half of
**the contraction** — that adds to the deep versus shallow [question]". I
implemented it as the upper half of the *expansion-ending candle's own range*. On a
large expansion bar that demands price sit far above the contraction low, which is
what produced run 1's other anomaly: the gates selecting for **wider** stops than
the ungated set, backwards from everything the methodology claims.

**What changed.** `upper_half` now measures retracement of the expansion *leg*
(shallow ≤ 50%), which is what "deep versus shallow" means. And `pivot_low` now
searches only within the contraction instead of up to 60 bars back into the
expansion — the stop goes below the demand area of the pullback being traded, not
below whatever low sits two months back.

**The stop-width anomaly is fixed:** gates-passed median stop is now 4.07% against
4.60% for all signals — tighter, as the method predicts.

**And the result inverted:**

| Arm | run 1 | run 2 (corrected) |
|---|---|---|
| BASELINE all signals | −0.009R | −0.009R |
| MODEL A gates passed | **+0.049R** (n=241) | **−0.139R** (n=796) |
| Falsification check | passes | **INVERTED** |

Accepted candidates now *underperform* rejected ones by 0.94%/trade. By the
author's own test — "if the trades you left all are moving up and the ones I'm
picking are all coming down, then there is a big, big, major fault in your
framework" — the gate stack fails.

Every strategy is worse under the gates, and S5 passes nothing at all:

| Strategy | all signals | gates passed |
|---|---|---|
| S1 | +0.14% | −1.26% (n=475) |
| S2 | −0.31% | −0.48% (n=141) |
| S3 | −0.36% | −0.93% (n=112) |
| S4 | +3.00% | −0.02% (n=68) |
| S5 | +2.35% | — (n=0) |

**Conclusion: the gate stack does not work.** Run 1's positive was an artifact.

---

## Two rules that do not survive contact with the data

### Containment does nothing

The author calls this "one of the most important points that I'll ever give you in
your trading". Measured in isolation across all 22,530 signals:

| | n | mean return |
|---|---|---|
| contained = True | 13,005 | −0.066% |
| contained = False | 9,525 | −0.058% |

No effect. This is the single most emphatic claim in the corpus and it has no
measurable predictive power on our scanner's signals.

`upper_half`, corrected, is weakly positive in the right direction: −0.015% passing
against −0.113% failing. Small, but real.

### Tighter stops predict WORSE trades, not better

This is the finding that matters most, because stop minimisation is the part of the
methodology most worth wanting.

| Risk-distance quartile | n | mean % | mean R |
|---|---|---|---|
| Q1 tightest | 4,904 | **−0.303%** | **−0.178R** |
| Q2 | 4,904 | −0.350% | −0.106R |
| Q3 | 4,903 | −0.018% | −0.033R |
| Q4 widest | 4,902 | **+0.528%** | −0.004R |

Monotonic, and the wrong way round — in percentage *and* in R, so it is not an
artefact of the normalisation. The tightest stops lose most.

**Why this is not necessarily a refutation of the author.** A tight stop is more
easily taken out by noise, and he has two defences that this backtest does not
model: he re-enters after a stop-out ("then you enter it again — because if you
don't, then you will not make that system work for you"), and he sizes up on the
tight stop so the winners pay for the whipsaws.

**But it does mean one thing clearly:** on *our scanner's* entry bars, ranking by
tight stop is actively harmful. The edge he gets from a tight stop comes from
*where he chooses to enter*, not from the stop being tight. We are applying the
stop to an entry he would not have taken. `rank_score()` currently weights risk
distance highest — that is now shown to be backwards here and must change.

---

## What survives — and it is the part you named

These are measured across all 22,530 signals, independent of the gate stack, so the
bug fixes did not move them.

### CB purity carries real signal

| CB purity quartile | n | mean return |
|---|---|---|
| Q1 (lowest) | 5,937 | **−1.06%** |
| Q2 | 6,828 | −0.74% |
| Q3 | 4,944 | **+1.63%** |
| Q4 (highest) | 4,821 | +0.40% |

A ~1.7-point spread between the bottom and third quartiles. Not monotonic at the
very top, which is worth understanding rather than smoothing. This is the strongest
single signal found, and it exists only because the CB definition was supplied.

### Single tower of volume is a genuine disqualifier

| | n | mean return |
|---|---|---|
| Not a single tower | 18,452 | +0.06% |
| Single tower | 4,078 | **−0.62%** |

A 0.68-point gap on a large sample, from a rule stated plainly in lecture 1.

### Turnover is not monotonic — the top quartile is the worst

| Turnover quartile | n | mean return |
|---|---|---|
| Q1 lowest | 5,633 | −0.55% |
| Q2 | 5,632 | +0.31% |
| Q3 | 5,632 | **+0.88%** |
| Q4 highest | 5,633 | **−0.89%** |

A floor is right; a "more is better" ranking is wrong. The best band is
upper-middle. Consistent with the author calling ₹80 cr "pretty healthy, **not the
best**" and insisting adequacy is relative to account size.

---

## Where this leaves the work

**Stop building gates.** Three of them (containment, event, separation) either do
nothing or actively hurt, and stacking them produces an inverted funnel.

**Build a ranker from the three measures that work.** CB purity, volume cluster,
and a turnover *band* rather than a floor. All three are continuous, all three are
measured on 22,530 samples rather than 241, and all three come straight from the
transcripts.

**Drop risk distance from the ranking** until the entry timing is his rather than
the scanner's. Its sign is wrong here and weighting it first was a mistake.

**Caveats that still apply to everything above:** two years, 161 symbols, no
transaction costs, no train/test split, and the whole sample used for every
measurement. These are directional findings on a small fixture, not validated
results. The 2000-stock build exists to replace this.
