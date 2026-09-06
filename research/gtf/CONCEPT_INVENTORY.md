# GTF "Trading in the Zone" — concept inventory

Source: 3,146-minute (52.4 h, 20-episode) Hindi/Hinglish transcript,
*A Complete Course on Stock Market: Beginner to Advanced — GTF*
(Get Together Finance, instructor Arun Singh Tanwar).

The course is **not** an indicator course. Word counts over the whole
transcript settle what it actually teaches:

| term | count | | term | count |
| --- | --- | --- | --- | --- |
| zone (जोन) | 4,724 | | moving average | 223 |
| candle | 3,748 | | breakout | 84 |
| demand | 3,015 | | volume | 14 |
| base candle | 977 | | MACD | 0 |
| supply | 2,163 | | Fibonacci | 0 |
| leg-out | 665 | | RSI (standalone) | 0 |
| proximal | 409 | | | |
| distal | 214 | | | |

RSI and Stochastic appear only in the last episode, and only as an
optional +1 confirmation *on top of* a complete demand/supply setup
("बिना डिमांड सप्लाई के नहीं करना" — never use them without demand/supply).

---

## A. Testable rules (objectively codeable)

### A1 — Candle classification (~168-200 min)

> "एक्साइटिंग कैंडल की डेफिनेशन होती है बॉडी पार्ट इज ग्रेटर देन 50% ऑफ द रेंज ऑफ कैंडल"

```
range = high - low
body  = |close - open|
exciting  if body > 0.50 * range
base      if body <= 0.50 * range
```
Green exciting = buyers dominate; red exciting = sellers dominate; base =
buyer/seller balance. **Confidence: high.**

### A2 — Zone patterns (~306-322 min)

Three components, minimum one of each: **leg-in → base(s) → leg-out**.

| | leg-out green | leg-out red |
| --- | --- | --- |
| leg-in red (drop) | **DBR** demand, *reversal* | **DBD** supply, *continuation* |
| leg-in green (rally) | **RBR** demand, *continuation* | **RBD** supply, *reversal* |

* Leg-in and leg-out must both be exciting candles.
* Multiple leg-ins, bases and leg-outs are allowed.
* Leg-out priority > leg-in priority.
* A leg-in that stays inside the base range is re-read as part of the base
  (so DBR becomes RBR). **Confidence: high.**

### A3 — Zone marking (~342-376 min)

| | proximal line | distal line |
| --- | --- | --- |
| demand | **highest body** of all base candles | **lowest wick** of all base candles |
| supply | **lowest body** of all base candles | **highest wick** of all base candles |

Mnemonic given: प for पास (near) = proximal; द for दूर (far) = distal.
This is "body-to-wick" marking; "wick-to-wick" is allowed for a single
narrow base candle. **Confidence: high.**

### A4 — Freshness (~349-357 min)

> "फर्स्ट लेग आउट कैंडल के बाद में कभी भी प्राइस प्रॉक्सिमल लाइन को टच करके
> अगर ऊपर जा चुकी है तो वो जोन टेस्टेड हो चुका है"

Counted from **after the first leg-out candle**. Each time price touches the
proximal line and leaves the zone again = one test. Fresh = zero tests.
**Confidence: high.**

### A5 — Leg-out "achievement" (~316, 446-451 min)

A leg-out that does not travel beyond the proximal line — that stays inside
the base/zone range — has "no achievement" and the zone is poor. Several
small leg-outs that together cover less ground than one large one are
likewise poor. **Confidence: medium** (the video gives the principle, not a
number; the number has to be chosen and tested).

### A6 — Closing concept (~732-742 min)

> "क्या वो लेग इन कैंडल के ऊपर में क्लोज हुई है"

For a demand zone the leg-out must **close above the leg-in candle's high**
(supply: close below the leg-in low). If it merely wicks above and closes
back below, the *opposing* zone has proved itself and this zone has not.
Applied on the execution timeframe only. **Confidence: high.**

### A7 — Trend (~902-915 min)

Fully mechanical:
1. Plot **SMA 50** ("सिंपल मूविंग एवरेज 50 मैथमेटिकली सबसे बेस्ट प्रूवन मेथड है").
2. Count back **7 candles** including the current one.
3. Draw a vertical line there, and a horizontal line where it crosses SMA50.
4. Read the SMA50 as a clock hand from that point: 12→3 (rising) = **uptrend**;
   3→6 (falling) = **downtrend**; parallel to 3 (flat) = **sideways**.

i.e. `sign(SMA50[t] - SMA50[t-6])`. **Confidence: high.**

Usage: buy demand only in an uptrend; sell supply only in a downtrend.
"ट्रेंड जो है वो सबसे बड़ा हमारा हथियार है."

### A8 — Multi-timeframe sets (~919-931 min)

