# Sector rotation and market support as entry filters

Question asked: *"back test it for our all stocks without marking and give me result if
we take sector wise / support wise entry of stocks, or EMA-10 support of best performing
sector chart stocks entry."*

Answer up front: **none of the three filters survives the per-year control.** The pooled
numbers look encouraging; every one of them is calendar composition, not an edge.

## Data the test ran on

Synced database, verified 2026-09-19:

| item | state |
|---|---|
| `sector_membership` | 14 sectors, 229 memberships |
| index price history | 10 of 14 indices, 2021-09-20 -> 2026-09-18, ~1,240 bars each |
| missing indices | NIFTY BANK, NIFTY FIN SERVICE, NIFTY IT, NIFTY SMLCAP 250 |
| stocks with a sector | **183 of 482 (38%)** |
| trades taggable with a sector | **86,055 of 204,407 (42%)** |

The four sectors without a real index (Bank, Financial Services, IT, Consumer Durables,
Healthcare, Media, Oil Gas) are priced from an equal-weight composite of their own
members instead. That is a fair substitute for ranking but it is not the traded index.

Sector strength = 21-day return of the sector minus 21-day return of NIFTY 500, ranked
across the 14 sectors each day (1 = strongest). A stock in two sectors takes its **best**
rank, which is the generous reading.

Exit columns: `t20_ret` = exit on first close below the 20 EMA; `cur_ret` = the system as
it actually trades (-7% stop / +21% target). `cur_ret` is the one that matters for money.

## 1. Sector rank alone

Pooled, all 86,055 trades:

| rank bucket | n | t20 avg | t20 PF | cur avg | cur PF |
|---|---|---|---|---|---|
| 1-3 | 15,934 | +0.97 | 1.61 | +2.33 | 1.51 |
| 4-6 | 19,514 | +0.66 | 1.47 | +2.78 | **1.62** |
| 7-9 | 20,554 | +0.29 | 1.20 | +2.33 | 1.51 |
| 10-14 | 30,053 | +0.33 | 1.24 | +2.31 | 1.50 |

On `t20` the top bucket leads - but rank 10-14 beats rank 7-9, so the relationship is not
monotonic. On `cur_ret`, the exit we actually use, **the best bucket is 4-6** and the
spread across all four buckets is 0.12 in PF. There is nothing there.

## 2. Per-year control

Split by year and strategy, top-3 sector vs the rest:

* `t10` exit: top-3 wins in **5 of 10** year-strategy cells.
* `t20` exit: top-3 wins in **6 of 10**.

A coin flip. The pooled `t20` gap comes from 2022 S1 (+2.16) and 2024 (+1.03 S1, +0.51
S3); 2023, 2025 and 2026 run the other way.

## 3. Two permutation tests that disagree - and which one to believe

Labels shuffled *inside each year*, so the calendar is held fixed.

| strategy | exit | mean per-year diff | p (mean) | years won | p (sign count) |
|---|---|---|---|---|---|
| S1 | t20 | +0.47 | 0.001 | 2/5 | 0.80 |
| S1 | cur | +0.11 | 0.295 | 2/5 | 0.82 |
| S2 | t20 | +1.55 | 0.020 | 3/5 | 0.46 |
| S2 | cur | +1.44 | 0.019 | 2/5 | 0.80 |
| S3 | t20 | +0.22 | 0.001 | 4/5 | 0.17 |
| S3 | cur | -0.59 | 1.000 | 0/5 | 1.00 |
| S4 | t20 | +3.15 | 0.087 | 3/4 | 0.32 |
| S4 | cur | +4.57 | **0.0000** | 3/4 | 0.33 |

The mean-difference test lights up. The sign test - does the filter work *more years than
not* - shows nothing: the best cell is S3 `t20` at p=0.17, and against a best-of-8 search
that is p≈0.77.

The mean test is significant because one year carries it (S1: 2022 alone; S4: 2024's
+11.4). That is the same failure mode that killed the breadth filter, so the sign test is
the one that governs.

