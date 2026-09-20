# TRADER_METHODOLOGY

The complete methodology reconstructed from 14 lecture transcripts (93,862 words).
This document describes *how the author thinks*. `TRADER_RULEBOOK.md` reduces it to
testable rules.

Evidence classes: **EXPLICIT** / **DERIVED** / **UNKNOWN** / **CONFLICTING**.
Line numbers refer to `bulk_transcripts_14_1.txt`.

---

## 0. What this methodology is, and what it is not

It is **not** a scanner. The author says so directly and repeatedly: a stock
appearing on a scan is the *beginning* of the analysis, never the conclusion.

> "let's say you come back home, **you run your scan and this is the day you see the
> stock come in your scan**. Okay? And you're like, 'Oh, feels like you have missed
> the entry.'" — lecture 12

The scan produces candidates. Everything in this document is the second stage: what
the author does to a candidate to decide whether it is tradeable, at what price, at
what size, and with what stop.

This maps exactly onto the master prompt's framing: **our five scanners produce the
100; this methodology reduces the 100.**

The author's own scan, incidentally, is weekly and produces a manageable list:

> "we didn't have a lot of stocks honestly like we had what hardly 30 stocks coming in
> around um that week. We had on that week **57 stocks**" — lecture 14

So he is already operating at roughly the candidate-count our scanners produce.

---

## 1. The three-timeframe architecture (TTF / STF / ETF)

This is the organising structure of the entire methodology. Lecture 6 is devoted to
it.

| Frame | Name | Role | Typical period when trading daily |
|---|---|---|---|
| **TTF** | Trend Time Frame | Location, context, stage, DNA, extension | Monthly + Weekly |
| **STF** | Setup Time Frame | The setup itself: expansion, contraction, entry decision | Daily |
| **ETF** | Entry / Execution Time Frame | Pivots, precise entry, stop placement, trade management | Hourly, dropping to 15m / 5m / 1m |

**EXPLICIT — what each frame is for** (lecture 6):

> "the TTF is basically to make you aware of the factors of **location and the
> context** of how it is happening and where it is happening."

> "over here on ETF, you're **not expected to see the DNA, the relativity** because
> you've already taken care of that from a higher time frame perspective... **ETF is
> here to give you pivot points, structural points and manage things.**"

**EXPLICIT — the ordering constraint** (lecture 1):

> "you always should be convinced that the **STF is good and now ready for an up
> move**, then only you should move to any other time frame"

You do not go looking at the hourly to rescue a daily setup you do not like. The STF
decision comes first; the ETF only refines execution.

**EXPLICIT — frames are promotable.** A daily setup can turn out to be a weekly
setup, which changes the profit target and the position management, not the entry:

> "I did not scan weekly. I did not scan monthly. I was simply scanning on daily,
> going through my list. Just by doing that, **I'm actually landed up on a weekly STF
> trade**... which means I can have my profit expectations, the percentage gain, from
> this perspective. I will not be limited with the daily." — lecture 11

And demotable mid-trade: in lecture 11 he sells 76% of a daily-STF position and
explicitly "converted now this daily STF trade... into a weekly" for the remainder.

**EXPLICIT — the ETF moving-average check is deliberately minimal** (lecture 1):

> "when you're talking about the ETFs **don't worry too much about the 10 moving
> average**, so all I [care] here really is about **20 being above 50**"

---

## 2. DNA — the stock's characteristic move size

"DNA" is the author's term for how a particular stock moves, measured on the
timeframe being traded. It is the **first** thing he assesses on every chart, before
trend, before stages, before anything else.

### Two components

**(a) Magnitude** — the typical single-candle percentage move, and the typical
full up-move, on that timeframe.

Worked values across the corpus:

