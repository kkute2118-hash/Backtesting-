# EXIT_ENGINE

The author's exit logic is more consistent across lectures than his entry logic, and
most of it is computable.

---

## 1. The governing principle

> "**Let stocks tell you sell or buy.** Do not just try to say 'I think it will move up,
> I think it will go down.' Don't do that. Let the stocks give you the direction." —
> lecture 8

Exits are triggered by observable events, never by prediction or by reaching a target
price in the abstract.

---

## 2. The default state: do nothing

> "I simply use **10 EMA as my first area of trailing**. So I like to just **be ignorant
> of the stock as long as it is above my 10 EMA.** The day it comes to the 10 EMA is the
> day I'll come to my screen and see what has happened exactly here. As simple as that."
> — lecture 14

This is the base case (O-01). A touch of the 10 EMA is a **prompt to look**, not an
exit.

Corroborated as an observation in lecture 7:

> "in majority of the move the price **barely touched 10 EMA**, and when it did close
> below 10 EMA, **it went into a longer contraction**"

---

## 3. Exit triggers, in order of severity

### T1 — Decisive close below the 10 EMA → full exit

> "finally we have **closed very well below 10 EMA and that is where my exit was. So,
> completely exited.**" — lecture 11

> "the **first time you opened above 10 EMA and you closed below it**, so that becomes
> **an easy trigger**." — lecture 11

Note the qualifier "very well below" — a marginal close is not the trigger. This needs
a buffer parameter (OURS).

### T2 — The engulfing down candle → full exit

The most specific exit signal in the corpus, from lecture 8:

> "since the start of this move, **this is the first candle which completely eats the
> entire expansion candle**, and in fact **it is much bigger than the recent expansion
> candles**... and it's a minus 8.8%. So **even in percentage terms it is the biggest
> candle you are having in any expansion on the downside.**"

> "**You will never see the good stocks do this. Never.** The ones which are going up. And
> since it was 102%, I'm pretty happy with what I've made. So **I simply exited at the
> break of this.**"

Three conditions, all computable:
1. A down candle that fully engulfs the prior expansion candle.
2. Larger in absolute size than recent expansion candles.
3. The largest down candle (by %) since the move began.

Exit is taken **on the break of that candle's low**, not at its close.

The same rule reappears in lecture 14 as a *warning* rather than an exit, when it
occurs at the **start** of a contraction:

> "this candle is what almost a **minus 6.5% candle with good body size, and much bigger
> than most of the candles in expansion**. So that is **never a good thing to have**...
> It simply implies that my contraction can face some volatility."

Same signal, different meaning by location: **inside an expansion it is an exit; at the
start of a contraction it is a caution flag that sets expectations.**

### T3 — Lower circuits → full exit

> "this stock was put into the lower circuits... **I don't like lower circuits.** It's
> entirely possible we just keep falling down through circuits and that can put you in a
> bad bad place. And **that's exactly where I decided to close the entire position.**" —
> lecture 14

India-specific. Computable if circuit data is available; a proxy is a limit-locked bar
(open = high = low = close at a limit band).

### T4 — Pivot break, once extended → full or partial exit

Once the position is well in profit, the trailing reference shifts from the EMA to the
most recent pivot:

> "**why are you not giving it space between 10 and 20? Because the position is already
> 100% up.**... as the move goes up, continues going higher and higher, **you start
> reducing that space**. Otherwise you'll lose out on a lot of money that you have made.
> That 100% will suddenly look like 40 or 50%." — lecture 9

> "now I'm watching carefully since we have had a great up move. We are already up by 88%
> and we have kind of formed a pivot over here. **So that can be utilised.**" — lecture 14

### T5 — Higher-timeframe DNA exhausted → begin selling

> "really think what was the DNA work that was done on weekly. How much percent was it
> coming around? 40 50 60%. **That's exactly where the region it went up.** So you can
> **actively start selling because you know weekly DNA is going to get over** and there
> is no reason for weekly DNA to extend." — lecture 6

### T6 — Declining volume on a rising leg → caution

> "usually the way it is going higher, **the volumes are decreasing. Not a very good
> look.** So now again we are cautious." — lecture 14

A caution state, not an exit.

---

## 4. Partial exits — the tranche model

This is central to how the author actually trades, and it is consistent across
lectures.

