# Findings — the full store overturns two of the three conditions

**This supersedes `FINDINGS_RANKER.md`.** The filter shipped from the fixture
was mostly wrong, and the user's push on the turnover ceiling is what caught it.

Data: the rebuilt store, 2,974,527 candles, 3,303 symbols. A random 500-symbol
sample gave 33,244 signals over 2025–2026 across 448 symbols with enough
history.

## Why the fixture misled

| | fixture (161 symbols) | full store (448 sampled) |
|---|---|---|
| median 20-day turnover | ₹123 cr | **₹31 cr** |
| below ₹40 cr | ~0% | **56%** |
| p10 | — | **₹1 cr** |

The fixture is Nifty 500. It contains **no small or micro caps at all**, which
is precisely the range where a turnover rule does its work. Every conclusion
drawn about turnover from it was drawn from a truncated distribution.

---

## 1. The turnover ceiling was harmful — removed

On the fixture, >₹400 cr was the worst bucket. On a real universe it is one of
the best:

| | 100–400 cr | >400 cr | verdict |
|---|---|---|---|
| 2025 | +1.04% | **+1.36%** | ceiling hurts −0.32% |
| 2026 | +1.30% | **+2.07%** | ceiling hurts −0.77% |

Sign reversed in both years. On the fixture, ">400 cr" meant index
heavyweights and the rule was really "avoid mega-caps"; on the full store
₹400 cr is an ordinary strong mid-cap. **The ceiling was a market-cap proxy
wearing a turnover label.**

## 2. The turnover floor is redundant in production

`entry_filter_verdict()` rejects anything below `ENTRY_MIN_TURNOVER_CR` (₹40 cr)
**before** the per-strategy rule, so every live candidate has already cleared
it. The floor only looked powerful in backtests because those call
`strategy_signal()` directly and bypass the entry filter — 56% of raw signals
are below ₹40 cr and **none of them can reach a live scan.**

Kept at 40 as belt and braces (the entry filter can be switched off), but it
changes nothing in normal operation.

## 3. The single-tower rule has no stable edge — removed

Live-equivalent signals (those already past ₹40 cr):

| year | not-a-tower | tower | gap |
|---|---|---|---|
| 2025 | −0.94% | −0.08% | **−0.86%** |
| 2026 | +1.41% | +1.34% | +0.06% |

It flips sign. And per strategy, three of five do **better** on a tower:
S3 −0.69%, S4 −4.15%, S5 −0.56%. The earlier S4-only exemption was
directionally right and far too narrow. Rule removed entirely.

## 4. CB purity survives — but at 0.60, not 0.30, and with no ceiling

Threshold sweep on live-equivalent signals, both controls:

| threshold | 2025 gap | z within-day | 2026 gap | z within-day | |
|---|---|---|---|---|---|
| 0.30 | +0.08% | **−1.2** | +1.88% | +4.9 | fails 2025 |
| 0.40 | −0.24% | **−1.8** | +0.72% | −0.0 | fails both |
| 0.45 | +1.25% | +2.3 | +0.84% | +1.1 | marginal |
| **0.60** | **+2.19%** | **+3.4** | **+2.09%** | **+3.0** | **holds** |

0.60 is the only threshold positive in both years under the within-day null —
the control that removes any benefit from merely being active on good days.

**The upper bound also reversed.** The fixture showed purity >0.75 at −1.61%;
on the full store it is the *best* bucket at +3.12%. The band was noise.

The sweep is a best-of-5 choice, so discount the magnitude. What is not a
selection effect: 0.30 and 0.40 fail outright while 0.60 holds on both sides.

---

## The corrected rule

```
keep a candidate if CB purity over the expansion tail >= 0.60
```

That is the whole filter. The turnover floor is retained but redundant; the
ceiling, the CB ceiling and the tower rule are gone.

## Honest accounting

This is the **second** correction to this filter. The sequence:

1. Hard-gate stack — inverted the funnel, dropped.
2. Entry timing — cost 2.39 points, dropped.
3. His exit — lost 53%, dropped.
4. Weighted score + top-N/day — zero edge out of sample, dropped.
5. Three-condition filter from the fixture — **two of three conditions now
   shown wrong on a real universe.**

What survives from the entire study is **one condition**, and it is the one
that came from the user's own definition of a CB candle.

The pattern in the errors is consistent and worth naming: **every wrong
conclusion came from a narrow sample being treated as representative.** The
fixture had no small caps, so turnover rules fitted to it were really
market-cap rules. It had two years, so a band fitted to it was really fitted
to one regime.