| Timeframe | Single candle | Full up move | Source |
|---|---|---|---|
| Monthly | 25–40%, sometimes 50–70% | 70–140% | lectures 4, 6, 7, 8, 11 |
| Weekly | 15–30% | 40–60% | lectures 4, 6, 11 |
| Daily | 8–20% | 35–60% | lectures 4, 6, 9, 11, 14 |

These are per-stock, not universal. The point is to establish *this* stock's
numbers.

**(b) Quality** — the shape of the candles while the stock is moving up.

> "just have a look how these dark blue candles are there... the open and the lows,
> the highs and the close, pretty good whenever it is moving up" — lecture 3

> "almost full body, little bit element of the [wick] each side, but that's okay" —
> lecture 11

**EXPLICIT — only measure DNA on real up moves, never in a range** (lecture 6):

> "do not see the DNA for this because this has not happened for you... they are not
> going to offer any real value **since they are in a range**. We'll be like, where
> was the last time it was going up really well"

**EXPLICIT — how to compute a move correctly** (lecture 11). He rejects
high-minus-low and insists on summing the up candles:

> "a lot of people ask that sir, when I calculate the expansions, shall I do like
> this? I'll actually tell you a better way because this is not very realistic...
> **simply add on the positive candles**... So, it's not 175. **100% up move** we had"

This matters for implementation: the author's "up move %" is the sum of positive
daily returns across the leg, not the peak-to-trough range.

### What DNA is used for

1. **Sizing the profit target.** "I'm not trading for 5% or 8% or 10%. I'm going for
   beyond that... 20%, 30%, whatever comes through clean" (lecture 14).
2. **Sanity-checking the stop.** A 17–20% stop is absurd on a stock whose monthly DNA
   is 25–30% (lecture 4) — see `RISK_ENGINE.md`.
3. **Knowing when the move is done.** "you can actively start selling because you know
   **weekly DNA is going to get over** and there is no reason for weekly DNA to
   extend" (lecture 6).

---

## 3. Expansion and contraction

The author's entire market model is a two-phase cycle. Money is made by entering in
**contraction** and being paid in **expansion**.

> "as a trader where will you buy? Contractions. **We do not buy in the momentums**"
> — lecture 6

### Expansion quality

**EXPLICIT criteria:**

- Full-body candles, open near low, minimal wick (lectures 3, 6, 11).
- Volume clusters throughout, not a single tower (lecture 1, lecture 10 — see
  `VOLUME_LIQUIDITY_SPEC.md`).
- Consistency with the stock's DNA.
- **Where the expansion ends matters.** He marks "the last good candle" and "the
  candle with which the expansion ended", because the contraction is then measured
  against that candle's high.

**EXPLICIT — the weak expansion** (lecture 1, lecture 4). An expansion that "creeps"
upward rather than moving decisively is a disqualifier, for a specific mechanical
reason: by the time price reaches the 10 EMA, the EMA's slope has flattened, so it
provides no support.

> "eventually turned into a weak expansion... look how the expansion ended over here,
> that's not the way I would like"

**EXPLICIT — the weak high** (lecture 10):

> "when the prices just keep going up like this, it creates a **weaker high**, which
> is not great for momentum... You want price comes here and just stops and comes back
> in and then goes through it with great candles."

> "**Momentum creates stronger highs and highs, not weaker highs.**"

### Contraction quality

This is where the author spends most of his analytical effort, because this is where
entries live.

**EXPLICIT — the single most important structural test** (lecture 4):

> "this entire contraction you see happening was **within where the contraction
> started** — really important — and everything was **in the upper half** of the
> contraction... **this is one of the most important points that I'll ever give you in
> your trading**"

Restated: everything in the contraction should stay **inside the high of the candle
on which the expansion ended**, and ideally in the **upper half** of that range.

**EXPLICIT — what a good contraction looks like** (lecture 11):

> "we get **small body, small range good candles right at 10 EMA**. Okay, they're not
> closing away from 10 EMA or below that or getting volatile"