**S4 is the one honest "maybe":** biggest effect, the strategy we prioritise, positive in
2023/2024/2025 and negative in 2026. But n=793 across four years and p(sign)=0.33. Not
established.

## 4. Market / index support

NIFTY 500 state at entry, applied to all 86,055 trades:

| filter | pooled cur PF on | pooled cur PF off | years won |
|---|---|---|---|
| within 2% of its 50 EMA and above the 200 EMA | 1.36 | 1.64 | 3/5 |
| >=5% below its 1-year high, above the 200 EMA | 1.29 | 1.58 | 4/5 |
| simply above the 200 EMA | 1.48 | 1.84 | 3/5 |

Every "support" state is **worse** pooled than its complement. The 5%-drawdown filter wins
4 of 5 years yet loses on the pooled mean - Simpson's paradox, driven by a -5.03 reversal
in 2024. A circular-shift null (400 shifts of the market-state series, which preserves its
autocorrelation) puts it at p=0.16 on years-won and p=0.59 on the pooled difference.

Worth stating plainly: being above the 200 EMA scores *worse* than being below it here.
That is survivorship of the sample window, not a reason to trade downtrends.

## 5. The exact rule that was asked for

"Entry at the 10 EMA of a stock in the best performing sector":

| rule | n | % of all | cur avg | cur PF | years won |
|---|---|---|---|---|---|
| rank==1 | 4,517 | 5.2% | +1.97 (rest +2.45) | 1.42 | 1/5 |
| rank==1 and within 2% of 10 EMA | 2,984 | 3.5% | +1.65 (rest +2.45) | 1.35 | 2/5 |
| rank<=2 and within 2% of 10 EMA | 6,759 | 7.9% | +2.19 (rest +2.44) | 1.47 | 2/5 |

It filters hard - down to 3.5% of signals, which is what was wanted - but under the live
exit rules it is **worse than not filtering**, in four years out of five.

It also all but deletes S4. Trades per year under `rank==1 and near 10 EMA`:

| year | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| 2022 | 95 | 7 | 134 | 4 |
| 2023 | 275 | 9 | 411 | 2 |
| 2024 | 325 | 34 | 553 | 0 |
| 2025 | 135 | 47 | 479 | 1 |
| 2026 | 119 | 34 | 316 | 4 |

S4 - the strategy holding slot priority - gets 0 to 4 signals a year. The rule would hand
the book to S3.

## Conclusion

Do not gate entries on sector rank, on index support, or on the two combined. The sector
and index data is worth keeping as a dashboard (it is real information about where money
is moving, and the Sectors page shows it), but as an entry filter it does not beat taking
the trade.

The 38% sector coverage is a separate, hard blocker: a "leading sector only" rule makes
62% of the universe permanently untradeable, including most of what S4 finds.

Method notes: per-year control first, then a permutation null on both the mean and the
sign count, then a best-of-N adjustment. Pooled results are reported but never relied on.

---

# Addendum: strategy-by-strategy, and ROI on Rs 1,00,000

The pooled test above is dominated by S1 and S3 (83,018 of 86,055 tagged trades), and S5
was missing from it entirely - `trail_trades.csv` only looped strategies 1-4. Rebuilt the
trade table to cover **S1-S5** (S5 joined from `s5_trades.csv` with its own state-machine
exit) and re-ran per strategy. **The answer is not the same for every strategy, and the
pooled "nothing works" conclusion is wrong for S4 and S5.**

Sector-tagged signals per strategy: S1 29,290 | S2 2,244 | S3 53,728 | S4 793 | S5 9,862.

## Setup quality by strategy (live exit rules, -7% / +21%; S5 on its own trail)

