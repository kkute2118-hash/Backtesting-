# Findings — entry timing

Built the entry engine from the case-study PDFs and tested the question it
exists to answer: **does waiting for his entry beat buying when the scanner
fires?**

Same candidates, same exits, one difference — the entry bar. Golden fixture,
161 symbols, 22,452 signals.

---

## The answer: no, and the control row is why we can say so

| | n | win | mean |
|---|---|---|---|
| IMMEDIATE — all signals | 22,452 | 29.2% | −0.07% |
| **IMMEDIATE — the ones that later triggered** | 11,092 | 38.7% | **+2.26%** |
| **WAITED — his entry** | 11,092 | 28.8% | **−0.13%** |

The middle row is the control, and it is the whole experiment. Comparing
WAITED (−0.13%) against IMMEDIATE-all (−0.07%) looks like a wash. But those
11,092 candidates were *good* — bought on the scan bar they return **+2.26%**.
Waiting for his trigger gives back **2.39 percentage points**.

Without the control this would have read as "no effect". It is a large
negative effect on a subset that was better than average to begin with.

---

## Why: the cost scales exactly with how long you wait

| wait | n | immediate | waited | given up |
|---|---|---|---|---|
| 1 bar | 1,168 | −0.21% | −0.21% | **0.00** |
| 2 bars | 1,116 | +0.34% | −0.05% | −0.39 |
| 3–4 | 1,963 | +0.38% | −0.44% | −0.82 |
| 5–8 | 3,077 | **+2.79%** | −0.34% | **−3.13** |
| 9–16 | 3,768 | **+4.14%** | +0.22% | **−3.92** |

Two things read off this at once. The give-up grows monotonically with the
wait — and the *immediate* return grows too, from −0.21% to +4.14%. Candidates
whose trigger arrives late are the ones that moved hard in the meantime. **The
trigger is firing after the move, not before it.**

### The root cause: S1–S5 already fire where he enters

His sequence is expansion → contraction → entry. You find the stock during the
expansion, put it on a watchlist, and wait for the pullback.

Our scanners are pullback scanners. S3 is an EMA50 pullback. S2 is a tight
pullback. They fire *at* the contraction — which is the bar he would buy. Layer
his entry timing on top and you are waiting for a *second* contraction after
the one the scanner already found.

That is double-counting, and the wait-length table is what it looks like when
measured.

---

## What did work: the stop

The mechanism reproduces his stops accurately.

| | median stop |
|---|---|
| Our flat stop on the scan bar | 7.00% |
| His entry, all triggers | **4.16%** |
| M10 (pullback to the 10 EMA) | **3.72%** |
| V25 (value zone, 20–50 EMA) | **2.79%** |
| *Case studies: daily STF* | *3%* |
| *Case studies: weekly STF* | *6%* |

V25 at 2.79% and M10 at 3.72% land essentially on the case studies' stated 3%
for a daily STF. **The entry engine does what it was built to do.** It locates
the demand candle and puts the stop under it, and the resulting risk distances
match his published numbers.

It just does not produce better trades on our signals.

---

## Tighter stops are worse — third independent confirmation

Among waited entries, by stop width, using his pivot stop and 10-EMA exit:

| quartile | median stop | mean R |
|---|---|---|
| Q1 tightest | 1.59% | **−0.145R** |
| Q2 | 3.26% | +0.003R |
| Q3 | 5.36% | −0.050R |
| Q4 widest | 10.19% | **+0.067R** |

This is now the third time, on three different constructions, that tighter
stops have predicted worse outcomes: the gate-stack ranking in run 2, the
risk-distance quartiles across all signals, and now within his own entries.

It is a robust property of our data, not an artefact of one implementation.

### His stated defence does not rescue it

He is explicit about what to do when a tight stop gets taken out by noise:
*"whether it looks like this, dips a little bit below, takes your SL, goes up
and does it again — well, then you enter it again. Because if you don't, then
you will not make that system work for you."*

Modelled as up to two re-entries on the next trigger after each stop-out:

| | mean % | mean R |
|---|---|---|
| Waited, pivot stop | +0.055% | −0.031R |
| **Waited + re-entry** | +0.023% | **−0.039R** |

1,050 re-entries across 948 trades, and it is slightly *worse*. The defence
does not close the gap.

---

## Coverage

- **49.4%** of signals ever produce an entry inside a 15-bar window. Median
  wait 6 bars.
- By trigger: M10 6,083 · cross-then-IB 3,928 · V25 1,000 · V12 81.
- The cross-then-IB trigger has the **widest** stop of the four (7.47% median)
  because it fires away from the averages — lecture 5's case-4 problem, showing
  up exactly where that lecture predicts.

---

## Conclusion

**Do not add entry timing.** It is well-built, it reproduces his stop widths,
and it costs 2.39 points per trade because our scanners already occupy the
position in his sequence that it is designed to fill.

Two things remain worth having, both from earlier runs and both unaffected by
this:

- **CB purity** as a ranker — −1.06% / −0.74% / +1.63% / +0.40% by quartile,
  with a 50–75% sweet spot and a sharp fall above that.
- **Volume cluster vs single tower** — −0.62% against +0.06%.

Both are continuous measures over all 22,452 signals, both come straight from
the source material, and neither requires changing when we buy.

**One sub-case is worth a second look:** V25 entries carry a 2.79% median stop
and are roughly breakeven on the flat exit (+0.05%) against +0.07% immediate —
i.e. no give-up at all, at 40% of the risk. Small sample (n=1,039) and a
negative R under the pivot exit (−0.146R), so it is a lead rather than a
result.

**Standing caveats:** two years, 161 symbols, no transaction costs, no
train/test split, and the whole sample used for every measurement. And the
intraday gap remains — his 3% stop comes from a 15-minute entry inside the
daily pullback, and we hold daily bars only.
