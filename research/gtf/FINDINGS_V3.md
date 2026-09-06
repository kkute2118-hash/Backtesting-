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