**EXPLICIT — the VCC (Volatility Contraction Candle).** Small-bodied, low-volatility
candles forming right at the moving average. Lecture 5 explains *why* it forms: if
the signal candle closed near the MA, there is very little room between price and the
support zone, so volatility mechanically compresses and the MA slope is preserved.

**EXPLICIT — proportionality (this is "relativity" applied to time and depth)**
(lecture 10):

> "When it's gone up what 60% in five six days. And it has contracted only for five
> plus three, like just eight days. **Certainly this is not enough.**"

A contraction must be proportionate to the expansion that preceded it, in both time
and depth. A 60% move does not get resolved by an 8-day pause.

**EXPLICIT — declining volume in contraction is correct** (lecture 2): "then in the
contraction the volumes [decline]".

**EXPLICIT — contraction counting rule** (lecture 12). A new contraction only begins
once price has meaningfully exceeded the previous contraction's high:

> "why was this called as a contraction two and the next one was called as contraction
> three? Because you can clearly see **the price has gone up almost 4 5% above this
> black line**. In this case, if I draw the high, the price didn't go above that even a
> percent. That is why this entire thing becomes only a single contraction"

**EXPLICIT — contraction number matters.** He counts them. "Second contraction post
event" is a favourable label (lecture 11); "base three" is extended and requires
"an agile approach... active trade management" (lecture 1).

---

## 4. The "event" — moving-average crossovers on the left-hand side

This is the author's primary filter and, with turnover, the most mechanically
reproducible part of the methodology.

**EXPLICIT — it is the primary filter** (lecture 4):

> "always keep the **event on the LHS as a primary filter or criteria**, because that
> will usually give you or side you with the weekly STF most of the times"

An "event" is a moving-average crossover that has recently occurred to the left of
the current bar. The specific crossovers named across the corpus:

- 10 EMA crossing above 20 EMA (the "small black dot", line 9101)
- 10 EMA crossing above 50 EMA
- 20 EMA crossing above 50 EMA
- 10 / 20 / 50 all converging on the 200 — the strongest case

**EXPLICIT — no event means a lower-quality trade, not no trade** (lecture 4):

> "when you don't have the event on the LHS, you know, you will get the move but again
> **not the best**... just imagine buying the stock somewhere here — you have an event
> on the LHS — and have a look at the move that you got, pretty clean, pretty good. But
> just imagine buying over here: yes you get the move, **but is it worth it?**"

The cost of no-event is *opportunity cost*, which is the author's recurring theme.

### The MA compression case — the strongest setup in the corpus

Lecture 7 is an extended case study of two visually similar areas on the same stock,
one of which failed and one of which produced the largest move the stock ever made.
The discriminator is explicit:

> "it's **not** an event of 10 crossing above 20 or 10 crossing 50 or 20-50. No, it's
> literally **all moving averages** [converging]... **10 20 50 200 all together**."

> "then you had a down move... **this is the first time you have had this**"

And the mechanism, stated plainly:

> "**What this guy had to do? Nothing. 10 20 50 200 at a single point.** So only thing
> that can happen is they start up-sloping"

When all four EMAs are compressed at one price, no further work is required of the
stock to establish a bullish configuration. Contrast the failed area, where an up move
crossed the MAs but "**all the hard work of this [was] undone by the horrible
contraction**".

**DERIVED rule:** an event is only valid if the configuration it created **survived
the following contraction**. A cross that reverts is not an event. This is the
central lesson of lecture 7 and is directly computable.

### The 10-below-200 tell

**EXPLICIT** (lecture 8):

> "**daily 10 20 50 whenever they come below 200 simply tells you that something big
> is happening on the scale of monthly**"

Used as a prompt to go and look at the monthly, not as a signal in itself.

---

## 5. Relativity

"Relativity" is the author's term for judging any move against what has already
happened — to the same stock, on the same and higher timeframes.

