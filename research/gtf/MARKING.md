# The marking system: 2 trades a week from one ranked queue

You can trade two or three names a week. The system produces about 300 signals
a week. Everything below is about that gap.

---

## 1. The setup

Every source — S1, S2, S3, S4, GTF zones, and the liquidity grabs/sweeps/runs —
is rebuilt into **one candidate table on identical terms** (`build_pool.py`):

* entry at the close of the signal day, for everyone
* stop 2 ATR below entry, for everyone
* one exit policy for everyone (breakeven at +15 %, 60-bar time stop)
* the same 25 price-derived features for everyone

Identical terms matter. Comparing S4's own score against GTF's own score is
comparing two different scales built for two different purposes; neither tells
you which of today's candidates is better. **289,924 candidates**, 2022-10 to
2026-08, after which a turnover floor is applied.

**Rank by R, not by percent.** With fixed-fractional sizing the money in a
trade is `equity × risk ÷ stop distance`, so what compounds is R, not percent.
Ranking by percent quietly prefers wide, volatile trades that need more capital
to earn the same rupees.

## 2. Three things that had to be fixed first

**The illiquid tail was the single best-ranking feature.** "Least liquid" beat
every other ranking rule in every period (+1.60 R vs +0.35 pool average). That
is the capacity trap from round two: those names cannot absorb real money, so
their backtest returns are fiction. A **Rs 25 Cr turnover floor** goes on
before anything is ranked. It costs 16 % of candidates and about 0.09 R of
apparent edge — all of it unreal.

**I misread an inversion.** Pooling the last two years into deciles showed the
model's top decile at −0.387 R and its bottom at −0.094 R, which looks like the
model ranking backwards. It was an artefact of pooling: deciles cut across
quarters whose baseline R differs several-fold sort quarters, not trades.
Measured **within** each quarter the spread is +0.157 R overall and +0.074 R in
the last two years — weak, but not inverted.

**A pool with negative expectancy cannot be rescued by ranking.** The candidate
pool averages **+1.10 R in 2022-23 and −0.15 R over the last two years**. No
selection rule fixes that; it only decides how much of it you take.

## 3. What ranks, and what does not

Top 2 % by each rule, average R, inside the tradeable universe:

| rank by | full | 2022-23 | 2024+ | last 2 y |
| --- | --- | --- | --- | --- |
| expected-return model | 0.517 | 1.282 | 0.048 | **−0.554** |
| source's own score | 0.309 | 1.486 | −0.099 | −0.228 |
| strongest weekly trend | 0.337 | 1.175 | −0.141 | −0.304 |
| calmest | 0.629 | 1.869 | −0.169 | −0.200 |
| most sources agreeing | −0.244 | 1.563 | 0.191 | −0.165 |
| weakest 6-month momentum | 0.239 | 0.854 | 0.251 | **+0.335** |
| furthest below the 200 EMA | 0.234 | 0.746 | 0.118 | +0.151 |
| *pool baseline* | 0.258 | 1.100 | −0.027 | −0.148 |

Everything trend-following inverts after 2023. The contrarian features survive.
But note what happened when the contrarian rules were actually run at 2-3 a
week: **they did worse than random**. Being best in the extreme top 2 % does
not survive being diluted to the top 3 of a week.

## 4. What actually works: rank by probability, not by size

You asked for the *most probable* stocks. That is a different target from
expected return, and it is the one that holds.

A classifier on P(win), refit every quarter on candidates that had already
resolved, sorts win rate out of sample:

| | top fifth | bottom fifth | gap |
| --- | --- | --- | --- |
| full window | 30.4 % | 24.3 % | +6.1 |
| last 2 years | 25.6 % | 19.6 % | +6.0 |

Quarter by quarter the gap is **+6.4 points on average, positive in 12 of 16
quarters** and **+5.8 points, positive in 7 of the last 9**. Nothing else in
this project has been that consistent.

### Against random selection from the same pool

Same weeks, same budget, same capital, 60 paired orderings:

| per week | period | model ROI | random ROI | difference | model won |
| --- | --- | --- | --- | --- | --- |
| 1 | full window | +17.1 % | +47.4 % | −30.3 | 17 % of runs |
| 1 | last 2 years | −1.5 % | −6.7 % | +5.1 | 65 % |
| **2** | **full window** | **+89.3 %** | +72.6 % | **+21.4** | **67 %** |
| **2** | **last 2 years** | **+11.3 %** | −5.6 % | **+16.6** | **85 %** |
| 3 | full window | +44.9 % | +77.5 % | −23.6 | 28 % |
| 3 | last 2 years | +5.3 % | −6.2 % | +10.9 | 65 % |

Index over the same spans: +158.9 % full window, +7.9 % last 2 years.

**Read this honestly.** The last-two-year column is positive at every budget
(+5.1, +16.6, +10.9) and wins most orderings — that is the ranking doing real
work in the recent, hard period. The full-window column flips sign with the
budget, which means the ROI translation is noisy at 100-600 trades even where
the underlying win-rate edge is stable. Two a week is the best of three cells I
looked at, so treat +11.3 % as the top of the plausible range, not the
expectation.

## 5. The system

1. **Universe** — Nifty 500, 20-day average turnover ≥ Rs 25 Cr.
2. **Candidates** — any signal from S1-S4, GTF, or a liquidity grab/sweep.
3. **Mark** — P(win) from the quarterly-refit classifier, expressed as a
   percentile against the training distribution. 99 means "best 1 % of what
   the market was offering then".
4. **Take the top 2 per week**, one per symbol, in mark order, on the day they
   fire. No waiting to see if Friday is better than Monday — that is not
   available live.
5. **Entry** at the close of the signal day. **Stop** 2 ATR below.
   **Breakeven** at +15 %. **Time stop** at 60 bars.
6. **Size** at 1 % of equity risked, gross exposure never above equity.

`python weekly.py [YYYY-MM-DD]` prints the shortlist. Example, 2026-08-07:

| symbol | source | mark | entry | stop | stop % | turnover |
| --- | --- | --- | --- | --- | --- | --- |
| PFOCUS | GTF | 99.3 | 287.60 | 258.38 | 10.2 % | 25.9 Cr |
| IGIL | S3 | 99.1 | 355.80 | 330.56 | 7.1 % | 27.5 Cr |

## 6. What to expect, and what not to

* **Win rate 25-35 %.** The mark ranks probability but does not make it high.
  Most marked trades still lose; the winners have to run.
* **The edge is relative, not absolute.** In the last two years the marked
  picks made about +11 % while random picks from the same pool lost about 6 %.
  The index made 7.9 %. Ranking beat random convincingly and beat the index
  only narrowly, in a period where the underlying pool had negative
  expectancy.
* **Do not raise the budget expecting more.** Three a week was worse than two
  in both periods; one a week was worse than random over the full window.
* **The mark decays.** It is refit quarterly for a reason: every trend-
  following ranking in this project inverted after 2023. If the quarterly
  top-fifth-minus-bottom-fifth gap goes negative for two quarters running,
  stop trading it and re-examine, rather than waiting for it to come back.
