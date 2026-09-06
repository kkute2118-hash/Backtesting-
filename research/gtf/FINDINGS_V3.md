# Round three: the ratchet stop, and a new scoring system

Three requests: replace the S1-S4 marking system using winner data, design a
progressive stop, and push the GTF top-quality returns further.

---

## 1. The ratchet stop — your instinct, tested

You proposed: at +5 % move the stop to −3 %, at +8 % to breakeven, then to +2 %.

### First, what the paths say

For every 7/7 trade, once price has reached +X %, what happens afterwards:

| reached | share of trades | median worst point after | give back to 0 % | give back to −3 % | median best point after | goes on to +25 % |
| --- | --- | --- | --- | --- | --- | --- |
| +3 % | 88.8 % | −5.6 % | **83.8 %** | 64.0 % | +15.7 % | 27.7 % |
| **+5 %** | 81.4 % | −3.8 % | **71.3 %** | 53.8 % | +17.0 % | 30.2 % |
| **+8 %** | 70.0 % | −0.7 % | 53.9 % | 39.8 % | +19.2 % | 35.1 % |
| +10 % | 63.0 % | +1.0 % | 45.5 % | 33.4 % | +20.9 % | 39.0 % |
| +15 % | 46.3 % | +6.1 % | 26.6 % | 18.8 % | +26.0 % | 53.1 % |
| +20 % | 33.3 % | +10.8 % | 16.2 % | 10.9 % | +30.8 % | 73.9 % |

The give-back is real and large: **71 % of trades that reach +5 % come back to
breakeven or below.** That is exactly the problem you are pointing at.

But the same rows carry the counter-argument. Of the trades that reach +5 %,
**30 % go on to +25 %**, and the median best point afterwards is +17 %. The
question is not whether give-back exists — it does — but whether protecting
against it costs more than it saves.

### Per trade, it costs more than it saves

Twelve schedules, same 7,062 trades:

| schedule | win % | avg % | avg win | avg loss | PF | median bars |
| --- | --- | --- | --- | --- | --- | --- |
| **atr: breakeven at +4 ATR only** | 31.5 | **+2.72** | +21.4 | −5.9 | 1.68 | 27 |
| baseline (no ratchet) | 37.7 | +2.64 | +18.4 | −6.9 | 1.61 | 24 |
| breakeven only at +15 % | 31.8 | +2.62 | +20.8 | −5.9 | 1.65 | 27 |
| atr: 3→0, 6→+3 | 31.2 | +2.40 | +19.4 | −5.3 | 1.66 | 22 |
| later: 8→−3, 12→0, 20→+5 | 30.2 | +2.06 | +18.5 | −5.1 | 1.58 | 20 |
| **your plan: 5→−3, 8→0, 12→+2** | 33.7 | **+1.73** | **+13.7** | −4.3 | 1.60 | **14** |
| your plan + 8 ATR target | 33.8 | +1.43 | +12.7 | −4.3 | 1.50 | 14 |