**EXPLICIT** (lecture 1): after a 47% move, "relativity kicks in and we know **you are
not stopping at 10**" — i.e. expect the pullback to reach the 20 or 50 EMA, not the 10.

**EXPLICIT** (lecture 7): after ~50% in 4 days, "From a relativity point of view, **do
you really think it's going to come to its 10 and move up? Probabilities are much much
less**."

**EXPLICIT** (lecture 11): a counter-candle arriving one bar into a contraction —
"Is it enough? **Think about relativity.** You really think it is enough? ... Expecting a
contraction literally just [one bar] is a bit too much."

### Operational content

Relativity converts the size of the preceding move into an expectation about *which
moving average* the pullback will reach:

| Preceding move | Expected pullback destination | Class |
|---|---|---|
| Modest, in line with DNA | 10 EMA | DERIVED |
| Large (roughly 1.5–2x DNA) | 20 EMA | DERIVED |
| Very large / extended | 50 EMA, or deeper | DERIVED |

The transcripts give no numeric boundaries. The relationship is EXPLICIT; the
thresholds are ours to fit.

**EXPLICIT — relativity also governs time:** a big move needs a *long* contraction, not
just a deep one.

---

## 6. Pivots, demand candles and the ILHS

### DC = Demand Candle

**EXPLICIT definition**, line 2117: "DC is demand C[andle]".

A demand candle is a good-quality up candle that marks where buyers appeared. Its
**low becomes the pivot** — the structural point beneath which a stop belongs.

### ILHS = Immediate Left-Hand Side

**EXPLICIT.** The bars immediately to the left of the candidate entry bar. This is the
author's most frequently applied quality test.

> "please understand, **what is the immediate left-hand side of this? That is the
> ILHS.** It's this. And this candle is **not even 50% of this**. What is the quality?
> Not that great. Buying the stock over here is not simply giving you any conviction."
> — lecture 9

### The 50% counter rule

**EXPLICIT, appears in lectures 9, 12, 13, 14.** A large red candle in the contraction
must be *countered* — a subsequent up candle must retrace a substantial portion of it,
ideally engulfing it — before the setup is tradeable.

> "these two candles are hovering **below the 50% of this candle**. Now, that is not
> ideal. And that is why buying here is extremely risky... because **the immediate
> left-hand side is showing you selling pressure.** So, the better strategy is well that
> you **let a counter candle happen. Which means a candle which basically eats up an
> offer of good quality.**" — lecture 12

### Pivot quality — the decisive selection criterion

Lecture 10 surveys roughly twenty charts and accepts or rejects each one. **Pivot
quality is the most frequent stated reason for rejection.**

> "the pivot quality is not that great... And look what happened. The price actually
> went below by almost 7 or 6% below this point."

> "**if you don't have a quality demand area, demand pivot on your ILHS, it gets really
> difficult to allocate risk to this trade because well, where do I put my SL?** That is
> a big big uncertainty. And **your position size is directly controlled by the kind of
> SL you are taking**."

This is the causal chain that makes pivot quality matter more than it first appears:

```
pivot quality  ->  can you define a stop?  ->  how wide is it?
               ->  how big can the position be?  ->  how much does the trade earn?
```

A setup with no quality pivot is not merely riskier — it is **unsizeable**, and
therefore not worth taking even if it works.

**DERIVED — what makes a pivot "quality":**
- Full body, minimal wick.
- Counters the preceding down move by ≥50%, ideally engulfing it.
- Sits at or near a moving average (see §7).
- Formed on visible volume.

**EXPLICIT — a large lower wick is a defect, not a strength** (lecture 5):

> "on the down side it has created a **huge Wick**, which means the demand area is now
> **stretched**... if you have stop losses anywhere in between the area, what exactly
> are you doing having stop loss in demand area? You're just **fuelling** — you are just
> **giving liquidity**"

---

## 7. Moving-average proximity — the four-scenario framework