| Trading purpose | HTF (location / curve) | ITF (trend) | LTF (execution) |
| --- | --- | --- | --- |
| HIT hourly income trade | 60 m | 15 m | 5 m |
| DIT daily income trade | Daily | 60 m | 15 m |
| WIT weekly income trade | Weekly | Daily | 60 m |
| **MIT monthly income trade** | **Monthly** | **Weekly** | **Daily** |

HTF decides buyer-or-seller; ITF carries the trend; LTF carries entry, stop
and target. **MIT is the only set our daily candle store can express
end-to-end**, and it is also the one the instructor recommends
("डब्लू आईटी और एमआईटी पर ज्यादा से ज्यादा फोकस करें").
**Confidence: high.**

### A9 — Curve / location (~937-950 min)

On the HTF: mark the **nearest fresh demand zone below** and the **nearest
fresh supply zone above**, then split *demand-proximal → supply-proximal*
into three equal parts:

| section | action |
| --- | --- |
| inside the demand zone — **very low on curve** | buy |
| lower third — **low on curve** | buy |
| middle third — **equilibrium** | go with the trend |
| upper third — **high on curve** | sell |
| inside the supply zone — **very high on curve** | sell |

Location zones may be normal, multi-base, weakly-legged, even ~25 % tested;
execution zones must be the best available. **Confidence: high.**

### A10 — Entry and stop (~467-486 min)

* Demand: entry **just above** the proximal line; stop **just below** the
  distal line, with more room than the entry offset.
* Supply: entry just below proximal; stop just above distal.
* No fixed offset is given ("रैंडम एंट्री पिक करें"); the stated reason for the
  wider stop room is the U-turn analogy — a fast move needs a wider turning
  circle. **Confidence: high on structure, low on the offsets** (untaught).

### A11 — Target (~480, 1119-1130 min)

Interim rule: **2 × risk**, and *"अगर किसी भी ट्रेड सेटअप में हमें डबल टारगेट नहीं
मिलने वाला … तो उस ट्रेड सेटअप को हम इग्नोर कर देंगे"* — a setup that cannot
offer 2R is skipped.

Final rule: target = **proximal line of the opposing zone on the
intermediate (trending) timeframe**, measured *at the time of arrival*, and
it must still clear 2R or the trade is dropped. If no opposing zone exists:
book 2R on a merely-good level, trail on a 7/7 level.
**Confidence: high.**

### A12 — Trade score (~1066-1078 min) — max 7

| parameter | condition | points |
| --- | --- | --- |
| **Freshness** | fresh | 3 |
| | tested once | 1.5 |
| | tested twice or more | 0 |
| **Strength** | leaves with ≥ 2 exciting candles | 2 |
| | leaves with 1 exciting candle **+ a gap** | 2 |
| | leaves with 1 exciting candle, no gap | 1 |
| **Time at the base** | 1-3 base candles | 2 |
| | 4-5 base candles | 1 |
| | more than 5 base candles | 0 |

7/7 is by construction the best level. **Confidence: high.** This is the
single most valuable artefact in the course: a complete, closed-form,
parameter-free quality score.

### A13 — Never trade against the location (~1131 min)

An "execution-best trade" — shorting a supply zone while price sits on the
HTF demand — is called out as 95-99 % stop-out. **Confidence: high** as a
statement; testable as a filter.

---

## B. Testable hypotheses (need a definition before testing)

* **B1** "Leg-out should be explosive" — needs a threshold (leg-out range ÷ ATR,
  or ÷ zone height).
* **B2** "Garbage zones" — zones formed inside pre-existing congestion.
  Needs a congestion measure.
* **B3** "Authentic vs non-authentic" — a zone created as the reaction to
  another zone. Needs a lookback and a proximity rule.
* **B4** ~25 % tested location zones are acceptable — needs a penetration depth.
* **B5** Gap handling — a gap counts as a candle in its own right.

## C. Subjective / discretionary

* Which of several equally-scored zones to pick.
* "Does the leg-out have achievement" judged by eye.
* Trailing rules (taught as a narrative, not a formula).
* Whether a zone "looks like" distribution.

## D. Educational, not backtestable

Psychology, fear/greed/FOMO, capital and margin discipline, the Mahabharata
analogy for confluence, broker and charting-software setup, "never take
margin", position sizing by fixed rupee risk.

---

## The speaker's core philosophy

Institutional order-flow price action. Price moves because unfilled
institutional orders sit at the places where an imbalance began; a zone is
the footprint of that origin. Everything else — trend, curve, multi-timeframe
— exists to decide **which** footprint to bet on. It is a
**multi-timeframe, fresh-zone, trend-aligned mean-reversion-to-origin**
system with a fixed 2R floor: buy pullbacks into untested origins of prior
up-moves, inside an uptrend, low on a higher-timeframe curve.

Notably it contains **no** volume rule, **no** indicator entry, and no
breakout entry — it explicitly buys weakness into support, not strength.
That is the opposite side of the trade from the existing S1-S4 system,
which the prior audit found "is built to buy strength; over this window
strength was the wrong side."
