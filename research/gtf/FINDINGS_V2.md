# Round two: learning from the data instead of from the video

You asked me to study the winners and build something with much better returns.
Here is what that produced, what it cost, and where it stops.

**Two things up front.** I could not build a foolproof strategy, and I did not
find mind-blowing ROI. What I did find is a real, walk-forward-validated
improvement in *risk-adjusted* return that still does not beat buying the index
on raw return over this window. Everything below is measured with the model
**refit every quarter on past data only** — no fold ever sees its own future.

---

## 1. Why "study the winners" needs handling

A winner is defined by its outcome, so any feature you find by looking at
winners is guaranteed to separate them *in the sample you looked at*. I ran the
literal version anyway (`analysis_winners.py`, section 1) and used it only as a
hypothesis list. Everything that follows is scored by models that never saw the
labels they were graded on.

---

## 2. Better exits — the first real gain

Average favourable excursion over 60 bars is +21%, so the fixed +4 ATR target
was leaving the tail behind. `build_exits.py` walks each trade's real path under
twelve policies (trailing, breakeven, partials, wider statics).

| exit | train | val | test | edge over placebo (train) |
| --- | --- | --- | --- | --- |
| fix 2/4 (old) | +3.30 % | +2.88 % | +3.28 % | +2.11 |
| fix 2/6 | +4.16 % | +3.24 % | +4.20 % | +2.33 |
| **fix 2/8** | **+4.68 %** | **+4.07 %** | **+4.45 %** | +2.34 |
| trail 2/3 | +3.70 % | +0.84 % | +3.37 % | **+2.52** |
| half at 2, trail 3 | +2.68 % | +1.16 % | +2.70 % | +1.94 |

Two findings. **Trailing stops did not survive out of sample** — trail 2/3 has
the largest training edge and collapses to +0.84 % in validation. **Static wide
targets did.** And the edge over the placebo is a flat +1.6 to +2.5 % band
across every policy: the information is in the entry, not the exit.

Widening the target from 4 to 8 ATR is worth roughly +1.2 % per trade, and about
half of the raw gain is drift the placebo also collects.

---

## 3. A learned score — where the video's failed

The GTF 7-point score is inversely predictive. A gradient-boosted model on the
same 27 features, cross-validated by month inside train, is not:

| decile of predicted return | train (out-of-fold) | validation | test |
| --- | --- | --- | --- |
| bottom | −0.96 % | +0.83 % | −0.36 % |
| top | **+8.71 %** | **+7.21 %** | **+2.75 %** |

Monotone on data the model never touched. The top feature by permutation
importance is **`w_trend50`** — the video's own weekly trend rule, which was
useless on its own and turns out to matter conditionally. That is the sort of
thing a univariate screen cannot see.

### Fully walk-forward, refit every quarter

| signal set | n | win % | avg % | PF |
| --- | --- | --- | --- | --- |
| every arrival | 92,455 | 35.6 | +2.16 | 1.49 |
| matched placebo | 93,242 | 30.8 | +0.78 | 1.17 |
| five hand rules | 4,350 | 43.6 | +4.72 | 1.91 |
| learned score | 3,981 | 48.6 | **+7.64** | **2.46** |
| rules AND score | 749 | 50.6 | +7.53 | 2.32 |

Positive in every one of five calendar years. Bootstrap 95 % CI on mean percent:
`[+2.81, +13.04]`.

---

## 4. Then I took the illiquidity away, and half of it went

The model leans small: median turnover 14.3 Cr/day against 48.3 for all
arrivals, and 19.6 % of its picks trade under 5 Cr/day. Our 0.23 % cost model
does not price impact in names like that. Removing `turnover` from the feature
set and imposing a 10 Cr/day floor:

| | avg % | CAGR | Sharpe |
| --- | --- | --- | --- |
| learned score, as fitted | +7.64 | 32.6 % | 2.11 |
| no turnover feature | +5.33 | 27.4 % | 1.91 |
| + 10 Cr/day floor | +4.82 | 22.0 % | 1.62 |
| + 25 Cr/day floor | +4.08 | 19.1 % | 1.47 |

**A large part of the apparent outperformance was a small-cap tilt that probably
cannot be harvested.** This is the single most important line in this document.

Model-choice variance says the same thing: across depths 2-5 and three seeds,
CAGR ran 20.3 % to 30.3 %. The 32.6 % headline was the lucky end, not the centre.

---

## 5. Did the model actually beat the hand-written rules?

Identical guards on both — no turnover feature, approach capped at 9.66 %,
10 Cr/day floor — 30 slots, unlevered, walk-forward:

