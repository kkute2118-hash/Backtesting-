# ENTRY_ENGINE

The author's entry sequence, reconstructed from the two lectures that walk a real
trade forward bar by bar: **lecture 11** (his own numbered points 1–6) and
**lecture 14** (his own numbered entry points 1–3).

---

## 1. The canonical sequence (lecture 11)

The author numbers these himself on the chart. They are the clearest statement of the
entry process in the corpus.

### Point 1 — First close below the 10 EMA

> "we had a good big body candle, you know, close below 10 EMA after a good up move by
> the stock. **This is the first time you have closed below 10 EMA now since you
> started going up from here.** So, we take a note of that."

This *starts* the contraction. It is not an entry. Computable: first `close < EMA10`
after a run of `close > EMA10`.

### Point 2 — Wait for a counter candle, but check relativity

> "now we need a **good counter candle** to this one. And we also need to keep
> relativity in mind... Otherwise, how will you know that there is evidence of demand?"

And immediately, the rejection:

> "In the next 2 days, we do get a really solid counter candle... But, where is it
> happening in time? Is it enough? **Think about relativity. You really think it is
> enough?** ... Expecting a contraction literally just [one bar] is a bit too much. So,
> the probabilities are still not aligned."

**A counter candle alone is not enough.** The contraction must also have had
proportionate *time*. This is the trap the author explicitly points out.

### Point 3 — The move down to the 50 EMA (usually NOT an entry)

> "we go to 50 EMA. Now, always see the quality. What was the quality of going to 10
> EMA or 50 EMA? Were there big red candles, or were there candles with small lower
> wicks?"

> "we are also away from 50 EMA of the daily. So, till this area, **you just don't know
> how the price is going to react**... So, how will you define your SL? **You cannot.**
> And that is why, yes, you might be getting cheaper value... but with that is coming a
> lot of uncertainty. **This opportunity to add the stock is just not that great.**"

The rule: cheap price with an undefinable stop is not an opportunity. This is P-06.

### Point 4 — The DC up move creates the pivot

> "we had a good up move candle... we get a **good DC up move**. The quality is nice
> and takes just above 10 EMA, which is obviously a good thing. **If it took you a lot
> away from 10 EMA, that would have been bad.** But when we started around 50 EMA and
> just closed over there — so now **this entire up move is now a demand zone**."

Note the lecture-5 framework applied: started near the 50, closed just above the 10 —
close enough to the MA to keep the stop tight. The **low of this up move becomes the
pivot**.

### Point 5 — The best add: down move into the DC pivot at the 50 EMA

> "this down move — is it similar to this one? No. Why? Because at this point you just
> had the uncertainty. There is no demand zone on your left hand side. **But now you
> have a very very valid pivot point here**... So **I can have my SL. It's not an
> uncertain SL. It's not an illogical SL. There is logic to it.**"

> "**And this day actually was the best day to add.**... whatever you want to add, this
> is the place. Point number five. **Confluence of daily 50 EMA plus DC up move pivot
> point.**"

**This is the highest-quality entry in the entire corpus.** The two identical-looking
down moves (point 3 and point 5) differ only in whether a quality pivot exists on the
ILHS. That single difference is what makes one untradeable and the other the best day
of the setup.

### Point 6 — The trigger: 10 EMA crosses above 20 EMA and holds

> "it's a plus 3.92% day. If you see, there is a small black dot over here. Now see,
> the small black dot appeared on this day, too, right? **But after that, what
> happened? We again came back down, which is 10 going below 20.**"

> "We had a **4% day which got my 10 above 20**. After that, price did attempt to go
> downhill. But **was it able to make my 10 go below 20? No.** Rather, the very next day
> we had a good day **closing above 10 EMA**... **It never happened previously. It never
> happened before that.**"

This is the completed trigger, and all three parts are required:

1. A strong up day (~4%) takes **EMA10 above EMA20**.
2. Price dips but the **10-over-20 configuration holds**.
3. A subsequent day **closes above the 10 EMA**.

Plus the historical condition: **this has not happened before in the current
contraction**. A prior cross that reverted (the earlier black dot) does not count —
this is rule E-06, and it is the same lesson as lecture 7's area 1 vs area 2.

---

## 2. The three entry types (lecture 14)

Lecture 14 presents the same structure from a different angle: three distinct entries
in one setup, trading certainty against price.

### Entry 1 — Value buy in the demand zone

Price enters a demand zone defined by **a confluence of a prior demand candle and the
50 EMA** (or the 20–50 EMA band).

> "this line is not the demand zone. But **this line along with the 50 EMA of the daily
> is the zone of demand**... This becomes a demand zone."

> "It's a value buy, a really great value buy. The stop-loss, although in this case
> will be **expectational**... If you are getting a good amount of fair value, you will
> have to bear some amount of uncertainty."

Best price, weakest stop. Requires the demand zone itself to be high quality.

### Entry 2 — Second visit to the same demand zone

