# RISK_ENGINE

Risk is the part of the methodology the author is most insistent and most specific
about. His central claim is that **the edge lives in the entry price**, because entry
price determines stop width, which determines position size, which determines whether
the trade is worth the slot.

```
pivot quality -> definable stop -> stop width -> position size -> outcome
```

Every link is EXPLICIT somewhere in the corpus.

---

## 1. Where the stop goes

**EXPLICIT — below a structural pivot, and nowhere else.**

> "you say 'Sir, 10 EMA will be my SL.' But my question is **why? Was there any evidence?
> Was there any sign that 10 EMA is going to hold up, or is it arbitrary? Certainly
> arbitrary.** So that doesn't make sense. **That's not a logical way to trade.**" —
> lecture 11

**EXPLICIT — never inside a demand zone** (lecture 5):

> "if you have stop losses anywhere in between the area, **what exactly are you doing
> having stop loss in demand area?** You are just **fuelling — you are just giving
> liquidity.** And that is the problem."

**EXPLICIT — the stop must sit below a *demand* level, not below an arbitrary candle
low** (lecture 4):

> "if you are trading this inside candle, **why would you have the inside bar's candle
> low as your level? What is the reason?**... a lot of people won't even have a logical
> explanation. All they'll say is 'I trade on small level or tight level'... **you need to
> have your level below some certain demand area**"

---

## 2. Stop width must be proportionate to DNA

This is the author's single most quantitative risk statement, from lecture 4:

> "if I'm buying here my SL will be around **17%**, and do note the analysis we did on
> the monthly — the move you're getting is between **25 to 40% in a single month**. For
> that, taking the SL of 17%, **that's not the best thing.** I mean, you can take a 17%
> level if you're aiming for 500% move, even 100% move, **but certainly not when you're
> looking at 30% or 35%.** You know, that's 2-to-1. Not bad, but **not ideal.**"

So: a stop is acceptable only if it produces a reasonable ratio against the **DNA-derived
expected move**, not against an arbitrary target.

### The timeframe-switching ladder

Lecture 4 demonstrates progressively tightening the same trade by moving down
timeframes to find a nearer structural pivot:

| Approach | Stop | Verdict |
|---|---|---|
| Weekly STF, buy at the weekly signal | 17–20% | Rejected |
| Daily, buy at the 50 EMA | 10% | Better |
| Daily, buy below the DC under the 50 | 6–8% | Good |
| Hourly, using the hourly 200 MA structure | 4.6% | Best |

Lecture 12 shows the same compression on another trade — an end-of-day entry implying a
7% stop, versus waiting one day for a pivot to form:

> "if you're taking entry on end of the day, your SL has to be below 10 EMA, which is
> already **7%**... But see what happens next day. You're literally at 10 EMA closing
> there... **Created a pivot.** So now **your SL is not 7% anymore. Your SL is 2%
> suddenly. Now, that is what you want.**"

**7% → 2% by waiting one bar.** That is the mechanism the author is teaching, and it is
the clearest illustration of why he refuses to chase.

---

## 3. Structural vs expectational stops

**EXPLICIT — the expectational stop is a legitimate but restricted tool** (lecture 12):

> "you say 'Sir, the way everything is set up, **I expect the stock not to come in this
> zone and just take off from here**.' Now, that is your expectation. So that becomes your
> stop loss. **Take the SL which allows you to take the position size whatever you want.**
> If your 2% stop loss is allowing you to get the size that you want, then your SL becomes
> 2%... because **anyway the stop loss is not based on some structure**. It's on
> expectation that the price should move up from here if the momentum is there. **If the
> price starts coming down, you just get out.**"

> "And **yes, it can whipsaw you maybe a couple of times.** But the point is **the
> risk-reward of this style takes care of that.**"

**EXPLICIT — prefer structural when the cost is small** (lecture 12):

> "if you enter here, the pivot SL is **3%**. So now you can see if you're going for
> expectational SL of 2%, **I think it is much better to go for a structural 3% SL** and
> just take up a bit more risk on your portfolio, **because the difference is honestly not
> a lot.**"

**EXPLICIT — re-enter after an expectational stop-out** (lecture 12):

> "whether it looks like this, dips a little bit below, takes your SL, goes up and does it
> again — well, **then you enter it again. Because if you don't, then you will not make
> that system work for you.**"

### Decision rule

```
if quality_pivot_exists_on_ILHS:
    stop = below_pivot
    if stop_width_pct > DNA_expected_move * MAX_RISK_RATIO:   # MAX_RISK_RATIO OURS
        drop to lower timeframe and look for a nearer pivot
        if still too wide: SKIP
else:
    if thesis is pure momentum and setup quality is high:
        stop = expectational, 1.5-2%, sized to target position
        plan to re-enter on whipsaw
    else:
        SKIP                                                   # P-06
```

---

## 4. The 1% stop is rejected

**EXPLICIT, with two distinct reasons** (lecture 12):

> "I honestly don't like people who take 1% SL... **1% for a stock on the daily timeframe
> which has been going up 12%, 5%, 8% like anything is honestly not much.** And the second
> is **1% at times is gone in slippages.** If you're handling a good position size, 1% at
> times goes in buying and selling, combined slippage."