| signal set | n | win % | avg % | PF | CAGR | max DD | Sharpe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| five hand rules | 4,534 | 42.2 | +3.97 | 1.75 | 11.8 % | −19.0 % | 1.30 |
| learned score | 7,472 | 41.4 | +4.21 | 1.71 | 19.2 % | −17.1 % | 1.65 |
| rules **and** score | 1,389 | **45.9** | **+5.26** | **1.88** | 6.9 % | −11.6 % | 1.05 |
| rules **or** score | 10,617 | 41.1 | +3.97 | 1.70 | **21.3 %** | −19.2 % | **1.85** |

The honest reading: **the model helps mainly by finding more tradeable signals,
not better ones.** Per trade it is a wash with the hand rules (+4.21 vs +3.97).
The intersection has the best trades by some distance (+5.26 %, PF 1.88, 45.9 %
wins) and is useless as a portfolio because 1,389 signals cannot fill 30 slots.
The union wins on CAGR and Sharpe purely on capacity.

---

## 6. The system, and the benchmark

Production configuration — rules-or-score, guards on, unlevered, 1.5 % risked
per trade, one position per symbol, 30 slots, median of 8 random selection
orders:

| | CAGR | max DD | Sharpe | corr with index |
| --- | --- | --- | --- | --- |
| **GTF-D14** | **21.3 %** | −19.2 % | **1.85** | **−0.13** |
| equal-weight universe, buy and hold | **23.4 %** | −21.4 % | 1.32 | 1.00 |

Calendar years for the tighter production set: +54.6 %, +27.7 %, **−11.1 %**,
+14.0 %. There is a losing year in there, and the earlier version that showed
+16.3 % for 2025 was being carried by the illiquid names.

So: **lower raw return than the index, materially better risk-adjusted return,
and near-zero correlation with it.** That is a diversifier, not a replacement.

---

## 7. What changed from round one

| | round one | round two |
| --- | --- | --- |
| exit | fixed 2 ATR / 4 ATR | fixed 2 ATR / **8 ATR** |
| selection | five hand rules | rules **or** learned score |
| validation | one train/val/test split | **quarterly walk-forward refit** |
| per trade | +2.84 % | +3.97 % on 2.4× the signals |
| Sharpe (as deployed) | 0.94 | **1.85** |
| max DD | −18.7 % | −19.2 % |

---

## 8. What would actually move the needle, and why I did not just do it

* **Leverage.** At −0.13 correlation and Sharpe 1.85, 1.5× gross would clear the
  index on return with similar drawdown. That is a capital decision, not a
  research finding, and I am not going to bury it in a config file.
* **The short side.** Supply zones are detected and still untested. A working
  short leg would roughly double capacity and cut the long-only regime risk.
  This is the largest unexplored gain in the whole study.
* **Intraday execution.** The video's own best-rated sets (HIT/DIT) need 15- and
  60-minute candles we do not store.
* **Survivorship.** Everything here still runs on today's Nifty 500 applied
  backwards. The probe in `FINDINGS.md` §6 bounds it; it cannot remove it.

## 9. What I would not do

Push the numbers further by relaxing the liquidity floor, or by picking the
model seed and exit policy that print the best figure. Both are available and
both are how a backtest stops being evidence. The spread across seeds
(20.3-30.3 % CAGR) is the honest uncertainty, and the centre of it is what I
have quoted.

---

## 10. The last two years on their own — a correction

The 21.3 % CAGR in §6 covers 2022-01 to 2026-09 and is **front-loaded**:
+54.6 %, +27.7 %, −11.1 %, +14.0 %. Asked for the last two years specifically
(2024-09-04 to 2026-09-04), the answer is much worse and it should be the
headline anyone acts on.

| | GTF-D14 | equal-weight buy & hold |
| --- | --- | --- |
| **total return, 2 years** | **+2.4 %** | **+7.9 %** |
| CAGR | +1.2 % | +3.9 % |
| max drawdown | −18.9 % | −21.4 % |
| Sharpe | 0.21 | 0.31 |

Signal quality over those two years is fine: 5,608 signals, **39.2 % wins,
+3.05 % per trade, profit factor 1.53**, average winner +22.6 %, average loser
−9.5 %.

**The portfolio destroys it, and the reason is capacity.** Only **472 of 5,608**
signals can be taken at 30 slots — and the ones actually taken average
**+0.48 %, not +3.05 %.**

Signals arrive in bursts, and the bursts are selloffs: 2,806 of the 5,608 came
in the half-year to 2025-03, which averaged +0.5 % on a 32 % win rate. The slots
fill on the way down with the early, poor trades in the cluster; the good ones
(the half-years to 2025-09 and 2026-09 averaged +8.9 % and +7.4 %) arrive when
there is no capacity left.

