# Round four: the liquidity course, run on the speaker's own definitions

You sent the 93-minute liquidity course after my first sweep test failed, so
that the rules would be his and not my paraphrase. That was the right call —
my first implementation was not his setup. This round rebuilds it from the
transcript and re-runs the full battery.

**Verdict: the reversal patterns carry a small, real, out-of-sample edge.
Used as a filter on your four strategies, every version of this makes them
worse. I do not recommend deploying any of it.**

---

## 1. What I had wrong the first time

Reading the course showed four material differences.

| | my first version (`sweep.py`) | the transcript |
| --- | --- | --- |
| the level | k=5 pivot lows | that is what he calls **internal** liquidity — "minor swing points", the easy ones. He says trade **external** liquidity, "simply the most obvious levels" |
| the pattern | one setup: break, reclaim, EMA retest | **three** patterns: grab, sweep, run — and the run goes the *other way* |
| confirmation | a 10/20 EMA retest (mine, not his) | a momentum candle: *"the real body of the momentum candles to be at least twice the size of the previous candle"* |
| discriminators | none | close far beyond + small wick + heavy volume = **run** (a real breakout). Close beyond with a big wick = **sweep** (a reversal) |

The last one matters most. I was treating every break of a low as a long,
which mixes a reversal setup together with its own failure case.

Rebuilt in `liq.py`:

- **grab** — "a fast and strong wick that pokes through a level and then
  immediately reacts": wick through the level, close back on the right side,
  same bar.
- **sweep** — "a slow liquidity grab": closes through, reverses within five
  bars, confirmed by a momentum candle (body ≥ 2× the previous body).
- **run** — "the price takes the level but keeps going": closes ≥ 0.5 ATR
  beyond, wick ≤ 30 % of range, volume ≥ 1.5×, body ≥ 2× the previous body.
  Traded **with** the break, not against it.
- **equal highs/lows** — pivots stacked within 1 % count as one deeper pool.
- **high vs low resistance** — low resistance forms after a failure swing,
  high resistance after a clean break.
- **targets** — the nearest untapped opposing pool, per *"once high
  resistance liquidity is taken the price tends to travel toward the low
  resistance liquidity"*.

14,593 setups, 472 symbols, 2021-04 to 2026-08.

The heat-map section of the course (walls, clouds, withdrawals, flips) needs
live order-book data. We have daily OHLCV. It is untestable here, and I have
not guessed at it.

## 2. Two bugs the tests caught first

Both were found by `test_liq.py`, not by inspection, and both would have
flattered the results.

**A setup that could not exist on its own day.** The detector refused to emit
anything within 5 bars of the end of data. Truncating the series at a setup's
own entry bar made the setup vanish — meaning it needed future bars to be
found. Moved that guard out to the builder, where it belongs.

**Equal lows repriced by the future.** Merging stacked pivots into one pool
let a touch that had not happened yet change the pool's price, its touch
count, and the bar it became knowable. In one case the target moved from
22,000 to 28,499 depending on whether later bars were visible. Levels are now
snapshotted per pivot, counting only already-confirmed touches — a cluster
appears as a sequence of progressively deeper levels, which is what a trader
watching it form actually sees.

## 3. The results, against a matched placebo

Long-only rules in a rising market beat zero for free, so everything is
measured against a placebo: same symbol, same month, same side, same stop
distance, random bar. Both a same-month and a forward-only placebo are shown,
because they disagree, and the disagreement is the finding.

No target, 60-bar time exit, costs in.

| pattern | n | setup % | same-month placebo | forward placebo | edge (fwd) |
| --- | --- | --- | --- | --- | --- |
| grab long | 2,523 | +2.24 | −0.84 | +1.37 | **+0.87** |
| sweep long | 2,949 | +2.27 | +0.66 | +2.02 | +0.25 |
| **run long** | 1,620 | **+4.55** | **+9.86** | +3.39 | +1.16 |
| grab short | 3,691 | −1.73 | −2.82 | −1.87 | +0.14 |
| sweep short | 3,318 | −2.14 | −2.95 | −2.13 | −0.01 |
| run short | 492 | +0.06 | −0.40 | −0.67 | +0.73 |

**The run is the headline and the trap.** It returns +4.55 %, the best of any
pattern — and random entries in the same stock in the same month returned
**+9.86 %**. The run finds an excellent stock and then enters it at close to
the worst available moment. (The same-month placebo is unfair to a breakout,
since it can enter before the run's own move; the forward-only placebo cuts
the edge from −5.31 to +1.16. The truth is in between, and either way most of
the +4.55 % is the stock, not the timing.)

Every discriminator the speaker names does work *within* the runs — bigger
body, more volume and a clean break all sort the outcomes correctly:

| filter | n | avg % |
| --- | --- | --- |
| all runs | 1,620 | +4.55 |
| body ≥ 3× previous | 1,353 | +5.12 |
| body ≥ 3× and volume ≥ 3× | 995 | +5.58 |
| + level was high-resistance | 573 | +6.78 |