Lecture 5 is dedicated to a single, subtle idea that turns out to drive entry quality
more than any other. The author presents four scenarios for a signal candle crossing
above a moving average:

| # | Opens | Closes | Verdict |
|---|---|---|---|
| 1 | near MA | far above MA | Poor — stop is wide; price must travel back |
| 2 | near MA | **near MA** | **Best** — tight stop, VCC forms naturally |
| 3 | far below MA | near MA | Mediocre — wide stop; often needs a repeat |
| 4 | far below MA | far above MA | Poor — creates a stretched demand zone |

**EXPLICIT — why the open matters:**

> "when we are starting near to the moving average, the opening, that is great...
> because you can see that this is creating a **pivot level**... and **the closer your
> structural point is to the moving average, the better it is for you**... this means
> your SL is reduced."

And a second reason:

> "if the price was not very far from the moving average, that means the consolidation
> was **shallow**. If the price was away from the moving average, then **the contraction
> was deep** and... **the moving average slope will turn down. You don't want that.**"

**EXPLICIT — why the close matters:**

> "when you're closing far away from the moving average... your SL is huge... but then
> you say okay fine, I'll wait for the stock to come closer... **this entire region the
> price will have to travel.** How does it travel? That is yet to be seen. It could print
> a bad red candle."

And if it travels slowly, over four to six small candles, "**the moving average slope
will turn flat or down**, which is not going to provide you the support".

**EXPLICIT — the range disqualifier:**

> "when this blue candle was printed, what was the condition of the moving average? **10
> was literally equal to the 20 moving average, which means a range**, and ranges [are]
> area[s] of volatility... so when you are checking for these candles **make sure 10 has
> a clearly visible distance between 20 moving average**"

Restated in lecture 9: "**it's not a clear 10 EMA. It's 10 EMA currently intermingled
with the 20.**"

This is fully computable: reject signal candles where `|EMA10 - EMA20| / price` is
below some minimum separation. The threshold is ours to fit.

---

## 8. Location, extension and the 50% context

### All-time highs

**EXPLICIT** — treated as favourable (no overhead supply) *and* as a management
problem (no reference levels):

> "it's all-time high. **Nobody knows what's the right price**, and especially when you
> use technical analysis, well, there is **no anchor point on the left-hand side**" —
> lecture 11

### Overhead liquidity

**EXPLICIT** — a prior high-volume area above current price is where a "push" (a
rejection) should be expected. Not a reason to skip, but a reason to plan partial
exits and have ETF structures ready.

### The 50%-of-prior-move context

**EXPLICIT** (lecture 10, restated in lecture 13). A contraction or base forming in the
**lower half** of the preceding down move is materially worse than one forming in the
upper half:

> "all of this was happening literally in the **50% of this down move**... **Below 50%.**
> And that's something I don't fancy."

### Extension

**EXPLICIT — extension is a timeframe-relative concept.** The stock may be extended on
the monthly while offering a clean daily setup. Lecture 9 is the treatment:

> "monthly is extended, has been going, but **my trade is being manifested on daily**"

> "now we are also heading into a territory where **monthly can decide, well, just
> enough. We are correcting now.** And that will lead to some huge red candles on the
> daily. **You don't want to be caught in that down move.**"

**EXPLICIT consequence — the momentum snap.** Extended stocks produce sudden reversals
of a magnitude the stock has never previously shown:

> "Stock on this day is 11.75% up. **The very next day you are minus 11%.** That's how
> things work when you get extended on time frames."

> "This is the first kind of candle that we have ever had in this chart since we started
> moving up. It's a **minus 20% candle. We never had that. Never. The highest was 8%.**"

**EXPLICIT — trade extension with tighter management, not avoidance:** reduce the room
given to the position as gains accumulate; switch from EMA-based trailing to pivot-based
trailing. See `EXIT_ENGINE.md`.

### Base counting