Same zone, now with a better ILHS because the first visit produced a pivot. The author
notes the second visit came via a −7.52% candle similar in size to the one that started
the contraction — but in a **different context**, which is what made it acceptable:

> "we again come to demand zone through a minus 7.5% candle **but within a different
> context**... if you can counter this that'll be absolutely brilliant, and that is why
> this also becomes even a good buying opportunity"

### Entry 3 — Certainty buy on the 10>20 cross

> "a candle has come 9% up and **this candle has the capacity to make the 10 EMA cross
> above my 20 EMA. So that is extremely powerful.** Then you have another candle which
> **closes extremely close to my 10 EMA**. So brilliant."

> "the great deal about this is **there is more certainty but a bit more price you have
> to pay.** That's like the price you have to pay for having more certainty... when you
> were buying here the price was around 192–194. Now that you're buying, it's 214–215."

**The author considers the extra ~11% entirely worth paying.** This matters for
implementation: an engine that always optimises for the cheapest entry is not following
this methodology.

Note the confirmation candle "closes extremely close to my 10 EMA" — lecture 5 case 2
again. The best entries recur.

---

## 3. Preconditions (must all hold before any of the above applies)

| # | Precondition | Rule |
|---|---|---|
| 1 | 20-day average turnover above the floor | L-01, L-06 |
| 2 | An event on the LHS that survived its contraction | E-02, E-06 |
| 3 | EMA10 clearly separated from EMA20 — not intermingled | E-07 |
| 4 | Contraction contained within the expansion-ending candle's high | K-01 |
| 5 | Contraction proportionate in time and depth to the expansion | K-05, K-06 |
| 6 | Volume cluster in the expansion, not a single tower | V-01, V-02 |
| 7 | A quality pivot on the ILHS → a definable stop | P-06 |
| 8 | No earnings imminent, unless already deep in profit | Lec 12 |

---

## 4. Explicit non-entries

- **Momentum days.** Prices move in the first 15–30 minutes and liquidity is poor
  (RG-04 notes a transcription contradiction here; every other lecture supports
  rejection).
- **Above the high of the bar**, as a rule in itself. "dumb people buy above the high
  of the bar" (lecture 7).
- **Into earnings** when not already up substantially (lecture 12).
- **Cheap price with no pivot.** The recurring rejection across lectures 10, 11, 12.
- **When it is not at your price.** "if you repeat this process for the next 100 trades,
  the expected value of it is going to come negative" (lecture 12).
- **When a better candidate exists.** Opportunity cost is a stated rejection reason
  throughout lecture 10.

---

## 5. Reduction to computable form

```python
# ---- Hard gates (EXPLICIT, computable) -------------------------------------
gate_liquidity   = avg_turnover_20d >= TURNOVER_FLOOR_CR          # OURS
gate_event       = event_on_lhs(lookback=EVENT_LOOKBACK) and event_survived()
gate_separation  = abs(ema10 - ema20) / close >= MIN_EMA_SEP      # OURS
gate_containment = contraction_high <= expansion_end_candle_high  # K-01
gate_upper_half  = contraction_low >= expansion_end_candle_mid    # K-02

# ---- Trigger (EXPLICIT, computable) ----------------------------------------
cross_day        = (ema10 > ema20) and (ema10.shift(1) <= ema20.shift(1))
held             = (ema10 > ema20).rolling(HOLD_BARS).min() == 1  # HOLD_BARS OURS
confirm          = close > ema10
first_occurrence = no prior surviving cross within this contraction  # E-06

trigger = cross_day_recent and held and confirm and first_occurrence

# ---- Pivot & stop (EXPLICIT, computable) -----------------------------------
pivot   = low of the demand candle / DC up move
stop    = pivot * (1 - STOP_BUFFER)                                # OURS
risk_pct = (entry - stop) / entry

# ---- Quality approximations (OURS — must be validated) ---------------------
candle_quality   = body / (high - low)            # RG-03
counter_ratio    = up_candle_body / prior_red_candle_body   # >= 0.5 per P-04
cluster_score    = see VOLUME_LIQUIDITY_SPEC.md §4
```

Every constant in CAPITALS has **no transcript value**. It is a fitted parameter and
must be reported as fitted, per Section 37 of the master prompt ("no data = no claim").

---

## 6. Relationship to our five scanners

Under the ABSOLUTE RULE, **nothing here changes what S1–S5 select or score.** This
engine runs strictly *after* a scanner has produced a candidate, as a second-stage
filter and ranker.

Two of our existing scanners already overlap with the author's logic, which is worth
noting for the ablation tests:

- **S3 (EMA50 pullback)** resembles the point-3 to point-5 sequence.
- **S5 (pocket pivot)** resembles the volume-cluster and turnover-spike logic.

The ablation must therefore check whether this layer adds anything *beyond* S3 and S5,
not merely whether it beats the pooled baseline. See `BACKTEST_SPEC.md` §5.
