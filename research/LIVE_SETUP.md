# The live setup

The configuration the system now runs, and the measurement behind each part.
Full workings: `research/SECTOR_TIMING_FINDINGS.md`.

## The rules

| | rule | why |
|---|---|---|
| Strategies (default) | **S4 + S5**, S4 takes slot priority | measured best portfolio; S1-S3 stay implemented and selectable |
| S1, S2, S3, S5 | **ATR(14) >= 4% of close** | S5 beats the rest 5 years of 5 (p(sign)=0.031, p(mean)<0.0001); S1/S2/S3 win 3 of 5 with p(mean)<0.001 |
| S4 | **sector rank <= 3**, real sector-index membership only | 4 years of 4, p(mean)=0.0028. ATR does nothing for S4 (+0.19, p=0.40) |
| Every strategy | **turnover >= Rs 40 cr/day** | returns fall monotonically with liquidity (PF 1.56 -> 1.19); below the floor the ATR filter inverts (-0.49, PF 1.11 vs 1.23) |
| Sizing | 3 slots, 25% of live equity each, one position per ticker | |
| Exit | unchanged per strategy (S5 on its 10/50 EMA machine, the rest -7% / +21%) | |

## What was removed

* **The marking / score gate.** The score has no demonstrated relationship to
  outcome. `persist_scanner_signals` and `step_add` no longer cut on it; the
  score is still computed and displayed.

## What was measured and deliberately left out

| rejected | result |
|---|---|
| market / index demand zone | negative for all five strategies; the state is followed by -0.51% over 60 days against +3.20% otherwise |
| sector at support | adds nothing on top of ATR (best p(sign) 0.055 -> 0.57 against best-of-15); subtracts from S1 |
| correlation-inferred sectors | classifier is good (67% top-1) but the edge does not replicate: S4 top-3 PF 3.07 -> 1.27 |
| expanding to ~2000 stocks | less liquid stocks do move faster, but pay worse; no candidate shortage to solve (49 signals/day, >=3 on 100% of days) |
| turnover ceiling of Rs 250 cr | marginally better in-sample, but the upper edge was read off the same sample |

## What it returned in backtest

Rs 1,00,000, 3 slots, 25% per position, 2022-06 to 2026-09 (4.29 years),
median of 12 random tie-break seeds.

| portfolio | taken | win% | final Rs | CAGR% | CAGR range | maxDD% | CAGR/DD |
|---|---|---|---|---|---|---|---|
| S4+S5, no filter | 231 | 37.5 | 1,80,207 | 14.6 | 2.7 to 26.4 | -24.0 | 0.61 |
| **S4+S5, this setup** | 192 | 44.1 | **3,53,603** | **34.2** | **24.8 to 54.8** | -27.1 | **1.26** |
| all five, this setup | 174 | 33.7 | 2,38,946 | 22.5 | 10.2 to 28.9 | -33.9 | 0.66 |

The seed range matters more than the median: the worst of twelve draws still
returned 24.8% a year. That is the claim with the most support, not the 34.2%.

## Caveats a reader should carry

* 4.29 years, one market, one country. 2023 carries an outsized share of every
  strategy's return in this sample.
* S4's sector rule needs real index membership, which covers 183 of 485 stocks.
  An S4 signal outside that set is rejected rather than waved through.
* S1/S2/S3 pass the ATR filter on the mean but only 3 years in 5 - real on
  average, not dependable year to year. That is part of why they are not in the
  default portfolio.
* Re-measure after each sector sync. The S5 sector edge decayed every year in
  this sample and was negative in 2026.

## Turning it off

`core.APPLY_ENTRY_EVIDENCE_FILTER = False` restores the unfiltered scan, which
is what any future measurement run should use.