**EXPLICIT** (lecture 1): base 1, base 2, base 3. "extended into base three" calls for
"an agile approach... active trade management is required."

---

## 9. Earnings

**EXPLICIT policy** (lecture 12), and it is size-dependent rather than absolute:

- **Already up substantially?** Hold through. "I bought the stock over here. By the time
  the earnings are, I was up by almost **72%**. Even if there is a minus 20% gap down, I
  will still be plus 40."
- **Recently entered?** "I just don't have that liberty. What I actually do — if let's
  say I bought the stock here, **I'll actually sell it here**. But the next morning,
  I'll actually watch it intraday. If it gives a risk opportunity, **I'll just add it up
  again post the earnings volatility is done**."
- **Not in the stock and it looks good into earnings?** Do not enter. "**I'll never ever
  advise you to buy the stock in the anticipation of momentum coming in your favour,
  because earnings bring unexpected volatility.**"
- **After earnings:** the resulting volatility is itself tradeable on 5m/15m/1m once it
  settles.

**EXPLICIT** — earnings are classified as an "event" in the risk sense: a source of
volatility that suspends normal structural reasoning.

---

## 10. Circuits (India-specific)

**EXPLICIT** (lecture 7):

> "As long as my stock, from a position of a buyer, **as long as my stock is going up in
> circuits, I have no problem** as a buyer. **But if that stock starts coming down in
> multiple circuits, that's where the trouble is.**"

**EXPLICIT** — a contraction free of lower circuits is a positive sign. Lecture 14 ends a
132% trade specifically because of lower circuits:

> "this stock was put into the lower circuits... **I don't like lower circuits**... it's
> entirely possible we just keep falling down through in circuits and that can put you in
> a bad bad place too. And **that's exactly where I decided to close the entire
> position.**"

---

## 11. Position sizing and psychology

**EXPLICIT — starting size is large, not exploratory** (lecture 14):

> "my position sizing **do not start with 15% 20%. They usually are in the higher end of
> 35 40%.** That's where I like to start."

And lecture 4 pushes further for the best setups: "not 25% not 30% of the capital —
**60 70 80% of the capital**, that's where the money is made."

**EXPLICIT — size is a function of stop width, which is a function of pivot quality:**

> "your SL will be small, your position size will be good number" — lecture 4
> "your position size is directly controlled by the kind of SL you are taking and what
> kind of certainty there is" — lecture 10

**EXPLICIT — the pilot-position anti-pattern** (lecture 10):

> "just imagine you get this opportunity, but you are so lost in the noise that you say,
> 'Okay, let me **dip my toes in the water**, have my **pilot position** or **test
> position**', or you have position size of 25 or 30% or 15% only. Imagine making 30%,
> 20% on that. **What difference does it make? Not much.**"

**EXPLICIT — size down for higher-timeframe trades** (lecture 8):

> "**I also did not size it as much as I do as my daily trades because it's a huge
> cycle. I cannot take minus 6% on a huge size of my account** like I'm able to do it on
> a daily."

This is not a contradiction of the above: bigger scale means wider stops and longer
holds, so the same *risk* budget buys a smaller *position*.

**EXPLICIT — pyramiding is redefined.** The author rejects the common meaning:

> "**pyramiding is not** 'if the position size is working in your favour or the stock is
> working in your favour then only you keep adding' — that's not the way... these are the
> **worst areas** to add to your stock... and these are the best ones" — lecture 4

His pyramiding means adding at successive *contractions* (horizontal cycles), each with
its own defined stop — not adding into strength.

**EXPLICIT — win rate matters** (lecture 13). He argues against the common
"low win rate is fine if risk-reward is high" position, on Indian tax grounds: STT is
non-deductible, so a high-turnover, low-win-rate strategy can be profitable on a
spreadsheet and loss-making after charges. His framing:

> "**win rate is nothing but the quality of your decision-making**, which involves: are
> your entries right? Is your stock selection good?"