| Trigger | Action | Source |
|---|---|---|
| Up ~7% | Move stop to near breakeven | Lec 14 |
| Up ~20%, or into the first strong expansion | Sell **74–80%** of the position | Lec 14 (74%), Lec 11 (76%), Lec 13 (80%) |
| Remainder | Trail on the 10 EMA, targeting higher-timeframe DNA | Lec 11, Lec 14 |
| At resistance | Sell 50% **only on an ETF pivot break**, not pre-emptively | Lec 6 |

The reasoning for the large early tranche is explicitly about **opportunity cost**, not
fear:

> "I'm already up 20% or so... I'm still open to the possibilities... **but I'm not open
> with the entire size.** I'm more than happy to book a good chunk of my profits and
> **utilise them somewhere else.**" — lecture 14

> "the profits we have booked, **the capital that we freed up, was used in even better
> trades** which moved pretty well in a short period of time. So **we are not missing out
> on anything.**" — lecture 14

And in lecture 11: "I sold 76% over here. **Let's go to the better opportunities.**"

**Implication for backtesting:** a single-position backtest will systematically
understate this methodology, because a large part of its return comes from capital
recycling. The backtest must be **portfolio-level** with a realistic slot count. See
`BACKTEST_SPEC.md`.

### The resistance rule

> "since we are at a resistance doesn't mean I'll blindly sell 50%. What I'll do is I'll
> actually **pick a pivot point, a structural point from ETF** — 15 or 5 minutes — where
> it is clearly visible and I'll use that. **If this gets taken out, I'll be selling 50%.
> If this doesn't get taken out, why do I even have to sell 50%?**" — lecture 6

Lecture 10 is blunter about selling early at resistance:

> "he took the entry here and he sold on this day. I don't know why... **he sold for 5%
> and missed out on almost 15%.** And the reason for selling here is there is a
> resistance... **at least wait for structural breaks to happen.** Why do you have to
> think 'there is a resistance now, a push can come, so I should sell'? Instead: **there
> is a resistance and there can be a push, so I should be ready for that.**"

---

## 5. Stop management during the trade

**EXPLICIT — move to breakeven once meaningfully in profit** (lecture 14):

> "you don't want a stock which was up 7% to result in a loss. Then the best thing you can
> do is **bring your stop loss from whatever it was to very close to your buying price**...
> but **don't further do anything stupid. Otherwise you'll end up missing the major part
> of the move.**"

**EXPLICIT — do not ratchet on every green day** (lecture 13):

> "when you have such kind of moves, **it doesn't mean you will move your trailing SL here
> and here and here. No. Simply got it to my cost.**"

The stop moves **once**, to breakeven, and then stays until a structural reason to move
it appears.

---

## 6. Computable form

```python
# ---- Default ---------------------------------------------------------------
if close > ema10:
    hold()                                         # O-01

# ---- Full exits ------------------------------------------------------------
T1 = close < ema10 * (1 - CLOSE_BELOW_BUFFER)      # OURS
T2 = (down_candle_engulfs_prior_expansion_candle
      and abs(pct_change) > max(recent_expansion_pct)
      and abs(pct_change) == max_down_pct_since_move_start)
      # exit on break of that candle's low
T3 = lower_circuit_bar()
T4 = extended and close < last_pivot_low

# ---- Partial exits ---------------------------------------------------------
if unrealised_pct >= BREAKEVEN_TRIGGER:   # ~7%,  OURS-calibrated from Lec 14
    stop = entry_price
if unrealised_pct >= TRANCHE_TRIGGER:     # ~20%, OURS-calibrated from Lec 14
    sell(TRANCHE_FRACTION)                # 0.74-0.80
    remainder_trails_on = ema10

# ---- Caution ---------------------------------------------------------------
T6 = rising_leg and volume_trend_negative          # reduce, do not exit
```

Constants in CAPITALS are calibrated from the author's worked examples but are not
stated as rules. They are parameters.

---

## 7. What the exit engine deliberately does **not** include

- **No fixed R multiple.** Targets come from DNA (O-07), not from a risk multiple.
- **No time stop.** Nothing in the corpus supports one.
- **No trailing on the 20 or 50 EMA.** The 10 EMA is the stated trailing reference
  throughout; the 20 and 50 appear as *entry* references only.
- **No exit on market conditions.** "Markets are always neutral" (G-03).