| strategy | setup | n | win% | avg% | PF | years won |
|---|---|---|---|---|---|---|
| **S1** | all tagged | 29,290 | 33.3 | 1.90 | 1.40 | - |
| | top-3 sector | 5,576 | 35.1 | 2.39 | 1.53 | 2/5 |
| | leading sector | 1,594 | 31.9 | 1.63 | 1.34 | 1/5 |
| **S2** | all tagged | 2,244 | 33.1 | 1.88 | 1.40 | - |
| | top-3 sector | 644 | 34.0 | 2.05 | 1.44 | 2/5 |
| | leading sector | 238 | 29.8 | 1.18 | 1.24 | 1/3 |
| **S3** | all tagged | 53,728 | 36.1 | 2.69 | 1.60 | - |
| | top-3 sector | 9,310 | 34.1 | 2.11 | 1.45 | **0/5** |
| | leading sector | 2,517 | 33.4 | 1.88 | 1.40 | 2/5 |
| **S4** | all tagged | 793 | 46.9 | 5.54 | 2.48 | - |
| | top-3 sector | 404 | 52.5 | 6.96 | 3.07 | 3/4 |
| | leading sector | 168 | **54.2** | **7.64** | **3.43** | **4/4** |
| **S5** | all tagged | 9,862 | 37.2 | 2.14 | 1.98 | - |
| | top-3 sector | 2,110 | 39.1 | 2.87 | 2.06 | 4/5 |
| | leading sector | 701 | 40.8 | 4.19 | 2.44 | 4/5 |

Monotone and per-year consistent for S4 and S5. Flat for S1/S2, and **negative for S3** -
S3 in a top-3 sector lost to S3 elsewhere in all five years.

## Within-year permutation nulls (label shuffled inside each year)

| strategy | setup | n | years won | mean diff | p(sign) | p(mean) |
|---|---|---|---|---|---|---|
| S1 | top-3 | 5,576 | 2/5 | +0.11 | 0.80 | 0.276 |
| S1 | rank 1 | 1,594 | 1/5 | -0.64 | 0.97 | 0.971 |
| S2 | top-3 | 644 | 2/5 | +1.46 | 0.81 | 0.017 |
| S2 | rank 1 | 208 | 1/3 | -0.44 | 0.88 | 0.691 |
| S3 | top-3 | 9,310 | 0/5 | -0.58 | 1.00 | 1.000 |
| S3 | rank 1 | 2,517 | 2/5 | +0.38 | 0.80 | 0.090 |
| **S4** | rank 1 | 151 | **4/4** | +3.98 | 0.067 | **0.0028** |
| **S4** | top-3 | 350 | 3/4 | +4.43 | 0.320 | **0.0000** |
| **S5** | rank 1 | 701 | **4/5** | +2.40 | 0.154 | **0.0002** |
| **S5** | top-3 | 2,110 | 4/5 | +0.92 | 0.168 | **0.0094** |

Unlike the pooled case, the S4/S5 means are *not* carried by one year:

```
S4 rank 1:  2022 +2.71 | 2023 -3.84 (n=17, excluded) | 2024 +8.52 | 2025 +3.48 | 2026 +1.21
S5 rank 1:  2022 +6.74 | 2023 +4.70 | 2024 +1.45 | 2025 +0.22 | 2026 -1.14
```

So the mean-statistic p-values are trustworthy here (Bonferroni over 10 tests: S4 rank 1
p=0.028, S5 rank 1 p=0.002 - both still significant). The sign test does not reach 0.05,
but with 4-5 years the smallest value it *can* produce is 1/16 = 0.0625, so S4's 4/4 is
the best result the statistic allows. Low power, not absence of effect.

**The S5 edge is decaying every single year** (+6.74 -> +4.70 -> +1.45 -> +0.22 -> -1.14)
and is negative in 2026. S4's holds up better but is also shrinking.

## ROI: Rs 1,00,000, 3 slots, 25% of live equity per position, compounding

2022-06-02 to 2026-09-15 (4.29 years). Twelve random tie-break seeds; median reported,
full range shown, because with 36-140 trades taken the draw matters more than the filter.

