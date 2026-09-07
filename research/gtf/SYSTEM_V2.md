# The system

One strategy, built only from rules that survived a test that could have
killed them. Everything that sounded good and failed is listed at the end, so
you can see what was thrown away and why.

**Run it:** `python system.py [YYYY-MM-DD] [capital]`

---

## The rules

| # | Rule | Evidence |
| --- | --- | --- |
| 1 | **Universe**: Nifty 500, 20-day average turnover ≥ Rs 25 Cr | **Strong.** Without the floor, "least liquid" is the best-ranking feature in every period (+1.60 R vs +0.35 pool average). That money is not collectable. |
| 2 | **Candidates**: any signal from S1-S4, a GTF demand-zone arrival, or a liquidity grab/sweep | **Strong.** GTF arrivals beat a matched placebo by +0.13 R. The others contribute candidates the ranking sorts. |
| 3 | **Mark** each candidate with P(win) from a model refit every quarter on trades that had already finished | **Strong.** Top fifth beats bottom fifth by **+6.4 points of win rate, positive in 12 of 16 quarters** and **7 of the last 9**. The most consistent result in the project. |
| 4 | **Take the top 2 marks per week**, one per symbol, on the day they fire | **Good.** Beat random selection from the same pool in 85% of 60 paired orderings over the last two years. 1 and 3 a week were both worse. |
| 5 | **Entry** at the close of the signal day | **Structural.** No intraday data, so no other entry is honestly testable. |
| 6 | **Stop** 2 ATR below entry, never widened | **Strong.** The video's tight distal stop stops out 91% of the time on narrow zones. At 2 ATR the GTF score stops being inverted and starts working. |
| 7 | **Breakeven**: move the stop to entry once price reaches +15% | **Good.** 71% of trades that reach +5% give it all back, but 30% of them go on to +25%. +15% was the point where protecting stopped costing more than it saved. |
| 8 | **Time exit** at 60 trading days | **Adequate.** Not optimised; it is the horizon everything was measured on. |
| 9 | **Size** 1% of equity at risk per trade, no position above 25%, gross exposure never above equity | **Strong.** Fixed-fractional sizing is why R and not percent is what compounds. The no-leverage cap matters: without it a 3-a-week book silently runs 5x geared. |
| 10 | **Breadth tilt**: 4 trades a week when breadth < 30%, 3 when < 40%, else 2 | **THIN — 2 to 3 episodes.** See the warning below. |

## Results

Rs 10,00,000, 1% risk, no leverage, costs of 0.23% per round trip inside every
trade, median of 40 selection orderings.

| system | period | ROI | CAGR | max DD | Sharpe | worst ordering |
| --- | --- | --- | --- | --- | --- | --- |
| **with breadth tilt** | full window | **+97.8%** | **19.5%** | **−11.8%** | **1.36** | +68% |
| base, 2 a week | full window | +88.8% | 18.0% | −13.8% | 1.31 | +63% |
| random, 2 a week | full window | +76.3% | 15.9% | −24.6% | 1.05 | +55% |
| *equal-weight index* | full window | *+158.9%* | *27.5%* | *−21.4%* | | |
| **with breadth tilt** | last 2 years | **+12.6%** | **6.5%** | **−16.8%** | **0.47** | +1% |
| base, 2 a week | last 2 years | +10.7% | 5.5% | −19.9% | 0.34 | 0% |
| random, 2 a week | last 2 years | +0.3% | 0.2% | −24.6% | −0.01 | −8% |
| *equal-weight index* | last 2 years | *+7.9%* | *3.9%* | *−21.4%* | | |

Year by year, base system: **+6.4%, +29.5%, +19.6%, +7.9%, +15.3%.** No losing
year, but note 2022 is a partial year and 2026 is not finished.

**The index made more money over the full window and the system did not beat
it.** 27.5% CAGR against 19.5%. What the system did do is make its return with
roughly half the drawdown (−11.8% against −21.4%) and beat the index over the
last two years, when the index stalled. If you want maximum return and can sit
through a 21% drawdown, an index fund is the honest answer. If you want a
smaller drawdown and something that works when the index does not, this is
worth running.

## What to expect

* **Win rate about 33%.** Two out of three trades lose. At that rate **six
  consecutive losses has a 9% chance of happening in any given stretch** — it
  is an ordinary event, not a broken system.
