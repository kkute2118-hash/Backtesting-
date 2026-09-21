# His stock selection, step by step

His rules in his own order, stripped of our backtesting. This is the
methodology as stated, not a claim that it is measurably profitable — what we
could measure is in `FINDINGS_DEEP.md`, and it is mostly negative. Keep the
two apart.

Tags: **HIS** = stated in the transcripts · **OURS** = a number we chose
because he refused to give one. He refuses on purpose: *"Do not make it a
formula. If you do, you are in trouble."*

Rule IDs map to `TRADER_RULEBOOK.md`.

---

## STEP 1 — Liquidity. Before the chart. (L-01…L-10)

He checks this **first** and rejects outright, before looking at anything.

| | |
|---|---|
| measure | **20-day average turnover in ₹ crore** = close × volume, averaged over 20 sessions. Twice stated, never any other lookback. **HIS** |
| reject | ~₹1–2.5 cr/day — *"extremely less"* **HIS** |
| healthy | ~₹80–90 cr/day — *"pretty healthy for most of our account sizes"* **HIS** |
| the floor | somewhere between ₹3 cr and ₹80 cr. He never says where. Ours is ₹40 cr. **OURS** |
| relative | adequacy depends on **your account size**, not an absolute number **HIS** |
| why | thin stocks slip, and slippage eats a tight stop — which is the whole edge **HIS** |

**Also read the direction of turnover, not just the level (L-07, L-08):**

- the 20-day average **rising through the move** is confirmation — his worked
  example goes 175 → 200 → 255 cr as the move develops
- a single day at **5–7× the average** is "big" — his example is 175 → 1,250
- always read turnover **together with** the day's % move and candle quality,
  never alone (L-09)

> This is the "smart money" read, and it is a *comparison*, not a level: money
> arriving where there was less money before. A big candle on an ordinary
> turnover day is the trapping move — price went up and nothing actually
> changed hands.

## STEP 2 — DNA. What is normal *for this stock*. (D-01…D-09)

Assessed **before** trend, stage or structure.

- DNA = the stock's typical single-candle % move on the timeframe you trade
- DNA also = the typical **full up-move** %, computed by **summing the positive
  candles**, not high minus low (D-04)
- measure it only on genuine up moves, **never inside a range** (D-05)
- it includes candle *quality*: opens near the low, full body, small wicks
- rough bands: daily 8–20%, weekly 15–30%, monthly 25–40% — per stock, not
  universal **DERIVED**
- the **target comes from DNA**, not from a fixed R multiple (D-07)

## STEP 3 — The event on the left-hand side. (E-01…E-12)

*The* primary filter. No event, no trade.

- the averages are **10, 20, 50, 200 EMA** (his legend: black / blue / green /
  orange)
- an **event** = a recent crossover — 10>20, 10>50, 20>50, or all four
  converging at one price (the strongest configuration)
- the event is only valid if the configuration **survived the contraction that
  followed** (E-06)
- **10 must be clearly separated from 20.** Intermingled = range = reject
- weekly: require 10>20 **and** 20>50, otherwise skip the stock entirely
- *"Every move towards 10 EMA is a buy"* — but **only** once 10 is above 20,
  sloping up, with a higher-low / higher-high structure (E-12)

## STEP 4 — The expansion. (X-01…X-06, V-01…V-05)

- expansion candles: **full body, open near the low, minimal wick**
- **volume cluster, not a single tower.** Several adjacent elevated bars.
  *"I need volumes all throughout"*. One isolated tall bar disqualifies
- a **weak expansion** that creeps up is a disqualifier — the 10 EMA flattens
  and stops offering support
- identify **the candle the expansion ended on**. Everything in step 5 is
  measured against that candle's high
- CB candles: his blue / dark blue shading, a day the stock performed
  **extremely well compared with its own other good days**. Count them, and
  white candles interleaved in the run are a defect **HIS, unquantified**

## STEP 5 — The contraction. (K-01…K-12)

- **the entire contraction must stay inside the high of the expansion-ending
  candle** — *"one of the most important points I'll ever give you"*
- it should sit in the **upper half** of that range. Shallow, not deep
- small bodies, small ranges, **right at the 10 EMA** (this is the VCC)
- **proportionate in time** to the expansion — 60% gained in 6 days is not
  resolved by 8 days of rest
- **proportionate in depth** — this is relativity
- a red candle in the contraction **bigger than the expansion candles** is a
  serious defect
- a contraction forming in the **lower half of the prior down move** is
  materially worse
- volume **should** decline through the contraction — that is correct
  behaviour, not weakness
- no lower circuits
- count contractions since the event: **second contraction post-event is
  favourable**; base 3 is extended — smaller size, active management

## STEP 6 — The pivot. No pivot, no trade. (P-01…P-12)

