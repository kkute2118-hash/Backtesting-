# Addendum — the two RichRoad case-study PDFs

Sources: `SDBL_Case_Study_RichRoad.pdf` (17pp) and the Kalyan Jewellers case study
(18pp), both RichRoad Trading Academy. These are written documents rather than
transcripts, so the terminology is defined rather than inferred — they resolve
several things the lectures left open, and they contradict one thing I had assumed.

---

## 1. CB = Committed Buyers — confirmed, and it is not a volume measure

Both PDFs carry the same glossary:

```
TTF : Trend Timeframe        DC  : Demand Candles
STF : Setup Timeframe        IB  : Inside bar
ETF : Execution Timeframe    CB  : Committed Buyers
```

Also confirming the MA legend exactly as reconstructed from the transcripts: black
10 EMA, blue 20 EMA, green 50 EMA, orange/red 200 MA.

The most useful line for what a CB *is*:

> "now we have a red candle on the Monthly indicating that the M Buyers are getting
> relaxed now, who knows for how long, **whenever they get active again, we'll see
> them pop up on Daily as CBs**."

A CB is the **higher-timeframe buyer's footprint on the lower timeframe**. That is
exactly consistent with the user's definition — a day the stock performed
extremely well compared with its own other good days — and with CB sitting beside
DNA and relativity in his own list.

### The volume question — measured, not assumed

The PDFs do associate CBs with volume:

> "Towards the end, we started getting **white candles with no blue CBs present,
> signaling weak up move on low volumes**."

That reads as though a CB requires elevated volume, so I tested three definitions
of CB purity over the same 22,530 signals:

| CB definition | ≥50% purity | <50% purity | spread |
|---|---|---|---|
| **Return percentile only** | **+0.303%** | −0.100% | **+0.403%** |
| Volume elevation only | −0.457% | +0.055% | −0.511% |
| Return AND volume | −0.389% | −0.049% | −0.340% |

**The pure-return definition is the one that works.** Requiring volume as well
*destroys* the signal, and volume elevation on its own is predictive in the wrong
direction on our data.

So the implementation stays a relative-return measure. The PDFs' pairing of CBs
with good volume is a real observation about his charts; it is not a usable part of
the definition here.

### CB purity is inverted-U, not monotonic

Binning by purity of the ten bars before the signal:

| CB purity | n | mean return |
|---|---|---|
| none | 8,857 | −0.26% |
| 0–25% | 8,024 | +0.07% |
| 25–50% | 4,751 | −0.02% |
| **50–75%** | 795 | **+0.67%** |
| 75–100% | 103 | **−1.61%** |

The sweet spot is 50–75%. Above that it turns sharply negative — which is what his
own extension warnings predict, and matches the earlier quartile run where Q3 beat
Q4. **CB purity should be scored as a band, not "more is better."**

---

## 2. The fractal confluence rule — new, precise, and the key to his stop

Stated twice, near-verbatim in both case studies:

> "So basically **D went to 10 MA** as it was Base1 checked by Relativity, DNA and
> Location, **which was Hourly going to 50 MA** and the move started when **15min
> touched its 200MA**."

> "We got a proper M10. **Daily comes to 10 EMA. Hourly to 50 EMA. 15 min to 200 MA**
> and begins a fresh Stage 2."

One pullback, read at three scales simultaneously. He does not enter when the daily
touches its 10 EMA — he waits for the 15-minute to reach its 200 MA *inside* that
daily touch, and that is where the entry goes.

### Which explains the stop-loss ladder, stated explicitly

From the Kalyan study, the same trade at three setup timeframes:

| STF | setups offered | stop loss |
|---|---|---|
| Monthly | 1 | **10%** |
| Weekly | 1 | **6%** |
| Daily | 3 | **3%** |

> "I personally don't keep Monthly as STFs but I am always aware of it. **Majority of
> the times I use Daily as my STF for better churning of Capital.**"

**The tight stop does not come from picking different stocks. It comes from
executing the same setup on a lower timeframe.**

This directly explains run 2's finding that tighter stops predicted *worse* trades.
We measured stop width across daily-bar pivots on daily scanner signals — his 6–10%
case. His 3% case requires hourly and 15-minute bars to locate the pivot.