This is directly relevant to our backtest design: **transaction costs and STT must be
modelled**, per Section 33 of the master prompt.

**EXPLICIT — "left" vs "missed"** (lecture 13), a useful distinction for evaluating the
engine:

- **Left**: the setup was available at your price and you consciously declined it on
  quality grounds. Legitimate; accept the outcome.
- **Missed**: the setup was on your list, met every criterion, and you failed to act.
  A process failure.

> "if [the trades you left] all are moving up, and the ones I'm picking are all coming
> down — if that is the case, **then there is a big, big, major fault in your framework**"

That is a testable statement about the engine, and worth building into the backtest as a
diagnostic: compare the forward returns of accepted vs rejected candidates.

---

## 12. What the author explicitly refuses to do

Recorded because these are anti-patterns our implementation must not reintroduce.

- **No formulas from patterns.** "you just cannot blindly make it a pattern or a formula"
  (lecture 4); "**Do not make it a formula. If you do, you are in trouble**" (lecture 7).
- **No fixed MA-gap rule.** "I've seen people make formulas — the gap should be more in
  20 and 50 and all those — but **that's not the way**" (lecture 7).
- **No buying above the high of the bar.** "dumb people buy above the high of the bar"
  (lecture 7).
- **No arbitrary stops.** "you say 'Sir, 10 EMA will be my SL.' But my question is **why?
  Was there any evidence?**... Certainly arbitrary" (lecture 11).
- **No 1% stops.** Slippage consumes them (lecture 12).
- **No market-regime labelling.** "There's no bullish market and there's no bearish
  market. **Markets are always neutral**" (lecture 13).
- **No chasing.** "if you do not get the price at the best price, you're better off
  leaving it... if you repeat this process for the next 100 trades, **the expected value
  of it is going to come negative**" (lecture 12).

That last one is the closest thing in the corpus to an explicit statement of edge:
**the edge is in the entry price, not in the stock selection.**

---

## 13. Answer to the master prompt's final research question (Section 43)

> *"If my 5 existing scanners produce 100 candidate stocks, what systematic process
> derived from the trader's transcripts can reduce those 100 candidates to the
> highest-quality setups?"*

A four-gate funnel, ordered by the author's own sequence and by cost-to-evaluate:

**Gate 1 — Liquidity (hard, computable, EXPLICIT).**
20-day average turnover above a floor. This is the author's own first check. Expect it
to remove candidates cheaply and without judgement.

**Gate 2 — Event and EMA structure (hard, computable, EXPLICIT).**
A moving-average crossover on the LHS that *survived the subsequent contraction*; EMA10
clearly separated from EMA20 (not intermingled); 10 > 20 > 50 on the STF. The weekly
condition "10 above 20, 20 above 50" from lecture 8 is a strong optional filter.

**Gate 3 — Structure (computable with defined approximations, EXPLICIT concepts).**
Contraction contained within the high of the last expansion candle; contraction in the
upper half of that range; contraction proportionate in time and depth to the expansion;
a quality pivot on the ILHS that counters any large red candle by ≥50%; volume cluster
rather than single tower during the expansion.

**Gate 4 — Ranking (soft, approximated, DERIVED).**
Among survivors, rank by **risk distance** — distance from the entry to the structural
pivot — because that is what determines position size, and the author's stated edge is
in entry price. Break ties on candle quality, turnover trend, and DNA-to-risk ratio.

**What is unknown and must be tested, not assumed:**
- The blue-candle overlay (RG-01) — a first-order criterion we cannot reproduce.
- Every numeric threshold. The author supplies almost none.
- Whether "candle quality" can be usefully approximated by body/range ratios at all.

**What must be tested statistically:** whether this funnel improves on the five
scanners alone. Section 30 of the master prompt makes that mandatory, and
`BACKTEST_SPEC.md` specifies it. **Nothing in this document should be deployed before
that test runs.**