* **Roughly 2 trades a week, 100-120 taken a year.** Not every signal gets a
  slot; capital and the one-per-symbol rule turn ~400 signals into ~185 trades.
* **The median trade loses money.** The average is positive because winners run
  to the 60-day limit while losers are cut at 2 ATR. If you cut winners early
  to "lock in gains", you will remove the entire edge.
* **Expect a 15-20% drawdown.** The backtest had one. A live one will feel worse.

## The warning on rule 10

The breadth tilt is the only rule here that is not properly evidenced. It is
built on **two scored episodes** at breadth under 30% (Feb-May 2025, Mar-Apr
2026) and three at index-below-200. Every one was positive — and every one was
a drawdown that bounced within 60 days. **This five-year sample contains no
sustained bear market.** In a 2008 or a 2000, a rule that says "trade more when
breadth collapses" is exactly the wrong rule and will do real damage.

Keep it only if you accept that. `python system.py --no-tilt` equivalent: set
`TILT=False`. It costs about 1.5 points of CAGR.

## Monitoring, and when to stop

Run this every quarter. It is not optional — every other ranking in this
project inverted eventually, and this one will too.

1. Split the last quarter's candidates into fifths by mark.
2. Compute the win rate of the top fifth minus the bottom fifth.
3. **Two consecutive negative quarters: stop trading it.** Not "wait for it to
   come back". The historical gap is +6.4 points and it was negative in 4 of 16
   quarters, so one bad quarter is noise and two is a signal.
4. Refit the model quarterly. It is trained only on trades that had already
   resolved, so a fresh refit never sees its own future.

Also track your live win rate against 33% and your live average R against
+0.37. If either sits well below for 30+ trades, something has changed that
the backtest does not cover.

## What was thrown away

Listed so you know these were tested, not overlooked.