Your schedule is last of the twelve, and the mechanism is in the `avg win`
column: **it cuts the average winner from +18.4 % to +13.7 %.** It does reduce
the average loss (−6.9 → −4.3), but in a system where 33 win and 67 lose, the
winners are what pays. Trimming the tail by a quarter is not covered by smaller
losses. Same story in train, validation and test (+2.55 / +1.54 / +0.61 against
the baseline's +3.42 / +2.80 / +1.19).

### But at the portfolio level you were right

A ratchet ends trades sooner — your schedule holds a median 14 bars against the
baseline's 24 — and §10 of `FINDINGS_V2.md` established that **slots, not
signals, are the binding constraint.** Faster turnover buys more trades.

Last two years, 15 slots, unlevered:

| schedule | avg % / trade | median bars | trades taken | total 2 yr | CAGR | max DD | Sharpe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **breakeven only at +15 %** | +2.85 | 24 | 146 | **+21.5 %** | **10.2 %** | −15.7 % | **0.87** |
| atr: 3→0, 6→+3 | +2.55 | 20 | 166 | +20.8 % | 9.9 % | −17.8 % | 0.81 |
| later: 8→−3, 12→0, 20→+5 | +1.86 | 17 | 172 | +19.6 % | 9.4 % | −13.8 % | 0.81 |
| **your plan: 5→−3, 8→0, 12→+2** | +1.60 | **11** | **215** | **+17.3 %** | 8.3 % | −18.6 % | 0.78 |
| baseline (no ratchet) | +3.12 | 24 | 150 | +16.1 % | 7.7 % | −12.7 % | 0.84 |
| *benchmark* | — | — | — | *+7.9 %* | *3.9 %* | *−21.4 %* | *0.31* |

**Your plan beats the baseline on the portfolio** (+17.3 % against +16.1 %) even
though it is the worst per trade — 215 trades taken instead of 150. The
turnover pays for the worse trade.

Over the full window it does not: baseline +159.0 %, your plan +132.9 %. Slots
were scarcer in the last two years because the signals cluster into selloffs.

### What to actually use

**Breakeven only, at +15 % (or ~+4 ATR).** It is the best schedule in the recent
window (+21.5 %, Sharpe 0.87), near the best per trade (+2.85 %), and it does
what you wanted — stops a winner turning into a loser — without strangling the
tail. Its median hold is unchanged at 24 bars, so it is not buying its result
with turnover; it is genuinely a better trade.

The lesson from the losing variants is about **timing, not the idea**. Ratchet
at +5 % and you are inside the noise: 83.8 % of trades that reach +3 % and
71.3 % of those that reach +5 % dip back to breakeven, and most of those
recover. Wait until +15 %, where only 26.6 % dip back, and the move is nearly
free.

---

## 2. The S1-S4 marking system — I could not rebuild it, and that is the finding

You asked me to replace the scoring system using the winners. I regenerated all
**210,409 ungated S1-S4 signals** with the look-ahead-fixed engine (the 273,688
rows already in the store predate commit a30a00e, so they were not evidence),
and tried.

### The existing score, after the fix

| score band | n | avg R train | avg R val | avg R test |
| --- | --- | --- | --- | --- |
| 0-49 | 4,369 | +0.215 | −0.167 | +0.032 |
| 50-59 | 42,124 | +0.516 | −0.185 | +0.032 |
| 70-74 | 41,918 | +0.504 | +0.004 | −0.039 |
| 80-84 | 23,846 | +0.606 | −0.043 | −0.011 |
| 85-89 | 7,916 | +0.555 | −0.125 | −0.043 |
| **90-100** | 722 | +0.373 | **−0.120** | **−0.134** |

Under 70 gives +0.142 R; 85 and over gives +0.169 R. **The strong inversion the
audit found is gone after the look-ahead fix — the score is now simply flat.**
That corrects what I told you earlier: it was contamination, not a real
inversion, across most of the range. But the top of the scale is still the worst
part of it, in both held-out periods.

And the live gate does not earn its place:

| selection | n | win % | avg R | PF |
| --- | --- | --- | --- | --- |
| every signal | 194,266 | 36.6 | **+0.186** | 1.30 |
| **old score ≥ 85 (the live gate)** | 8,347 | 34.0 | **+0.154** | 1.24 |
| old score ≥ 90 | 694 | 30.3 | +0.042 | 1.06 |

**Gating at 85 selects worse than taking everything.**

### The replacement score failed

Same method that worked for GTF — 35 fingerprint features, gradient boosting,
refit every quarter on past data only, 194,266 signals scored out of sample:

| decile of the new score | avg R | win % |
| --- | --- | --- |
| 0 (lowest predicted) | **+0.234** | 37.6 |
| 4 | +0.204 | 36.7 |
| 9 (highest predicted) | **+0.126** | 35.5 |

**Monotonically backwards.** The model's ranking is anti-predictive out of
sample. Its top decile returns +0.183 R against +0.186 R for taking everything —
it adds nothing. Combining it with the old gate is worse than either
(−0.081 R, PF 0.89).

I am not going to dress this up. **S1-S4 signals are not rankable by these
features.** The honest answer to "build a new marking system" is that the data
will not support one, and shipping a score that cannot rank is how the current
one came to exist.

### What does separate them: which strategy, and the exit

| | full window | | last two years | |
| --- | --- | --- | --- | --- |
| strategy | avg R | PF | avg R | PF |
| S1 | +0.211 | 1.33 | **−0.102** | 0.86 |
| S2 | +0.296 | 1.50 | **−0.063** | 0.91 |
| S3 | +0.146 | 1.24 | **−0.142** | 0.79 |
| **S4** | **+0.398** | **1.65** | **+0.168** | **1.25** |

**Only S4 makes money in the last two years.** S1, S2 and S3 all lose, under
every exit tested. S4 is also the one whose record the audit dismissed as an
artefact of monthly look-ahead — post-fix it drops from 62.4 % wins and PF 4.46
to 39.4 % and PF 1.65, so most of that was the leak, but what is left is real.

And the exit matters more than any score:

| strategy | engine exit (7 % stop, 3R) | 2 ATR stop, 8 ATR target | breakeven at +15 % |
| --- | --- | --- | --- |
| S1 | +1.47 % | +2.17 % | **+2.96 %** |
| S2 | +2.07 % | +2.72 % | **+3.25 %** |
| S3 | +1.02 % | +0.95 % | **+1.51 %** |
| **S4** | +2.78 % | **+4.72 %** | +4.44 % |

Last two years, S4: **+1.17 % → +2.09 %** simply by changing the exit.

### What to change in S1-S4

1. **Delete the ≥85 gate.** It selects worse than random.
2. **Do not replace the score.** Two attempts, two failures. Rank by nothing.
3. **Trade S4 only.** S1, S2 and S3 have lost money for two years.
4. **Change the exit** to a 2 ATR stop with an 8 ATR target. That is worth more
   than any scoring change on the table.

---

## 3. Improving GTF — what worked and what did not

### Worked: the exit

Breakeven at +15 % on the 7/7 set lifts the last two years from **+16.1 % to
+21.5 %** and the Sharpe from 0.84 to 0.87.

### Did not work: allocation

§10 of `FINDINGS_V2.md` diagnosed the capacity failure as slots filling on the
way down through a cluster. That suggested throttling entries. It does not work:

| policy | total, last 2 yr | Sharpe |
| --- | --- | --- |
| **first come (current)** | **+21.5 %** | **0.87** |
| rank by ATR % | +19.7 % | 0.67 |
| rank by zone width | +19.3 % | 0.70 |
| max 5 new positions per day | +13.6 % | 0.62 |
| keep 25 % dry powder | +12.6 % | 0.67 |
| max 3 new per day | +8.7 % | 0.45 |
| max 2 new per day | +7.5 % | 0.41 |
| only when the index is above its 20-day MA | **−2.5 %** | −0.11 |

Throttling costs more than the bad early trades it avoids. And requiring the
index to be above its 20-day average destroys the strategy outright, which
confirms the shape of the edge: **it needs the selloff.** You cannot have the
good trades in a cluster without taking the early poor ones.

Over the full window ranking by ATR % does help (+194.7 % against +145.1 %), but
it does not carry to the recent window.

### Did not work: combining with S4

The two streams are uncorrelated (monthly correlation **−0.006**), which
normally argues for running both. It does not help here:

| system | last 2 yr | Sharpe | full window | Sharpe |
| --- | --- | --- | --- | --- |
| **GTF 7/7 alone** | **+21.5 %** | **0.87** | +145.1 % | **1.60** |
| S4 alone | +10.8 % | 0.55 | +128.2 % | 1.58 |
| both together | +10.0 % | 0.48 | +157.1 % | 1.52 |

They compete for the same 15 slots, and S4's weaker trades displace GTF's better
ones. Uncorrelated is not enough when capacity, not risk, is the constraint —
you would need separate books.

---

## 4. Where this leaves the answer to "improve the return"

Last two years, unlevered, 15 slots: **+21.5 %, CAGR 10.2 %, max DD −15.7 %,
Sharpe 0.87**, against buy-and-hold's +7.9 %, 3.9 %, −21.4 %, 0.31. That is up
from +16.1 % before this round, and it beats the benchmark on every measure.

What is left, in order of expected size:

1. **The short side.** Supply zones are detected and still untested. It would
   roughly double capacity and cut the long-only regime risk. Largest single
   gain available.
2. **Separate books** for GTF and S4 rather than one shared slot pool.
3. **Leverage**, at −0.13 correlation and Sharpe 0.87. A capital decision.
4. **More slots**, which helped modestly and monotonically.

What is exhausted: scoring, allocation throttles, ratchet schedules beyond a
single late breakeven move.

---

## 5. The liquidity sweep — tested, and it does not survive

The setup as described: price takes out a prior daily swing low, the weekly
trend is sharply up, it reclaims the low quickly on good volume, then retests
the 10/20 EMA and that retest is the entry. Coded in `sweep.py`, every step
point-in-time — a swing low is only usable once confirmed, which takes `k` bars,
and that delay is respected.

**4,309 setups** across 475 symbols.

### Standalone

| window | exit | n | win % | avg % | PF |
| --- | --- | --- | --- | --- | --- |
| full | 2 ATR / 8 ATR | 4,309 | 34.9 | +1.89 | 1.42 |
| full | breakeven at +15 % | 4,309 | 29.8 | **+2.36** | 1.57 |
| **last 2 years** | breakeven at +15 % | 1,684 | 21.4 | **−1.33** | **0.72** |

By year: −0.53, −1.28, **+9.57**, +3.50, −1.00, −0.12. The whole full-window
result is 2023.

### It is not my parameters

54 combinations of pivot width (3/5/10), reclaim window (1/3/5 bars), volume
threshold (1.0/1.5/2.0×) and which EMA is retested (10/20):

* **54 of 54 positive over the full window**
* **1 of 54 positive over the last two years**

Every parameterisation agrees. This is regime, not tuning.

### It adds nothing as a filter

GTF 7/7 signals split by whether a sweep-reclaim happened in the previous 20
bars:

| | n | win % | avg % | PF |
| --- | --- | --- | --- | --- |
| after a sweep | 881 | 32.0 | **+2.63** | 1.68 |
| no sweep | 6,181 | 31.8 | **+2.62** | 1.65 |

Identical. The sweep carries no information the GTF setup does not already have.

### Refining it makes it worse — and this is the useful part

Thresholds taken from pre-2024 data only, then the last two years read once:

| filter | train n | train avg % | train PF | **held out avg %** | **held out PF** |
| --- | --- | --- | --- | --- | --- |
| all setups | 1,761 | +3.71 | 1.92 | −1.33 | 0.72 |
| deep sweep | 881 | +3.84 | 1.96 | −1.53 | 0.68 |
| steep weekly trend | 705 | +4.97 | 2.15 | −1.69 | 0.67 |
| deep + steep | 353 | +6.33 | 2.52 | −1.67 | 0.68 |
| deep + steep + volatility | 214 | +8.09 | 2.84 | **−2.81** | 0.54 |
| **all four filters** | 148 | **+11.45** | **3.81** | **−2.26** | **0.61** |

**The more it is filtered, the better the training number and the worse the
held-out number.** That is the signature of fitting noise, and "+11.45 % per
trade at profit factor 3.81" is exactly the number that would be presented as a
breakthrough if only the training column were shown.

On the same held-out window and the same exit, GTF 7/7 returns +1.09 % (PF 1.25)
and S4 returns +1.01 % (PF 1.20). Both hold; the sweep does not.

### What this does and does not settle

It settles that **this reading of the setup** does not work on this data. It does
not settle the concept: the transcript may define the swing, the reclaim, the
volume condition or the entry differently — sweeping a *weekly* rather than a
daily swing, for instance, would be a materially different test, and so would
entering on the reclaim rather than waiting for the EMA retest. Send it and
those get tested against the speaker's own definitions rather than mine.

But the shape of the result is worth weighing first. The failure is not narrow —
54 of 54 parameterisations, no filter value, and zero incremental information
over a setup we already have.

### The other two additions asked for

* **Volume** — already in the study. It contributes, consistently but slightly:
  a +0.02 to +0.08 spread top-versus-bottom quintile after controlling for zone
  width. Worth keeping, not worth building around.
* **Market trend** — tested in §3. Requiring the index above its 20-day average
  returns **−2.5 %** and destroys the edge. This family of setups needs the
  selloff.
* **Sector support** — **cannot be tested. There is no sector mapping in the
  candle store**, which the prior audit also recorded under `not_assessed`.
  Adding a symbol→sector table is a small piece of work and would open up both
  sector-relative strength and sector-breadth filters. It is the most useful
  unblocked thing on this list.
