# VOLUME_LIQUIDITY_SPEC

Source: 14 lecture transcripts, 93,862 words (`bulk_transcripts_14_1.txt`).
Every claim below carries a line citation into that file. Nothing here is inferred
from outside the transcripts.

Evidence classes used throughout: **EXPLICIT** (the author states it),
**DERIVED** (consistent across repeated examples but never stated as a rule),
**UNKNOWN** (referenced but never defined), **CONFLICTING** (the transcripts
disagree with themselves).

---

## 1. The mandated question: are there three volume / average-volume tools?

> **The transcripts do not establish three distinct average-volume formulas/tools.**

This is the required verbatim answer from Section 8 of the master prompt, and it is
the honest one. The evidence:

- The word **"volume"** appears **64 times** in 12,637 lines.
- The phrase **"average volume"** appears **exactly once**, at line 5555, and it is
  used loosely as an adjective ("a blue candle and average volumes you reclaimed
  your 10 EMA") — not as a named indicator, not with a lookback, not with a formula.
- Searches for `avg volume`, `volume average`, `moving average of volume`,
  `volume MA`, `volume indicator`, `relative volume`, `volume profile` return
  **zero** matches.

Every other volume reference in all 14 lectures is a *qualitative visual judgement*:
"good volumes", "high volumes", "low volumes", "humongous volume", "volumes are
there", "volumes are decreasing". The author reads volume off the chart by eye. He
never once computes an average of volume.

What he *does* compute, repeatedly and with numbers, is **average turnover in
rupees**. That is a different quantity, and Section 9 of the master prompt is right
to separate them.

### What the transcripts actually establish

Four distinct volume/liquidity constructs exist in the material. Only one is a
formula.

| # | Construct | Volume or turnover? | Average? | Formula stated? | Class |
|---|---|---|---|---|---|
| 1 | 20-day average turnover (₹ crore) | Turnover | Yes | Yes | EXPLICIT |
| 2 | Single-day turnover vs that average | Turnover | No (ratio) | By example only | EXPLICIT |
| 3 | Volume cluster vs single tower of volume | Volume | No | No — visual | EXPLICIT concept, UNKNOWN formula |
| 4 | The "blue / dark blue" candle overlay | Unknown | Unknown | No | UNKNOWN |

Presenting these as "the three average-volume tools" would be a fabrication. They
are one average, one ratio, one visual pattern, and one undefined chart overlay.

---

## 2. Tool #1 — Average turnover over 20 trading days

**The single most important quantified liquidity measure in the entire corpus.**

- **Exact name used by author:** "average turnover", "the average turnover of the
  stock", "average turnover last 20 days".
- **Unit:** ₹ crore per day.
- **Lookback:** **20 trading days.** EXPLICIT, stated twice, both in lecture 12.
- **Is it an average:** Yes.
- **Is it a ratio:** No.
- **Chart visual:** It appears as a read-out on his TradingView chart (he says "let's
  actually see it" and reads a number off screen), so it is almost certainly a
  built-in or custom indicator display rather than something he computes by hand.
- **Computable programmatically:** Yes, trivially.

### Transcript evidence for the 20-day lookback

Line 10074–10076, on Force Motors:

> "if you actually see the liquidity you can clearly see whatever the average
> turnover is right now must have been back then. So it's **almost 250 crores on an
> average for the 20 days**."

Line 10091–10093, on KPI/"Kew" Power:

> "Correct, **80 80 crores average turnover last 20 days**, which is pretty healthy.
> Not the best. Uh pretty healthy, right? It's still pretty good. For most of our
> account sizes."

These are the only two places in 93,862 words where a turnover lookback is named.
Both say 20. There is **no** transcript support for 21, 30, 50 or any other period.
A search for `21 days`, `30 days`, `50 days` returns nothing in a turnover context.

### Configuration constants

```python
# The author's own period. Do not change this: it is what the transcripts prove.
AUTHOR_AVERAGE_TURNOVER_LOOKBACK = 20   # trading days

# Our platform's existing period, kept separate and configurable.
SYSTEM_TURNOVER_LOOKBACK = 21           # trading days
```

These must stay two distinct names. Collapsing them would silently rewrite the
author's rule into ours — exactly what Section 9 forbids.

> **Practical note:** 20 vs 21 trading days will move an average turnover figure by
> well under 5% in almost every case. The distinction matters for *fidelity*, not
> for outcomes. Any backtest should report both and show the difference is immaterial
> rather than assume it.

### How the author interprets the level

He never states a hard floor. He states preferences and rejections, from which a
band emerges:

| Observed value | Author's verdict | Line |
|---|---|---|
| ₹1 crore/day | "there was no liquidity here" — left the trade | ~1858 (flat) |
| ₹2.5–2.57 crore/day | "Extremely less" — left the trade | ~1857 (flat) |
| ₹80–90 crore/day | "pretty healthy. Not the best... still pretty good. For most of our account sizes" | 10091 |
| ₹175 crore/day | treated as unremarkable, good | 8832 |
| ₹182.3 crore/day | "insane amount of money involved on an average every day" | 5418 |
| ₹250–255 crore/day | "That's not small" | 8846, 10074 |
| ₹400–600 crore/day | cited approvingly as a reason the stock was picked | lecture 13 |

**DERIVED band:** the author's practical floor sits somewhere between ₹3 crore
(explicitly rejected) and ₹80 crore (explicitly "pretty healthy"). The transcripts
do **not** locate it more precisely. Anyone implementing this must treat the floor as
a **tunable parameter to be fitted on our own data**, not as a transcript constant.

**Important caveat the author states himself:** the adequacy of turnover is relative
to *account size*, not absolute — "pretty good **for most of our account sizes**"
(line 10092). A liquidity floor is therefore a property of the trader, not of the
stock. Our platform's existing ₹40 crore/day floor sits inside his observed band and
is not contradicted by anything in the transcripts.

---

## 3. Tool #2 — Single-day turnover against the 20-day average

- **Exact name:** none. The author expresses it as a comparison in prose.
- **Unit:** ₹ crore (both terms), or a dimensionless ratio.
- **Is it an average:** No. It is *today* measured against tool #1.
- **Computable:** Yes.
- **Class:** EXPLICIT by worked example; no threshold ever stated.

### Transcript evidence

Lecture 11, lines 8830–8848, walking forward day by day through one stock:

> "the average turnover of the stock is **175 crores** and this day got you **1,250
> crores**. Now, that is not small. That is something to be noted... That's big."

> "another day which had a turnover of more than **1,000 crores**. And now the average
> turnover of the stock has **climbed up to 200 crores**."

> "Then we had another these days, you know, **400 crores**. Now at this point, you
> see, we are sitting at average turnover of **255 crores**."

Line 9267–9273, later in the same stock:

> "by this time, the turnover of the stock is now coming in the numbers of 800, 600
> crores... These numbers are also more than 1,000 crore. Okay? And look at the
> quality. It's a **12% day with more than 1,000 crore turnover**. Can't leave like
> that."

### Interpretation

Two things are being read at once, and they are separable:

1. **The spike ratio.** 1,250 / 175 ≈ **7.1×**. 1,000 / 200 = 5×. These are the days
   he calls "big" and "can't leave like that". No threshold is stated; 5–7× is what
   the worked examples show.
2. **The drift of the average itself.** He explicitly tracks the 20-day average
   *rising* through the move: 175 → 200 → 255 → 600–800. A rising average turnover is
   treated as confirmation that real money has entered the name and stayed. This is
   the more distinctive idea, and it is directly computable as the slope of the
   20-day average turnover series.

**Strong:** a >5× turnover day, *and* the 20-day average visibly climbing over the
following weeks.
**Weak:** a single big turnover day that leaves the 20-day average unchanged — this
is the turnover analogue of the "single tower of volume" (tool #3).

**Combined-quality rule (EXPLICIT, line 9271):** the author always pairs turnover with
the day's percentage move and candle quality — "a 12% day with more than 1,000 crore
turnover". Turnover alone is never the signal.

---

## 4. Tool #3 — Volume cluster vs single tower of volume

This is the author's only genuine *volume* (not turnover) construct, and it is
entirely visual.

- **Exact names:** "volume cluster", "good volume cluster", "single Tower of volume",
  "cluster of volumes".
- **Is it an average:** No.
- **Is it a ratio:** No.
- **Chart visual:** Yes — he literally draws a triangle over the volume bars.
- **Formula:** **None given.** UNKNOWN.
- **Computable as stated:** No. Any implementation is an approximation that must be
  validated, per Section 41.

### The defining passage — lines 996–1013 (lecture 1)

> "with good **volume cluster** but this is the important point that I'm talking
> about it's about the volume cluster. I've talked about this point before as well
> that the **single Tower of volumes** — this is a single Tower of volume, there is no
> good volume before that or after that; there are good volume clusters that you see
> here which are absent. So that's an important point you have to write: there is a
> good volume cluster that I see... **to show the volume cluster you can certainly
> draw a triangle**, it helps you."

### The definition, restated precisely

- **Single tower of volume:** one high-volume bar with no elevated volume on either
  side of it. **Rejected.**
- **Volume cluster:** *several consecutive or near-consecutive* elevated-volume bars
  spanning the expansion. **Required.**

The discriminator is **persistence across adjacent bars**, not the height of any one
bar.

### Corroborating passages

Line 7303–7312 (lecture 10), rejecting a stock:

> "look at this volume. On 14%, there is a humongous volume here. But **where were you
> when the stock was going up 7%?** It was literally average. And where were you when
> the stock was going 10% here? It was just average. So, this is something that I
> don't fancy. You know, **I need volumes all throughout** over here when you are the
> starting out."

That is the single-tower rejection applied in real time to a real candidate. It is
the clearest statement of the rule in the corpus.

Line 1416–1422 (lecture 2):

> "there were volume clusters in the up move... the volume clusters are present okay
> and then in the contraction the volumes [decline]"

Line 12549 (lecture 14): "the volumes are decreasing. Not a very [good look]" — said
of a *rising* leg, where declining volume is a warning.

### Extracted rule (EXPLICIT concept, DERIVED thresholds)

> **Expansion requires a volume cluster. Contraction should show declining volume.**
> A lone volume spike surrounded by average volume is a disqualifier.

### Proposed computable approximation — NOT the author's formula

The author gives no formula, so this is ours and must be labelled as such and
validated against his worked examples before use:

```
elevated(i)      = volume[i] >= K * median(volume[i-20 : i-1])        # K ~ 1.5–2.0
cluster_score    = count of elevated bars within the expansion window
                   / length of expansion window
single_tower     = (count of elevated bars == 1) and cluster_score < 0.2
```

`K` and the 0.2 cut-off are **free parameters with no transcript support**. They must
be fitted and reported as fitted.

---

## 5. Tool #4 — The "blue candle" overlay: UNKNOWN

The author repeatedly selects stocks on the basis of candles being "blue", "dark
blue" or "navy blue". This is not standard TradingView colouring, and **the
transcripts never define what makes a candle blue.**

### Why we know it is an overlay, not ordinary colouring

In lecture 6 he sets up his chart from scratch and states his colour scheme
explicitly:

> "The first thing that you will do, you'll make this white. **The green one will be
> white.** The red one stays red. Why? There is a reason which I'll tell you later.
> The borders will be black."

So in his scheme an ordinary up candle is **white** and a down candle is **red**.
Blue is therefore something added by an indicator. He never returns to explain "the
reason", in this lecture or any other.

### How he uses it

Line 9745–9752 (lecture 12):

> "What is the quality of candles? Are there any **white candles** in between? Like we
> had over here? No, we don't have this time. In fact, **every single candle of the
> expansion is a blue shade colour candle.**"

Line 4896 (lecture 7): "look at how many **dark blue candles** you are having. 1 2 3 4."
— he *counts* them and compares counts between two setups.

Line 5886, 6017 (lecture 9): "the up moves are now happening through **navy blue
candles**"; "the DNA of daily is pretty good, right? Navy blue candles."

Line 957–959 (lecture 2): "every up move had these **Blue candles** and the good thing
is this up move had a dark blue candle."

### Assessment

This is a **first-order selection criterion** — he counts blue candles and rejects
stocks that show white ones in the expansion — and its definition is **missing**.

The most likely hypothesis, given that he shows blue candles and says "look at the
volumes" in the same breath throughout, is that blue shading encodes **volume above
some threshold**, possibly with intensity (blue vs dark blue vs navy blue) encoding
magnitude. There is also a plausible reading where it encodes **body size / candle
quality**. The transcripts support neither over the other.

> **This is the single largest gap in the knowledge model.** It is logged as
> RG-01 in `RESEARCH_GAPS.md`. It cannot be resolved from the supplied material and
> must not be guessed at in code.

### Separate, resolvable marker: the "small black dot"

Distinct from candle colour, and this one *is* recoverable. Line 9101–9105:

> "If you see, there is a **small black dot** over here. Now see, the small black dot
> appeared on this day, too, right? But after that, what happened? We again came back
> down, which is **10 going below 20**."

The dot marks the bar on which **EMA10 crosses above EMA20**. This is fully
computable and is used as an entry trigger — see `ENTRY_ENGINE.md`.

### Moving-average colour legend (EXPLICIT, line 1297)

> "**black is 10 moving average, blue is 20 moving average, and the green one is 50
> moving average, and this red is your 200 moving average**"

Note this makes "blue" ambiguous in the transcripts: a *blue line* is the 20 EMA, a
*blue candle* is the undefined overlay. Line 5511 confirms the line sense: "I can see
the blue line that is my 20 moving average. The green line 50."

---

## 6. Liquidity as a gate — how the author actually uses it

### It is a pre-filter, not a score component

The author checks liquidity **first**, before any chart analysis, and uses it to
discard candidates outright:

- Lecture 9, opening: "when I take a note of the **liquidity, it's pretty good**.
  Like, it doesn't get better than that, right? So, the liquidity is taken care of.
  **Then** we see the DNA."
- Lecture 10: "another great stock... but **because of the liquidity kind of left
  it**."
- Lecture 13: "I'll actually tell you **a weakness of mine. Focus on liquidity.** Now,
  this did not have as much liquidity, right? So, just left it. Other than that,
  it's pretty beautiful looking chart."

That last quote is important and slightly self-critical: he calls his own liquidity
strictness a "weakness", because it made him skip charts he otherwise liked. It is
still how he trades.

### Why he cares: slippage and exit capacity, not signal quality

- Lecture 12: "1% at times is gone in slippages. If you're handling a good position
  size, 1% at times goes in buying and selling, combined slippage."
- Lecture 13: "when things like this happened right in the opening minutes of the
  market, and if you go on to press and try to execute your stop losses, **if the
  account is good, you will end up moving the prices**. So you'll have to pay premium
  to get out of this stock on the downside."
- Lecture 11: "I don't like to add on these days. These are momentum days. Usually it
  happens in the first 15 30 minutes. **I just don't get the liquidity.**"

Liquidity is an *execution* constraint. It does not make a setup better; it makes a
setup tradeable at size.

### Intraday liquidity for entry timing

For entries executed on lower timeframes he applies the same thinking at a smaller
scale. Lecture 13: "the liquidity was immense over here, if you see. Like **80 crores,
40 crores, 30 crores every single 15 minutes.** I have to take advantage to get the
entry." Lecture 10: "liquidity on a 1 minute was pretty good. **Two crores or three
crores** like that."

This is out of scope for a daily-bar platform but is recorded for completeness.

---

## 7. Conflicts and cautions

### CONFLICT-01 — momentum-day adds

Lecture 11, lines 9273–9277, reads as a direct self-contradiction in consecutive
sentences:

> "Now, see, **I don't like to add on these days. These are momentum days.** Usually
> it happens in the first 15 30 minutes. I just don't get the liquidity. **So, for me
> these are the perfect day to add on to a stock.**"

The surrounding argument (no liquidity, prices gap in the first 15–30 minutes, he
repeatedly rejects chasing momentum elsewhere) makes the first sentence the intended
meaning. The final sentence is most plausibly a transcription error for "these are
*not* the perfect day". **Resolution: treat momentum days as NOT add-on days**, which
is consistent with every other lecture. Logged as RG-04.

### Ordinary-volume language is not evidence of a formula

Phrases like "good volumes", "amazing volumes" and "high volumes" appear dozens of
times and are tempting to quantify. They are not defined anywhere. Any threshold we
attach to them is ours, and must be labelled ours.

---

## 8. Summary of computable outputs

| Feature | Formula | Transcript support | Class |
|---|---|---|---|
| `avg_turnover_20d` | rolling mean of (close x volume) over 20 trading days, in ₹ crore | Lines 10074, 10091 | EXPLICIT |
| `turnover_spike_ratio` | today's turnover / `avg_turnover_20d` | Lines 8830–8848 (5–7x examples) | EXPLICIT by example, threshold DERIVED |
| `avg_turnover_slope` | change in `avg_turnover_20d` over the expansion | Lines 8835–8848 (175→200→255) | EXPLICIT by example |
| `volume_cluster_score` | fraction of expansion bars with elevated volume | Lines 996–1013, 7303–7312 | Concept EXPLICIT, formula OURS |
| `single_tower_flag` | exactly one elevated bar, isolated | Lines 1000–1003 | Concept EXPLICIT, formula OURS |
| `blue_candle` | **undefined** | Lines 957, 4896, 9752 | UNKNOWN — RG-01 |

Constants:

```python
AUTHOR_AVERAGE_TURNOVER_LOOKBACK = 20   # EXPLICIT, lines 10074 / 10091
SYSTEM_TURNOVER_LOOKBACK         = 21   # our platform, unchanged, separate
TURNOVER_FLOOR_CR                = None # no transcript value; must be fitted
VOLUME_ELEVATION_MULTIPLE        = None # no transcript value; must be fitted
```