Compare against **"sector-covered stocks, no filter"**, not against "no filter" - the
latter trades all 482 stocks while every filtered row can only trade the 183 that have a
sector.

| strategy | setup | taken | win% | CAGR% | CAGR range | maxDD% |
|---|---|---|---|---|---|---|
| S1 | covered, no filter | 123 | 30.9 | 8.3 | 2.2 to 24.4 | -39.4 |
| S1 | top-3 sector | 106 | 32.5 | 9.8 | 5.1 to 17.8 | -32.3 |
| S1 | leading sector | 102 | 31.5 | 7.4 | 4.2 to 13.8 | -35.0 |
| S2 | covered, no filter | 80 | 34.9 | 12.0 | -0.2 to 18.9 | -17.8 |
| S2 | top-3 sector | 76 | 33.1 | 7.9 | 1.7 to 11.0 | -20.2 |
| S2 | leading sector | 50 | 44.9 | 14.8 | 13.9 to 16.1 | -10.9 |
| S3 | covered, no filter | 76 | 36.0 | 10.7 | 1.4 to 16.4 | -19.9 |
| S3 | top-3 sector | 70 | 35.4 | 8.7 | 1.6 to 18.1 | -22.8 |
| S3 | leading sector | 66 | 40.7 | 15.1 | 11.9 to 20.7 | -14.0 |
| **S4** | covered, no filter | 84 | 40.7 | 18.8 | 8.6 to 26.0 | -22.8 |
| **S4** | top-3 sector | 57 | 45.6 | 17.0 | 15.2 to 20.5 | **-12.8** |
| **S4** | leading sector | 36 | **55.6** | 18.1 | **16.4 to 18.1** | **-7.0** |
| **S5** | covered, no filter | 223 | 36.7 | 12.7 | -0.1 to 27.6 | -19.5 |
| **S5** | top-3 sector | 146 | 42.7 | **17.4** | -1.0 to 31.9 | **-11.5** |
| S5 | leading sector | 114 | 38.1 | 8.8 | 1.7 to 27.8 | -22.3 |

The filter does **not** reliably raise CAGR - the seed ranges overlap everywhere. What it
does for S4 and S5 is cut drawdown and collapse the spread: S4 leading-sector runs
16.4-18.1% CAGR at a 7% maximum drawdown, against 8.6-26.0% at 22.8% unfiltered. Same
money, a third of the pain, and far less dependent on which signal you happened to pick.

S2's leading-sector row (14.8% CAGR, 13.9-16.1 range, -10.9% DD) looks similar but rests
on 50 trades and a null that says p(sign)=0.88. Ignore it.

## S4 + S5 together - the configuration actually being traded

S4 keeps slot priority.

| setup | signals | taken | win% | final Rs | CAGR% | CAGR range | maxDD% | CAGR/DD |
|---|---|---|---|---|---|---|---|---|
| no filter (whole universe) | 27,241 | 226 | 37.2 | 1,79,148 | 14.6 | 0.6 to 35.5 | -24.5 | 0.59 |
| sector-covered, no filter | 10,655 | 216 | 38.6 | 1,81,074 | 14.9 | 4.7 to 26.2 | -21.3 | 0.70 |
| **top-3 sector** | 2,514 | 140 | **44.5** | **2,11,684** | **19.1** | 4.1 to 28.9 | **-16.6** | **1.15** |
| top-2 sector | 1,664 | 127 | 42.9 | 1,81,000 | 14.8 | 7.0 to 26.8 | -17.4 | 0.85 |
| leading sector | 869 | 109 | 40.3 | 1,77,036 | 14.3 | 13.3 to 26.2 | -19.3 | 0.74 |
| top-3 + at 10 EMA | 722 | 166 | 37.2 | 1,73,871 | 13.7 | 8.5 to 25.8 | -15.2 | 0.90 |

