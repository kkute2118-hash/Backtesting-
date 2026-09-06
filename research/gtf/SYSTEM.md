# GTF-D14 — the running system

Supersedes `STRATEGY.md` (GTF-D13), which stays for the record. Evidence in
`FINDINGS_V2.md`. **Confidence: medium.** It is validated the hard way —
quarterly walk-forward, model refit on past data only — and it still returns
less than buying the index over this window, with a better Sharpe and a losing
year in it.

---

## Daily operation

```bash
python scan.py --db market_data.sqlite3          # run after the close
```

It prints the ranked candidates and writes `signals_<date>.csv`. Orders are
resting **buy limits** for the next session.

The scanner retrains on every run, using only trades that had already resolved
95 days before the as-of date, so a run dated T could genuinely have been made
on the evening of T.

---

## The pipeline

```
daily candles
   -> demand zones            leg-in / base / leg-out, body-to-wick  (video A1-A3)
   -> alive + reachable       no close below distal; price within 9.66% above
   -> features                27, all readable on the previous close
   -> learned score           gradient boosting, refit quarterly on past only
   -> gates                   score >= 90th pct  OR  the five hand rules
                              AND turnover >= 10 Cr/day
                              AND market in the high-volatility regime
   -> resting buy limit at the proximal line
   -> stop  entry - 2 x ATR14      (ATR of the fill day)
      target entry + 8 x ATR14
      time   60 trading days
```

### The five hand rules (kept because the union outperforms either alone)
```
zone_height_pct                >= train 40th pct
legout_atr                     >= train 50th pct      (video A5, quantified)
atr_pct                        >= train 50th pct
approach speed                 >= train 50th pct
(close - EMA200)/ATR14         <= 0.96                (our own prior audit)
```

### Guards that exist because they broke in testing
| guard | why |
| --- | --- |
| approach capped at **9.66 %** | the model was fitted on real arrivals, median 1.2 % above the zone. Fed a zone 50 % below price it printed +24 % expected return and a **negative stop price**. |
| **turnover excluded** from the features | with it in, the model tilted to sub-5 Cr/day names — half the apparent edge |
| **10 Cr/day floor** | our 0.23 % cost model does not price impact |
| one row per symbol | otherwise the list is eight variations of one name |
| exclude fills gapping below the stop | the limit and the stop trigger together |

---

## Portfolio rules

* 1.5 % of equity risked per trade; stop distance is 2 ATR, so notional = risk / (2·ATR/price).
* Position notional capped at equity / slots.
* **No leverage** — gross exposure never exceeds equity.
* 30 concurrent slots; one position per symbol.
* CAGR is flat from 1 % to 3 % risk per trade — the binding constraint is slots
  and the no-leverage cap, not the risk fraction.

---

## Measured, walk-forward, 2022-01 to 2026-09

| | value |
| --- | --- |
| signals | 10,617 |
| win rate | 41.1 % |
| average per trade | +3.97 % |
| profit factor | 1.70 |
| matched placebo | +0.78 %, PF 1.17 |
| CAGR (30 slots, unlevered) | **21.3 %** |
| max drawdown | −19.2 % |
| Sharpe | **1.85** |
| correlation with the index | **−0.13** |
| benchmark: equal-weight buy-and-hold | 23.4 % CAGR, −21.4 % DD, Sharpe 1.32 |

Robustness: CAGR 30.8-39.9 % across six exit policies (unconstrained set),
20.3-30.3 % across model depths 2-5 and three seeds. **Quote the range, not the
top of it.**

---

## The last two years on their own

The table above spans 2022-2026 and is front-loaded. Over **2024-09 to 2026-09**:

| | GTF-D14 | buy & hold |
| --- | --- | --- |
| total return, 2 yrs | **+2.4 %** | +7.9 % |
| CAGR | +1.2 % | +3.9 % |
| Sharpe | 0.21 | 0.31 |

Signal quality held (39.2 % wins, +3.05 %/trade, PF 1.53). **Capacity did not:**
472 of 5,608 signals get taken and those average +0.48 %. See FINDINGS_V2 §10.

## How this fails

* **A losing year.** 2025 was −11.1 % for the production set.
* **It goes quiet.** The volatility gate closed for two full quarters of 2025.
* **Capacity is the binding constraint**, so which signals get taken matters;
  the CAGR spread across 8 random selection orders is roughly ±3 points.
* **It is long-only** in a universe with survivorship bias, which is the
  direction that flatters a dip-buying rule.
* **The intersection of rules and score is the best signal** (+5.26 %, PF 1.88)
  and cannot fill a portfolio. If you want quality over deployment, trade that
  and accept ~7 % CAGR.

## Do not

* Remove the liquidity floor to make the numbers better. That is where half the
  original 32.6 % came from.
* Pick the best seed or exit policy after the fact.
* Use the GTF trade score for ranking. It is inversely predictive; two separate
  studies now say so.
