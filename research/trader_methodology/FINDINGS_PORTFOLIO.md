# Findings — ₹1 lakh portfolio. The per-trade edge does not survive the account.

Direct answer to "how much do we make on 1 lakh, and is the new learning
helpful": **on this data, at ₹1 lakh with 3 concurrent positions, it makes
roughly nothing, and the filter does not help.** The per-trade edge is real
but a ₹1 lakh / 3-slot account cannot harvest it.

Day-by-day simulation, 3 slots, position = equity/slots (compounding), costs
charged on every fill, signals missed when no slot is free. Fixture: 161
symbols, Jan 2025 – Sep 2026 (1.68 years).

---

## The core problem: 22,530 signals, 43 trades

With 3 slots and a median 18-bar hold, the account can take about **26 trades
a year**. Everything else is missed — not filtered out, just unreachable.

That collides with the payoff shape. The 3R target means the mean return is
carried by a tail: **25.2% of filtered signals hit +21%**, and almost
everything else stops out at −7%. Over 43 trades you expect ~11 of those
winners. In the realised run we got **5**.

That is not bad luck to be corrected — it is what 43 draws from a
tail-dependent distribution looks like.

## Allocation luck dominates everything

Re-running with 150 random slot-allocation orders over the *same* filtered
signals:

| slots | trades | mean | sd | 5th | 95th | profitable |
|---|---|---|---|---|---|---|
| **3** | 44 | **−3.1%** | 19.4 | −31.7% | +29.6% | **41%** |
| 5 | 72 | −2.5% | 14.0 | −25.6% | +19.0% | 45% |
| 8 | 113 | +1.9% | 11.6 | −17.2% | +20.2% | 56% |
| 12 | 167 | +6.2% | 9.6 | −8.2% | +23.4% | 72% |
| 20 | 279 | +8.0% | 7.6 | −4.0% | +23.0% | 84% |
| 30 | 423 | +9.4% | 5.8 | −1.0% | +18.7% | **93%** |

At 3 slots the outcome swings **±20%** on allocation order alone, and only
41% of orderings finish profitable. The single −32.5% run reported first was
near the 5th percentile — but the *mean* is still negative.

**The trend is the finding.** More positions monotonically improves both the
mean and the reliability, because more trades let the tail show up. This is
diversification doing the work, not better selection.

## And the filter does not help in a portfolio

| slots | raw scan | filtered |
|---|---|---|
| 3 | **+3.9%** | −3.1% |
| 8 | **+3.5%** | +1.9% |

This flatly contradicts the per-trade result (+1.70% filtered vs −0.06% raw).
Both arms are equally slot-constrained — with 54 raw signals a day and 6.7
filtered, a slot never waits either way — so the filter's only effect is to
change *which* 43 trades you get, and at that sample size that is noise
dominated by the tail.

**Reconciling the two:** the filter's edge is a property of the *population*
of signals. A 43-trade sample of that population is too small for a
1.2-point mean difference to appear against a distribution whose standard
deviation is ~12 points per trade. Both results are correct; they answer
different questions.

## Per strategy, 3 slots, whole period

| | raw | filtered |
|---|---|---|
| S1 | +84.8% | −20.7% |
| S2 | −30.0% | +19.6% |
| S3 | −35.1% | −2.2% |
| S4 | +7.0% | +12.8% |
| S5 | +6.8% | +10.0% |
| all five | −32.3% | −32.5% |
| **S4+S5 filtered** | | **+51.5%** (14 trades) |

**Do not read these as strategy rankings.** S1 raw +84.8% against S1 filtered
−20.7% on 67 and 52 trades is the same allocation noise measured above. The
S4+S5 +51.5% rests on **14 trades**. None of these cells has enough trades to
mean anything — that is the point, not a caveat to it.

Held-out 2026 alone, 3 slots: raw +9.4%, filtered +10.4%, filtered-minus-S3
+12.9%, filtered S4+S5 +17.4% on 8 trades. Same warning.

---

## What this actually says

1. **No, this is not helpful at ₹1 lakh with 3 positions.** The arithmetic of
   the payoff defeats it before selection quality matters.

2. **The constraint is trade count, not signal quality.** ~26 trades a year
   against a 25% hit rate needs roughly 100+ trades a year for the mean to
   express itself.

3. **The per-trade finding still stands** — z=+4.3 within-day, survives costs.
   It is a population property and needs enough draws to realise.

## Two ways out, neither tested yet

**More positions.** 12 slots reaches +6.2% mean and 72% profitable; 30 slots
+9.4% and 93%. But 30 slots on ₹1 lakh is ₹3,333 a position — below sane
minimums, and brokerage stops being negligible. This trade-off has a floor
somewhere and it has not been located.

**A different exit.** The 3R target is what creates the tail dependence. An
exit with a higher hit rate and a smaller average win would need far fewer
trades to converge. The author's own exit — trail the 10 EMA, sell 74–80%
into the first strong expansion — showed a much less extreme loss profile
(median −0.33R against −1.00R) in the entry study. **Worth testing as a
portfolio, and not yet done.**

The second is the more promising, because it addresses the cause rather than
compensating for it — and it is what he actually does.

---

**Caveats:** 161 fixture symbols, 1.68 years, single price path. Slot
allocation assumes at most one position per signal and does not enforce one
position per stock. The full-universe rebuild will materially change the
signal supply and should move every number here.