Rs 1 lakh -> Rs 2.12 lakh over 4.29 years at top-3 sector, against Rs 1.81 lakh unfiltered.
Return per unit of drawdown improves from 0.70 to 1.15. The CAGR ranges still overlap, so
the headline CAGR gain is not established; the drawdown and consistency gain is the part
that holds.

Adding the 10 EMA condition on top makes every row worse. S4 names are already sitting on
their 10 EMA, so the condition only removes trades.

## Revised recommendation

* **S1, S2, S3 - do not apply any sector filter.** No effect, and S3 is actively hurt.
* **S4 and S5 - filter to the top-3 sector.** Not for more return, for a materially smaller
  drawdown and a much tighter outcome range.
* **Do not use rank 1 alone.** It over-filters: S4 drops to 8 trades a year, S5's CAGR
  halves.
* **Do not add the 10 EMA condition** to a sector filter.
* Watch the decay. S5's sector edge shrank every year and went negative in 2026. Re-measure
  before relying on it.

---

# Addendum 2: inferring a sector for the other 62% of the universe

Request: work out which sector each unclassified stock belongs to, so all ~500 stocks can
be traded under the sector filter instead of only the 183 in a sector index.

Built and measured. **The inference classifies well, and the trading edge does not survive
it.** A separate, better route exists and is now wired up.

## The classifier

For each stock, at each quarter start, take the trailing 250 days of returns **in excess
of NIFTY 500** (excess, so the score is sector co-movement and not market beta), correlate
against each of the 14 sector composites, and take the highest. Only trailing data is
used, so there is no lookahead. When scoring a stock that is a known member of a sector,
that stock is removed from the sector's composite first - otherwise it is being correlated
with itself.

Validated leave-one-out on the 183 stocks whose sector is actually known, 18 quarterly
snapshots, 2,844 classifications:

| metric | result | random |
|---|---|---|
| top-1 accuracy | **67.0%** | 7.1% |
| top-3 accuracy | **86.6%** | 21.4% |
| always-guess-biggest-sector | - | 14.2% |

By sector: IT 100%, PSU Bank 86%, FMCG 84%, Realty 81%, Healthcare 81% ... Financial
Services 45%, Consumer Durables 44%, Pharma 41%, Media 29%. Pharma's misses are nearly all
Healthcare (top-3 96%), which is a distinction without much difference for ranking.

Accuracy tracks confidence almost perfectly - the top quintile by margin between the 1st
and 2nd sector is 99.5% correct, the bottom quintile 37.1%.

So as a classifier it works. Coverage goes from **38% to 93-100% of signals** per strategy.

## Two warnings the validation gives

**The unknowns are harder than the knowns.** Across the 18 quarters, a known stock's
predicted sector takes a median of 2 distinct values and 37% never change. An unknown
stock's takes a median of **4** and only **7%** never change. The 302 stocks outside every
sector index are outside them for a reason - conglomerates and niche businesses with no
strong sector co-movement - so 67% is an optimistic read of what they get.

**It is not a hidden momentum filter.** Stocks assigned to a top-3 sector do have higher
own 21-day relative strength (+1.49 vs +0.32). Controlling for that - comparing top-3 vs
rest *inside* each quintile of the stock's own RS - leaves the effect intact (+0.55
controlled against +0.57 uncontrolled). Whatever the inferred rank is picking up, it is
not just recent strength.

## The test that matters: does the edge replicate?

Split every strategy's trades by whether the sector was **known** or **inferred**:

| strategy | sector | top-3 PF | rest PF | top-3 years won |
|---|---|---|---|---|
| S1 | known | 1.53 | 1.37 | 2/5 |
| S1 | inferred | 1.38 | 1.23 | 4/5 |
| S2 | known | 1.44 | 1.38 | 2/5 |
| S2 | inferred | 1.39 | 1.37 | 1/5 |
| S3 | known | 1.45 | **1.63** | **0/5** |
| S3 | inferred | 1.28 | 1.12 | 4/5 |
| **S4** | known | **3.07** | 1.98 | 3/4 |
| **S4** | inferred | **1.27** | **1.41** | 2/4 |
| **S5** | known | **2.06** | 1.95 | 4/5 |
| **S5** | inferred | **1.88** | **2.13** | 3/5 |