Slot sensitivity confirms the mechanism — 10 slots −1.0 %, 30 slots +6.8 %,
80 slots +9.2 % — and the spread across random selection orders (−1.1 % to
+8.8 %) is wider than the result itself. Over this window the outcome is
**noise-dominated**.

### What this means

The per-trade edge is real and survives walk-forward. **It does not survive
contact with a capacity-constrained portfolio in a clustered-signal regime.**
Fixing that is a queueing and capital-allocation problem — staged entry through
a cluster, reserving slots, or sizing by signal strength rather than first-come
— and none of it has been tested here. Until it is, the honest number for the
last two years is **+2.4 %**.

---

## 11. The 7/7 correction — the score was fine, my stop was not

Asked to trade only the video's 7-out-of-7 zones. That contradicts §2 of
`FINDINGS.md`, which found the GTF trade score inversely predictive. Both are
true, and the reconciliation is the useful part.

| GTF score | n | avg R, **distal stop**, 2R target | avg %, **2 ATR stop**, 8 ATR target | median zone width |
| --- | --- | --- | --- | --- |
| 1.0 | 1,616 | **+0.166** | +2.03 % | 5.19 % |
| 3.0 | 14,704 | +0.008 | +2.31 % | 2.45 % |
| 4.5 | 20,980 | −0.000 | +2.38 % | 2.32 % |
| 6.0 | 30,976 | **−0.063** | +2.24 % | 2.21 % |
| **7.0** | 7,710 | **−0.015** | **+3.14 %** | 2.19 % |

With the video's own distal stop the score is inversely predictive. With a
volatility stop the inversion vanishes and **7/7 becomes the best bucket**.

The mechanism is the one from `FINDINGS.md` §2, pointed the other way. A 7/7
zone is among the thinnest (median 2.19 % against 5.19 % at score 1), so a stop
on its distal line sits inside the daily noise. **That penalty was never a
statement about zone quality — it was a statement about where the stop was.**
Move the stop off the zone and the score's real content shows through.

I got this wrong the first time by testing the score and the stop together and
attributing the result to the score. The correct reading: **the video's quality
score works; the video's stop placement does not.**

### What 7/7 is worth

Last two years (2024-09-04 to 2026-09-04), 15 slots, unlevered:

| set | signals | win % | avg % | PF | total 2 yr | CAGR | max DD | Sharpe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 7/7 only | 3,561 | 33.5 | +1.48 | 1.33 | +12.4 % | 6.0 % | −19.1 % | 0.64 |
| 7/7 + high-vol | 1,922 | 39.5 | +3.36 | 1.71 | +11.8 % | 5.7 % | −16.6 % | 0.61 |
| **7/7 + ≥10 Cr + high-vol** | 1,862 | **39.3** | **+3.24** | **1.69** | **+17.0 %** | **8.2 %** | **−12.7 %** | **0.89** |
| 7/7 + ≥10 Cr + hv + EMA200 | 1,221 | 43.2 | +4.71 | 2.07 | +7.2 % | 3.5 % | −17.9 % | 0.44 |
| *GTF-D14 (the learned system)* | 5,608 | 39.2 | +3.05 | 1.53 | *+2.4 %* | *1.2 %* | *−18.9 %* | *0.21* |
| *benchmark, buy and hold* | — | — | — | — | *+7.9 %* | *3.9 %* | *−21.4 %* | *0.31* |

**7/7 + liquidity + volatility gate beats the benchmark on every measure over
the last two years** — more than double the return, 60 % of the drawdown, near
three times the Sharpe — and it beats my own learned system by 7×.

Full window, same config: +158.5 %, CAGR 19.2 %, max DD −13.6 %, Sharpe 1.66,
against the benchmark's +284.2 %, 28.3 %, −21.4 %, 1.57. Lower return, better
risk-adjusted return. Without the liquidity floor, 7/7 alone returns +261 % at
Sharpe 1.85.

### Why it fixes the capacity problem

§10 showed the failure was that only 472 of 5,608 signals fit the slots, and the
ones taken averaged +0.48 % against the pool's +3.05 %. Filtering to 7/7 with the
two gates cuts the pool to 1,862 and lifts **the average of trades actually
taken to +1.92 %**. Fewer, better signals fill the slots better. Adding the
EMA200 filter on top makes per-trade quality higher still (+4.71 %) and the
portfolio worse (+7.2 %) — past a point, quality starves deployment.

### Caveats

* The 7/7 rule itself has **zero parameters fitted by me** — it is the video's,
  used as given. That is the lowest overfitting risk of anything in this study.
* The exit, the liquidity floor and the volatility gate were all chosen earlier
  with sight of the full data. That selection bias is not zero.
* 150 trades actually taken over two years. Selection-order spread is material.
* Still long-only, still survivorship-biased, still one market.
