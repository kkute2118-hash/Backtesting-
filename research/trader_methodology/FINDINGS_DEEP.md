# Deep-history run — the CB gate does not survive five years

Supersedes `FINDINGS_FULL_STORE.md` on the one rule that file kept.

## What changed about the test

`FINDINGS_FULL_STORE.md` ran on 448 symbols and, because
`load_scan_dataset()` defaults to a 1,000-day window, every signal it produced
landed in **2025–2026**. Two years cannot separate an edge from a regime. The
window is now `LOOKBACK_DAYS = 2200` and the run was repeated on 389 symbols
carrying 1,100+ bars each: **117,282 signals, 2022–2026**.

Both tests below are restricted, exactly as before, to **live-equivalent**
signals — those already past the ₹40 cr entry-filter floor, because nothing
below it can reach a live scan. 37,478 of the 117,282 qualify.

## The result

Within-day matched test: on each date, mean return of the candidates the gate
keeps minus mean return of the candidates it rejects. This is the control that
removes any benefit from merely being active on a good day.

| year | days | n kept | mean diff | t |
|---|---|---|---|---|
| 2022 | 132 | 338 | **−4.049%** | **−6.53** |
| 2023 | 187 | 451 | +0.897% | +1.15 |
| 2024 | 249 | 1,444 | −0.110% | −0.24 |
| 2025 | 187 | 345 | −0.531% | −0.83 |
| 2026 | 162 | 585 | +2.184% | +3.06 |
| **ALL** | **917** | **3,163** | **−0.152%** | **−0.52** |

Positive in two years of five, flat overall, and the one large effect is
negative.

The same test on the old two-year sample, run the same way for comparison:
2025 +1.83 (t +1.74), 2026 +0.42 (t +0.68), ALL +1.05 (t +1.81). Directionally
what was reported, weaker than the permutation z-scores implied, and **2025
flips sign** between the two symbol samples — the deep sample only admits names
with 1,100+ bars, which skews older and larger.

## Pooled comparison, and why it disagrees

| strategy | n kept | mean kept | n rejected | mean rejected | edge |
|---|---|---|---|---|---|
| ALL | 3,163 | +1.383% | 34,315 | +0.848% | **+0.535%** |
| S1 | 1,376 | +0.741% | 13,235 | +0.442% | +0.298% |
| S2 | 93 | −0.093% | 1,146 | +1.230% | −1.322% |
| S3 | 1,432 | +1.559% | 18,958 | +1.068% | +0.492% |
| S4 | 215 | +5.073% | 575 | +2.401% | +2.671% |
| S5 | 47 | +0.876% | 401 | +0.567% | +0.309% |

Pooled says +0.535%; matched says −0.152%. The gap **is** the finding: the
gate's apparent benefit is *which days it is active on*, not *which stock it
picks on a given day*. That is a market-timing claim, and two positive years
out of five is not support for one.

## Decision

`APPLY_FORWARD_TRADER_FILTER = False`.

Second reason, independent of the statistics: the gate passes **8.4%** of
live-equivalent signals, and a rejected candidate never gets a forward record.
Leaving it on removes the forward test's own control — "would the skipped ones
have done better?" stops being answerable inside the book. With it off, every
candidate is enrolled and the CB subset can still be measured retrospectively
whenever we want. Off is strictly more informative.

The module, its 11 tests and the `skip_reason` plumbing all stay. One flag
turns the gate back on.

## What this leaves

The forward-test selection is now exactly the frozen pipeline:
safety gate → strategy rules → ₹40 cr turnover floor → ATR ≥ 4% (S1/S2/S3/S5)
or sector rank ≤ 3 (S4) → one position per stock. See
`FORWARD_SELECTION_CRITERIA.md`.

## Also settled by this run

**Score does not rank.** Decile means over 117,282 signals:

```
q     0      1      2      3      4      5      6      7      8      9
mean 0.86   1.71   1.73   2.19   0.83   0.91   1.69   0.55   1.12   1.70
```

Non-monotonic, and top-3-per-day by score beat a random 3-per-day draw by
+0.29% against a draw sd of 0.141 — inside two sd once you account for having
tried four values of N.

**Per-year, all signals:** 2022 +0.33%, 2023 +5.84%, 2024 −0.39%,
2025 −1.12%, 2026 +1.67%. This is the answer to the money-flow question that
prompted the deep run: a measure that looked like an edge across 2025 and 2026
was reading the difference between a bad year and a good one. Any rule fitted
on two years of this series will do the same.

**Per-strategy, all signals, top-3/day by score:** S4 +4.50% (n=213) and
S5 +3.87% (n=50) against S1 +0.37% and S2 +0.68% — consistent with the
existing `STRATEGY_SLOT_PRIORITY` of S4 first, then S5. Ranking *strategies*
keeps working; ranking *candidates* keeps failing.