His most common stated reason for rejection.

- **DC = demand candle.** The pivot is its **low**; the stop goes below it
- a large red candle must be **countered** by an up candle retracing **≥50%**,
  ideally engulfing it. Candles hovering below that 50% line = selling
  pressure = do not buy
- a **large lower wick** stretches the demand zone — a defect, not strength
- **never place a stop inside a demand zone** — you are handing the market
  liquidity
- the closer the pivot sits to the MA, the better: tighter stop, shallower
  contraction
- best add point: **daily 50 EMA + the demand-candle pivot at the same price**
- no pivot on your timeframe → drop to 1h → 15m → 5m to find one
- **no quality pivot → no definable stop → no sizeable position → skip**

## STEP 7 — MA proximity of the signal candle. (M-01…M-06)

Four cases; only one is good.

| case | open | close | verdict |
|---|---|---|---|
| **2** | **near the MA** | **near the MA** | **best** — nearby pivot, tight stop, and a VCC is likely next |
| 1 | near the MA | far above | price has to travel back |
| 3 | far below | near the MA | deep contraction, MA slope turning down |
| 4 | far below | far above | worst — stretched demand zone; price often falls again |

## STEP 8 — Relativity and extension. (R-01…R-08)

- judge every move against **what this stock has already done**
- after a large move do **not** expect a shallow 10 EMA pullback — expect the
  20 or the 50
- extension is **timeframe-relative**: monthly-extended can still give a clean
  daily setup
- extended stocks produce **snaps** — reversals bigger than any the stock has
  shown before
- trade extension with **tighter management, not avoidance**

## STEP 9 — Entry. (N-01…N-09)

- **buy in contraction, never in momentum**
- daily close above the 10 EMA → watchlist, not a buy
- trigger: a candle takes **10 above 20 and the configuration holds**
- three entry types: value buy in the demand zone · repeat of the same zone ·
  certainty buy on the 10>20 cross. The certainty buy costs more and is worth it
- never buy above the high of a bar as a rule in itself
- do not enter in anticipation of earnings
- **not at your price → skip.** *"If you do not get the price at the best
  price, you're better off leaving it."*

## STEP 10 — Stop and size. (S-01…S-12)

- stop goes **below a structural pivot** — never a round number, never an
  arbitrary MA
- stop width must be **proportionate to DNA**: a 17–20% stop is wrong when
  monthly DNA is 25–30%
- to tighten a stop, **drop a timeframe** and find a nearer pivot — do not just
  move the stop up
- the ladder he works to: **monthly STF ~10% · weekly ~6% · daily ~3%**
- an **expectational stop of 1.5–2%** is allowed when there is no structural
  pivot and the thesis is pure momentum — but prefer a structural 3% to an
  expectational 2%
- **never a 1% stop** — slippage eats it
- size is set by stop width. Start 35–40% of capital; best setups 60–80%
- reject pilot positions: a 20% gain on 15% size is not worth the slot
- once up ~7%, move the stop near breakeven — but do **not** ratchet it on
  every green day

---

## His refusals, which are rules too (G-01…G-06)

- **do not turn an observation into a formula**
- **context beats pattern** — a "bad candle" can be correct in context
- **no market-regime labelling.** Markets are neutral
- **STT is not deductible**, so high-frequency low-win-rate systems lose after
  charges even when they look positive before them
- **"left" ≠ "missed".** Declining on quality is process working; failing to
  act is process failing. Track them apart
- **opportunity cost is a valid reason to reject or exit**

---

## What we could and could not verify

| step | testable from daily OHLCV? | measured verdict |
|---|---|---|
| 1 liquidity | yes | floor matters decisively for S4 (+3.0%/trade); mixed elsewhere |
| 1 turnover *change* | yes | reverses sign between years; no stable edge |
| 2 DNA | partly | not tested as a standalone gate |
| 3 event | yes | already inside S2 and S4 |
| 4 CB purity | yes | held on 2 years, failed on 5. Gate off |
| 4 volume cluster vs tower | yes | no stable edge; flips sign between years |
| 5 contraction | yes | the gate stack inverted the funnel |
| 6 pivot | yes | ranking by tight stop was backwards three ways |
| 7 MA proximity | yes | entry timing cost 2.39 points |
| 8 relativity | partly | not isolated |
| 9 entry | **no** — needs hourly/15m | his real entry is a 3-scale confluence |
| 10 stop | **no** — the 3% stop needs intraday bars | daily-only forces ~7% |

Steps 9 and 10 are the ones we genuinely cannot test: his entry is
*daily to 10 EMA → hourly to 50 EMA → 15-min to 200 MA*, and he enters on the
last of those. We store daily bars only. Everything we measured is therefore
his **weekly-STF case at best**, judged against a 7% stop instead of 3%.