**For S4 and S5 - the only two strategies where the sector filter worked - it reverses on
inferred sectors.** Top-3 becomes *worse* than the rest under both.

S1 and S3 show the opposite: nothing on known sectors (S3 is 0/5 and negative on known)
but 4/5 on inferred. Two contradictory signs for the same claimed mechanism inside the
same strategy. At least one of them is noise, and the pair together is not evidence of
anything.

## ROI on Rs 1,00,000, S4 + S5, full universe

3 slots, 25% per position, 12 seeds, median reported.

| setup | stocks | signals | taken | win% | final Rs | CAGR% | maxDD% | CAGR/DD |
|---|---|---|---|---|---|---|---|---|
| no filter | 485 | 27,241 | 226 | 37.2 | 1,79,148 | 14.6 | -24.5 | 0.59 |
| **top-3, real sectors only** | **183** | 2,514 | 140 | **44.5** | **2,11,684** | **19.1** | **-16.6** | **1.15** |
| top-3, real + inferred | 485 | 5,498 | 168 | 40.9 | 1,66,515 | 12.6 | -20.3 | 0.62 |
| top-3 by best of 2 inferred | 485 | 8,138 | 186 | 38.3 | 1,95,856 | 17.0 | -23.9 | 0.71 |
| top-3, high-confidence only | 334 | 4,230 | 166 | 41.2 | 1,55,364 | 10.8 | -23.7 | 0.46 |

Extending the filter to all 500 via inference does not just fail to add - it **dilutes the
working filter back to roughly no filter at all** (0.62 against 0.59). Restricting to
high-confidence assignments does not rescue it. Taking the best of the top-2 inferred
sectors gets closest (0.71) and is still well below real-only (1.15).

## The route that does work: NSE's own Industry column

The sector-index constituent files were the wrong source for full coverage. The **broad**
index files (`ind_nifty500list.csv`, midcap 150, smallcap 250) carry an `Industry` column
for **every** row - NSE's own classification, not index membership. That is a real sector
for the whole 500, not a correlation guess.

Implemented in `sync_sector_membership`:

* sector-index lists run first and still give many-to-many membership;
* the broad lists then backfill `Industry` **only** for symbols no index list placed, so a
  real membership always wins - it is what the sector index price actually tracks;
* rows are tagged `source='index'` or `source='industry'`, and `sector_map(source=...)`
  can ask for either, so this finding stays measurable rather than being mixed in
  invisibly;
* industries with no sector index to rank them against (Capital Goods, Chemicals,
  Construction, Services, Telecom, Textiles, ...) are left **unclassified** rather than
  forced into the nearest-looking bucket;
* an industry string not in the map is reported as `_unmapped_industries` instead of
  silently dropping those stocks, because NSE renaming one would otherwise be invisible.

`INDUSTRY_TO_SECTOR` is NEEDS_TUNING - the strings are from NSE's published taxonomy but
were not verifiable from this sandbox (niftyindices.com is blocked by the egress proxy).
The `_unmapped_industries` report is what confirms them on the first real sync.

Expected coverage after that sync is roughly 11 of NSE's 20 macro industries, so more than
38% and less than 100% - the remainder genuinely has no sector index to be ranked against.
**Whether the S4/S5 edge holds on industry-classified stocks is an open question and must
be re-measured after the sync**, with the same per-year control. The inference result above
is the reason to expect it might not.

## Recommendation

* Do **not** trade the sector filter on correlation-inferred sectors. Keep S4/S5's top-3
  filter restricted to the 183 stocks with real index membership, and trade the rest of the
  universe unfiltered.
* Run the sector sync again to pick up the Industry backfill, then re-measure - split by
  `source`, exactly as this addendum splits known from inferred.
