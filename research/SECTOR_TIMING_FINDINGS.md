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