| Rejected | Why |
| --- | --- |
| Liquidity sweeps (my reading) | +2.36% full window, −1.33% last 2 years; 1 of 54 parameterisations positive recently |
| Liquidity grabs/sweeps/runs (the course's own rules) | The run returns +4.55% while random entries in the same stock-month return +9.86%. Harmful as a filter on every strategy. |
| The course's target rule | Nearest opposing pool, −0.40%, worse than no target (+0.11%) |
| S1-S4 score gates | Post look-ahead fix the score is flat: S1 at score ≥ 85 wins 28.1% vs 28.3% ungated |
| Expected-return model | Ranks well until 2023, then −0.554 R in the last two years |
| Trend filters (strongest weekly, calmest, most sources agreeing) | All invert after 2023 |
| Contrarian filters at 2-3 a week | Best in the extreme top 2%, worse than random once diluted to a weekly budget |
| Regime filter toward strong markets | Monotonically harmful: −0.148 → −0.219 → −0.250 → −0.315 R as the filter tightens |
| Taking 3 a week | Worse than 2 in both periods |

## Honest limits

* **Survivorship bias.** Today's Nifty 500 list is applied to the whole
  history. Delisted and demoted names are missing. This flatters everything
  here and I cannot size it without a point-in-time constituent list.
* **No corporate action adjustment** was verified in the source data.
* **Stop fills** assume the stop price. 6.8% of stop-outs gapped through it, and
  those averaged −9.74% against −7.00% modelled.
* **Three and a half years, one bull market and two corrections.** That is a
  thin sample for any claim about the future.
* **No sector data**, so sector concentration is unmanaged. You could end up
  with 4 positions in the same sector and not know it.

---

## Appendix: what the mark is made of

**How one is computed.** Every candidate's features go into a gradient-boosted
classifier trained on whether past candidates ended green. The raw output is a
probability; the mark is that probability's percentile against the training
distribution. A mark of 99 means "in the best 1% of what this model has seen",
not "99% likely to win".

**What the model actually looks at** — permutation importance on 2026Q1, a
quarter it never trained on:

| feature | importance |
| --- | --- |
| 20-day realised volatility | 0.0300 |
| % above the 52-week low | 0.0201 |
| turnover | 0.0174 |
| 50 EMA vs 200 EMA | 0.0115 |
| 5-day return | 0.0094 |
| 50-day slope | 0.0087 |

The source that generated the signal (`src_score`, `is_S1` …) barely registers.
The model is reading the stock's condition, not which strategy flagged it.

**A high-marked candidate is calm, unextended and not a momentum leader** —
median values, mark ≥ 99 vs mark ≤ 50:

| | mark ≥ 99 | mark ≤ 50 |
| --- | --- | --- |
| 20-day volatility | 25.0 | 31.5 |
| 6-month return | +3.0% | +23.2% |
| distance above 200 EMA | 1.64 ATR | 3.35 ATR |
| weekly trend slope | +0.7% | +5.7% |

That is consistent with everything else found here: the edge is in quiet
laggards near their moving averages, not in strong trending names.

**Calibration, out of sample.** The mark is monotone up to about 95 and then
flattens and dips:

| mark band | full-window win% | last-2-year win% |
| --- | --- | --- |
| 0-50 | 25.7 | 20.9 |
| 50-75 | 29.7 | 24.4 |
| 75-90 | 30.7 | 25.4 |
| 90-95 | 30.8 | 25.7 |
| 95-99 | 30.5 | 27.1 |
| **99-100** | **26.7** | **22.5** |

The weekly picks sit at a median mark of 99.4, so this looked like a real
problem. It was tested: capping the mark and taking the best candidate *below*
a ceiling made results worse at every ceiling (99: +87.1%, 99.5: +82.4%,
95: +60.1%, against +88.8% uncapped; and −7.8% to +1.5% CAGR against +5.5%
over the last two years). Taking the week's best remains correct.

The reconciliation is that the band table ranks candidates against the whole
quarter while selection ranks them against the same week. A 99 on a week when
nothing good fired is not the same trade as a 99 in a strong week. **Read the
mark as a within-week ranking, not as an absolute quality score.**

---

## Appendix: the review list, and how much your judgement has to add

You want the smallest possible list of names to look at. Two results decide
how small, and both point the same way.

**Hard screens do not work.** Ten sensible-looking filters were tested on top
of the turnover floor — not extended above the 200 EMA, calm volatility, not a
six-month leader, off the 52-week high, RSI above 35, a sane stop width, more
liquid. **Not one raised average R in both periods.** Each helped one and hurt
the other. Applied together they kept 39% of the pool and made it worse than
no screen at all (+0.212 R against +0.258 full window). The reason is visible
in the permutation test: volatility and distance from the 200 EMA are already
the model's two strongest inputs. Screening on them again is overriding the
model with information it has already used.

**A longer list is a worse list.** The "floor" below is what you get if you
review the shortlist and your choice is no better than a coin toss:

| shortlist / week | names a year | list win% (last 2y) | floor ROI, full | floor ROI, last 2y |
| --- | --- | --- | --- | --- |
| **2** | 105 | 25.5 | **+88.8%** | **+10.7%** |
| 3 | 157 | 26.3 | +45.8% | +2.8% |
| 5 | 262 | 26.4 | +68.0% | +0.5% |
| 8 | 420 | 26.4 | +74.6% | −0.1% |
| 12 | 630 | 27.8 | +77.5% | +0.6% |

The edge is concentrated at the very top. Handing yourself five names to
choose two from costs about ten points of annual return unless your chart
reading is genuinely better than chance.

**What a veto costs.** You cannot backtest chart judgement, but you can price
the substitution — every name skipped is replaced by a worse-ranked one:

| choice | ROI full window | ROI last 2 years |
| --- | --- | --- |
| take ranks 1-2 | +88.8% | **+10.7%** |
| veto rank 1, take 2-3 | +49.3% | −1.7% |
| veto ranks 1-2, take 3-4 | +30.5% | −0.2% |
| veto ranks 1-4, take 5-6 | +89.8% | −17.9% |

One veto costs roughly twelve points of annual return. (The full-window column
is noisy — the +89.8% row is selection-order noise, not a finding. The last-two-year
column is the one to read.)

### So: `python review.py`

Three names a week. Take the top 2. The third is a reserve for when one is
disqualified.

**Use your eyes for the model's blind spots, not to re-rank.** It reads price
and volume only. It cannot see an earnings date, a merger, a split the data
never adjusted for, a regulatory action, or a broken price series. Those are
real reasons to skip.

It already knows the chart is choppy, the stock is extended, volatility is
high, or the trend is weak. Vetoing on those is the twelve-point habit.

**Skip a name only if you can name the fact, and the fact is not on the chart.**
