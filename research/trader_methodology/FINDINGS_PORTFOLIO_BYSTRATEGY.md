# Rs 1 lakh, strategy by strategy — and the first thing of his that works

Supersedes `FINDINGS_PORTFOLIO.md`. Run on 486,551 signals over 1,636 symbols,
2021-03-19 to 2026-09-18 (1,364 trading days, 5.46 years), three slots,
costs charged on the real position size at realistic slippage.

**Every figure below is the median of 25 runs with the within-day order
reshuffled**, not a single path. On a three-slot book only a couple of the
day's signals can be taken and which one gets the slot is close to arbitrary,
so one path is an anecdote. The single path put S4-on-his-stop at Rs 434,266;
the median is Rs 178,694. Both are in the file, and the median is the one to
quote.

Costs: at a Rs 33,333 slot the round trip is **0.593%**, not the 0.569% a
Rs 1 lakh notional implies — the Rs 20 brokerage cap stops binding once the
position is small. Every earlier per-trade table was slightly optimistic.

---

## The headline: his stop works on S4 and S5, and nowhere else

Per trade, on the full 1,636-symbol set:

| strategy | n | FLAT7 (our 7%) | PIVOT (his stop) | |
|---|---|---|---|---|
| S1 | 290,590 | **+0.94%** | +0.87% | ours |
| S2 | 23,737 | **+1.32%** | +0.57% | ours |
| S3 | 143,257 | **+1.50%** | +0.69% | ours |
| **S4** | 13,747 | +0.35% | **+1.23%** | **his, 3.5x** |
| **S5** | 15,220 | +1.22% | **+2.75%** | **his, 2.3x** |

And as a Rs 1 lakh account at three slots, median of 25 orderings:

| strategy | stop | trades | /yr | median final | CAGR | p10 | p90 | orderings > Rs 1L |
|---|---|---|---|---|---|---|---|---|
| **S4** | **his pivot** | 136 | 35 | **Rs 178,694** | **+11.2%** | 106,992 | 279,641 | **92%** |
| S4 | our 7% | 234 | 60 | Rs 45,971 | −13.3% | 26,333 | 61,295 | **4%** |
| **S5** | **his pivot** | 179 | 42 | Rs 108,193 | +1.5% | 46,833 | 178,328 | 60% |
| S5 | our 7% | 228 | 54 | Rs 60,939 | −8.7% | 33,863 | 86,624 | 4% |

S4 on our stop is a **4%-of-orderings-profitable disaster**. The same signals
on his stop are profitable in **92% of orderings with a 10th percentile above
Rs 1 lakh**. That is not an ordering artefact and it is not a per-trade
rounding difference — it holds on both measures, in the same direction, at
n=13,747.

Two caveats that keep this honest. The pivot arm only trades where a demand
candle exists, so it takes 7,004 of S4's 13,747 signals: part of what is
being measured is that condition, not only the stop. And S5 already uses a
structural stop in production, so for S5 this is a confirmation rather than a
proposal.

**Nothing was changed.** Stop calculation is frozen; this is a report.

---

## Everything else, three slots, median of 25 orderings

| arm | median final | CAGR | orderings > Rs 1L |
|---|---|---|---|
| **FLAT7** — our 7% stop, 3R (the current book) | **Rs 120,787** | **+3.5%** | 88% |
| PIVOT — his stop everywhere | Rs 103,477 | +0.6% | 56% |
| PIVOT_MK — his stop plus the marking gates | Rs 86,792 | −2.6% | 32% |
| FUNNEL — DNA, then turnover, then his stop, DNA target | Rs 36,124 | −17.0% | **0%** |

Per strategy under FLAT7: S2 Rs 156,186 (+8.5%), S3 Rs 152,358 (+8.0%),
S1 Rs 142,422 (+6.7%), S4 Rs 45,971 (−13.3%), S5 Rs 60,939 (−8.7%).

The funnel finished below Rs 1 lakh in **every one of 25 orderings**, at every
slot count, for every strategy except S5's 82-signal sample. A DNA target
that caps each winner at one typical move, on a book whose payoff is carried
by the trades that run several, does not survive contact with an account.

---

## The constraint nobody can filter their way out of

486,551 signals offered. At three slots the account takes **168**. That is
0.03%, and it is the whole game on a small book:

| slots | FLAT7 median final | trades taken | per year |
|---|---|---|---|
| 1 | Rs 119,679 | 58 | 14 |
| 3 | Rs 120,787 | 168 | 40 |
| 5 | Rs 145,804 | 288 | 68 |

Going from one slot to five moved the median more than any filter tested in
this project. Selection barely matters when the slot schedule discards
99.97% of what the scanner finds; what matters is how many independent bets
the account can hold and how fast they turn over.

The realistic reading of the current book is **+3.5% CAGR at three slots on
Rs 1 lakh, with a 43% drawdown on the single path** — positive, and not by
enough to be interesting after tax and effort. The route to changing that is
more slots or more capital, not another gate.

---

## What this changes about the standing conclusions

Nothing is retracted. The gates, the CB filter, the marking gates, the DNA
target and the tight stop applied globally all failed, and they fail again
here on an account. What is new:

1. **Strategy-specific stops.** "His stop is worse" was measured across all
   strategies pooled. Split out, it is worse on S1/S2/S3 and clearly better
   on S4 and S5 — and pooling hid a real effect because S1 and S3 supply 89%
   of the signals.
2. **S4 on a flat 7% stop is losing money** and has been in the book that
   way. That is worth acting on before any new research.
3. **Slot count dominates.** Any further selection work should be weighed
   against simply running more slots, which is free and measured.