The ordering is his and it is correct. It just never catches the placebo.

And the warning works in the other direction too. On the reversal patterns,
**heavy volume on the breaking candle makes them worse** — sweeps break down
from +1.37 % on quiet volume to −2.13 % above 3× — which is exactly what he
says: heavy volume on the breaking candle means a run, not a sweep.

**His target rule is worse than no target.** On the 13,527 setups with an
untapped opposing pool: liquidity target −0.40 %, 8 ATR −0.27 %, no target
+0.11 %. Median reward:risk offered was 3.2, but reaching it was rarer than
the geometry suggests.

## 4. The one rule that survived a held-out test

Ranked 18 refinements on 2021-2023 only, then read 2024 onward once.

Best on train: **grab or sweep, long, weekly 20-SMA up more than 5 % over six
weeks** — your own original hypothesis, that the weekly trend should be
sharply up. It held.

| period | n | raw | placebo | edge | 95 % CI | P(edge > 0) |
| --- | --- | --- | --- | --- | --- | --- |
| full window | 1,014 | +3.36 % | +1.84 % | **+1.53 pp** | [+0.11, +3.11] | 98 % |
| 2021-2023 (train) | 456 | +4.99 % | +3.69 % | +1.30 pp | [−0.67, +3.46] | 91 % |
| 2024-2026 (held out) | 558 | +2.03 % | +0.32 % | **+1.71 pp** | [−0.32, +3.87] | 94 % |
| **last 2 years** | 335 | **−0.25 %** | −0.60 % | **+0.35 pp** | [−1.49, +1.85] | 66 % |

CIs are month-block bootstrapped, because signals arrive in clusters and rows
are not independent.

It is a slope and not a fitted cliff, which is the main reason I believe it at
all — the edge rises monotonically with the threshold (0 % → +0.88 pp, 2 % →
+0.97, 5 % → +1.53, 8 % → +1.51, 12 % → +2.77) instead of spiking at the one
value I picked. 8 of 18 refinements were positive in both halves.

But read the last row. **In your own 2-year window it earns −0.25 % a trade
and the edge is +0.35 pp with 66 % confidence — which is a coin flip.** Win
rate 30 %, median trade −3.78 %, about 191 signals a year across 472 stocks.

## 5. As a filter on your strategies, it is harmful

This was your actual question — keep only stocks behaving this way. Two
versions, both tested with a period split.

**Filtering by a recent run** (the momentum reading) looks excellent and is a
regime artefact:

| strategy | 2021-2023 | 2024 | 2025+ | last 2 years |
| --- | --- | --- | --- | --- |
| S1 | **+2.16** | −0.23 | +0.18 | −0.20 |
| S2 | **+2.36** | −1.83 | −0.29 | −0.14 |
| S3 | +0.59 | −0.87 | +0.49 | +0.04 |
| S4 | **+4.08** | −2.36 | −2.98 | −2.94 |

(difference in average % per trade, kept minus dropped)

Every gain is in 2021-2023 and every one reverses afterwards. On the full
window S4 reads +5.12 % vs +3.98 % and looks like a real filter. Split by
period, it is a momentum tilt that stopped paying in 2024.

**Filtering by a qualifying reversal** — the rule that did survive — is worse:

| | 2021-2023 | 2024-2026 | last 2 years |
| --- | --- | --- | --- |
| GTF 7/7 | −0.67 | −0.29 | **−1.22** |
| S1 | +4.14 | −0.24 | −1.60 |
| S2 | +5.84 | −1.30 | −2.17 |
| S3 | +0.48 | −0.71 | −1.10 |
| S4 | −2.11 | +0.66 | −1.05 |

GTF is hurt in all three periods. Everything else is hurt in both held-out
ones. A rule with a small standalone edge is not the same thing as a useful
filter: it selects a *different* population from the one your strategies
already select, and the overlap is worse than either.

## 6. What I would take from this

1. **Don't deploy it.** Nothing here beats what you already have, and as a
   filter it costs about 1 percentage point a trade in the recent period.
2. **The run finding is worth remembering.** Stocks that take liquidity and
   keep going returned +9.9 % from random entries in the same month. The
   selection is excellent; the breakout bar is a bad entry. If anything in
   this round is worth another look, it is that gap — but the obvious way to
   exploit it (run picks the name, a pullback times it) I tested in section 5
   and it did not work.
3. **The speaker's discriminators are sound even though the trade is not.**
   Body size, wick size and breakout volume genuinely separate continuation
   from reversal. That classification is worth keeping as context on any
   breakout, and it is the one part of the course I would trust.
4. **Your weekly-trend hypothesis was the best single filter tested**, chosen
   on train and confirmed held out. It is just too weak in the last two years
   to build on.

Two rounds now — my reading and his — have failed to turn liquidity sweeps
into anything tradeable on this data. I would stop here and spend the effort
on the **short side**, which is still completely untested and remains the
largest unexplored thing in this project.