> "you will take 1% SL right on the paper... but when you actually go to the trade book
> and P&L, **you will see the loss that is reflected is much higher than what was given by
> the Excel sheet.** Now, that kind of **ruins a lot of systems which operate on this
> calculation of risk and reward.**"

**Implication for our backtest:** this is a direct instruction to model slippage and
charges. A backtest that ignores them will validate exactly the strategies the author
says fail in practice. See `BACKTEST_SPEC.md` §4.

---

## 5. Position sizing

**EXPLICIT — starting size** (lecture 14):

> "my position sizing **do not start with 15% 20%. They usually are in the higher end of
> 35 40%.** That's where I like to start."

**EXPLICIT — best setups go much larger** (lecture 4):

> "your SL will be small, your position size will be good number — **not 25%, not 30% of
> the capital, 60 70 80% of the capital. That's where the money is made.**"

**EXPLICIT — 50%+ for the best charts** (lecture 10):

> "these are the trades you should take with the position size of **at least at least
> 50%**. That's how you will make good money."

**EXPLICIT — the anti-pattern** (lecture 10):

> "let me **dip my toes in the water**, have my **pilot position** or **test position**,
> or you have position size of 25 or 30% or 15% only. Imagine making 30%, 20% on that.
> **What difference does it make? Not much honestly.**"

**EXPLICIT — size down for higher-timeframe trades** (lecture 8):

> "I also did not size it as much as I do as my daily trades **because it's a huge
> cycle. I cannot take minus 6% on a huge size of my account** like I'm able to do it on
> a daily. It's difficult. **It has a lot of potential to ruin a lot of things for me.**"

This is not inconsistent with the above. A monthly-scale trade has a wider stop and a
longer hold, so the same risk budget buys a smaller position.

### Reconciliation

The author sizes by **risk**, not by notional. A 40% notional position with a 4% stop
risks 1.6% of capital; a 60–80% position with a 2% stop risks 1.2–1.6%. The notional
figures he quotes are all consistent with a roughly **1.5–2% risk budget per trade**,
which is the number an implementation should actually use.

**This reconciliation is DERIVED, not stated.** The author never names a risk
percentage. It is the arithmetic that makes his quoted notionals and stops mutually
consistent, and it should be treated as a hypothesis to validate, not a quotation.

---

## 6. Drawdown expectations

**EXPLICIT — large intra-trade drawdowns are normal at higher-timeframe scale**
(lecture 8):

> "a position that once was up almost 18% is now back to zero. Nothing."

> "this is how it works especially the bigger scales: **-6% is normal, +18% is normal,
> then from 18 to 0 is also normal**... when you are buying at that point of time **you
> need to be mentally clear what things can go against you and yet be very normal.**"

This is a statement about what the equity curve of this methodology looks like, and the
backtest should be expected to reproduce it: **wide intra-trade excursions, not a
smooth curve.** A backtest producing a suspiciously smooth curve is probably wrong.

---

## 7. Charges and taxation (lecture 13) — directly affects backtest validity

The author devotes the second half of lecture 13 to Indian trading costs, and the
argument is structural rather than incidental:

- STCG is computed on gross profits minus gross losses minus deductible charges.
- **STT is non-deductible.**
- Therefore a book that looks profitable pre-tax can be a net loss after STT.

His worked example: ₹10L gross profit − ₹5L gross loss − ₹1L charges = ₹4L net gain,
₹80k tax, then ₹6L STT subtracted → **−₹2.8L net.**

> "it is entirely possible the STT will accumulate in such a huge amount that by end of
> the year, **even though you were profitable from your perspective of risk-reward
> calculations and win rate, the way the charges structure is, you will end up in
> losses.**"

And the conclusion, which is really a statement about strategy design:

> "**win rate is also important**, because win rate is nothing but **the quality of your
> decision-making**... If your win rate is less, it tells me maybe your entries are just
> not good."

### Mandatory backtest implications

1. Model brokerage, STT, stamp duty, exchange charges and GST explicitly.
2. Report results **net** as the headline, gross only as a diagnostic.
3. Report **win rate** alongside expectancy — do not defend a low win rate with
   risk-reward.
4. Report **turnover** (trades per year). A strategy that needs 300 trades/year to
   produce its edge is, by the author's own argument, suspect.

---

## 8. Parameters

```python
# From the author's worked examples (calibrated, not quoted as rules)
BREAKEVEN_TRIGGER_PCT   = 7.0     # Lec 14
TRANCHE_TRIGGER_PCT     = 20.0    # Lec 14
TRANCHE_FRACTION        = 0.75    # Lec 11 (0.76), Lec 13 (0.80), Lec 14 (0.74)
MIN_STOP_PCT            = 1.5     # Lec 12: 1% explicitly rejected
EXPECTATIONAL_STOP_PCT  = 2.0     # Lec 12
STRUCTURAL_PREFERENCE   = 1.5     # Lec 12: prefer structural if within ~1.5x

# DERIVED, must be validated
RISK_BUDGET_PCT         = 1.75    # reconciles quoted notionals and stops
MAX_RISK_RATIO          = None    # stop / DNA expected move; no transcript value
```