### And it is currently out of reach

Our candle store is daily only: `candles(symbol, dt, open, high, low, close,
volume)` with no interval column and one row per symbol per day. There is no
hourly or 15-minute data, and the daily job does not fetch any.

**So the part of the methodology most worth having — the 3% stop — cannot be built
or tested on our current data.** That is a data gap, not a modelling choice, and it
should be stated plainly rather than approximated with a daily pivot and called his
stop.

---

## 3. Setup templates — M10, V12, V25

The lectures used these as bare labels ("I'm not going to take M10 in this one",
"a beautiful V12 basically, template V12", "this becomes a v25 here on the daily").
The PDFs give enough context to read them:

- **M10** — a *Move to the 10 EMA*. "We got a proper M10. Daily comes to 10 EMA."
  Failure case: "D did not give M10. Why? **Structure broke** by the time D came to
  10 EMA."
- **V12** — the *Value zone between the 10 and 20 EMA*. "we finally pushed through
  the **10/20 Zone** by a Blue CB candle"; "V12 happened within the highs of the
  expansion"; "V12 also helped in creating a range, resetting the structure, leading
  to HH HL."
- **V25** — by the same construction, the value zone between the 20 and 50 EMA.

The V12/V25 reading is **DERIVED and not certain** — the PDFs never expand the
abbreviations. But it is consistent with every usage and with his "value zone"
language, and both are directly computable if correct.

---

## 4. Other rules the PDFs state more sharply than the lectures

**Entry trigger, weekly, stated as a sequence:**
> "candles were closing near to 10 EMA but failing to close above 10 and 20 EMA,
> then finally we had a **big candle on high volumes closing above both 10 and 20
> EMA and also led to 10 crossing above 20 EMA**, after which we had an **Inside Bar
> closing above 10 and 20 EMA — that was the buy point**."

The inside bar after the cross is the trigger, not the crossing candle itself.

**Big red candles are not automatically bad:**
> "are big red candles with high volumes bad? **NO.** It depends on a lot of factors"
> — specifically Location, and whether the red candle was itself a DC caused by a push.

**The counter rule, restated with the failure case:**
> "see how Hourly had **big red candles not countered by CB candles**, all the green
> candles were small compared to the big red candles in the fall, **it also broke the
> HL** on Hourly... all this coupled with relativity would not allow you go long."

**Top-down is mandatory:**
> "Once I have selected my STF and hypothesis of the trade, **then only** I will use
> ETF to plan my entries. This is Important, **always top down and never bottom up**."

**The 10/20 intermingling tell, as a starting read rather than a rejection:**
> "the **10, 20 and 50 EMA are intermingled very close to each other, with 200 EMA
> nearby**. This tells us that this contraction is a bit bigger and could be happening
> on a bigger timeframe (Monthly, and not just Weekly)."

Worth noting against rule E-07: in the lectures the 10/20 intermingling is a reason
to reject an entry; here the same observation is a *diagnostic* that sends him to a
higher timeframe. Same fact, two uses, depending on whether he is timing an entry or
establishing context.

**And the same refusal as the lectures, in writing:**
> "It's not about a pattern or a formula, it's about your perception and mindset."

---

## 5. What changes in the model

| Item | Before | Now |
|---|---|---|
| CB definition | resolved by user, unverified | **Confirmed** — "Committed Buyers", glossary, both PDFs |
| CB and volume | assumed independent | **Measured** — pure return works, adding volume breaks it |
| CB scoring | more is better | **Band 50–75%**; above 75% is negative |
| Tight-stop mechanism | assumed to come from stock selection | **Comes from timeframe** — 10% / 6% / 3% by STF |
| The 3% stop | assumed reachable | **Not reachable** — we hold daily bars only |
| M10 / V12 / V25 | unknown labels | M10 explicit; V12/V25 derived |
| Entry trigger | 10>20 cross holding | **Inside bar after the cross** |

**The single most consequential line of this addendum:** our data cannot express the
part of his method that produces the 3% stop. Anything we build on daily bars is his
weekly-STF case at best, and should be measured against that expectation rather than
against the case studies' headline numbers.
