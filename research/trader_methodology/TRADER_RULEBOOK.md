# TRADER_RULEBOOK

Every rule extractable from the 14 transcripts, classified and numbered.
`TRADER_METHODOLOGY.md` explains the reasoning; this file is the testable list.

**Classes**
- **EXPLICIT** — the author states the rule in words.
- **DERIVED** — consistent across repeated examples, never stated as a rule.
- **UNKNOWN** — referenced as important but never defined.
- **CONFLICTING** — the transcripts disagree with themselves.

**Computability**
- **C** — fully computable from OHLCV.
- **A** — computable only via an approximation we invent (must be validated).
- **N** — not computable from the transcripts as written.

Rules marked `[threshold: OURS]` have no numeric value in the transcripts. Any number
attached to them is a fitted parameter and must be reported as such.

---

## L — Liquidity

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| L-01 | Average turnover is measured over **20 trading days**, in ₹ crore | EXPLICIT | C | L10074, L10091 |
| L-02 | Liquidity is checked **before** chart analysis and used to reject outright | EXPLICIT | C | Lec 9 open, Lec 10, Lec 13 |
| L-03 | ~₹1–2.5 cr/day is "extremely less" → reject | EXPLICIT | C | Lec 13 |
| L-04 | ~₹80–90 cr/day is "pretty healthy... for most of our account sizes" | EXPLICIT | C | L10091 |
| L-05 | Liquidity adequacy is **relative to account size**, not absolute | EXPLICIT | N | L10092 |
| L-06 | A turnover floor exists between ₹3 cr and ₹80 cr but is never specified `[threshold: OURS]` | DERIVED | C | inferred from L-03/L-04 |
| L-07 | The 20-day average turnover **rising through the move** is confirmation | EXPLICIT | C | L8835–8848 (175→200→255) |
| L-08 | A single-day turnover spike of ~5–7x the average is "big" `[threshold: OURS]` | EXPLICIT (examples) | C | L8832 (175→1250) |
| L-09 | Turnover is always read together with the day's % move and candle quality | EXPLICIT | C | L9271 |
| L-10 | Low liquidity causes slippage that consumes tight stops | EXPLICIT | N | Lec 12, Lec 13 |

## V — Volume

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| V-01 | Expansion must show a **volume cluster** — several adjacent elevated bars | EXPLICIT | A | L996–1013 |
| V-02 | A **single tower of volume** (one elevated bar, isolated) is a disqualifier | EXPLICIT | A | L1000–1003, L7303–7312 |
| V-03 | Volume must be present **throughout** the expansion, not only at its end | EXPLICIT | A | L7312 "I need volumes all throughout" |
| V-04 | Volume **declining during contraction** is correct and expected | EXPLICIT | A | L1422 |
| V-05 | Volume **declining during a rising leg** is a warning | EXPLICIT | A | L12549 |
| V-06 | A signal candle on ~2x average volume is scan-worthy `[threshold: OURS]`; lookback unstated | DERIVED | A | Lec 4 "twice the average... which gets this in your scan" |
| V-07 | No average-volume formula or lookback is ever given | — | — | see `VOLUME_LIQUIDITY_SPEC.md` §1 |
| V-08 | "Blue / dark blue / navy blue" candles are a first-order selection criterion | UNKNOWN | N | L957, L4896, L9752 — **RG-01** |

## D — DNA

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| D-01 | Assess DNA **first**, before trend, stage or structure | EXPLICIT | C | Lec 6, Lec 9, Lec 11 |
| D-02 | DNA = typical single-candle % move **on the traded timeframe** | EXPLICIT | C | Lec 4, Lec 6 |
| D-03 | DNA also = typical full up-move % | EXPLICIT | C | Lec 11 |
| D-04 | Compute an up move by **summing positive candles**, not high-minus-low | EXPLICIT | C | Lec 11 |
| D-05 | Measure DNA only on genuine up moves, never inside a range | EXPLICIT | C | Lec 6 |
| D-06 | DNA includes **candle quality**: open near low, full body, small wicks | EXPLICIT | A | Lec 3, Lec 11 |
| D-07 | Profit target is set from DNA, not from a fixed R multiple | EXPLICIT | C | Lec 14 |
| D-08 | Exit as the higher-timeframe DNA is exhausted | EXPLICIT | C | Lec 6 |
| D-09 | Typical daily DNA 8–20%; weekly 15–30%; monthly 25–40% (per-stock, not universal) | DERIVED | C | Lec 4, 6, 9, 11, 14 |

## E — Event / EMA structure

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| E-01 | The MAs used are **10, 20, 50, 200**, referred to as EMAs | EXPLICIT | C | L1297 colour legend |
| E-02 | "Event on the LHS" is the **primary filter** | EXPLICIT | C | Lec 4 |
| E-03 | An event is a recent MA crossover: 10>20, 10>50, 20>50, or all four converging | EXPLICIT | C | Lec 7, Lec 11 |
| E-04 | The "small black dot" on his chart marks **EMA10 crossing above EMA20** | DERIVED | C | L9101–9105 |
| E-05 | All four EMAs (10/20/50/200) compressed at one price is the strongest configuration | EXPLICIT | C | Lec 7 |
| E-06 | An event is only valid if the configuration **survived the following contraction** | DERIVED | C | Lec 7 (area 1 vs area 2) |
| E-07 | EMA10 must be **clearly separated** from EMA20; intermingled = range = reject `[threshold: OURS]` | EXPLICIT | C | Lec 5, Lec 9 |
| E-08 | On the weekly: require 10>20 and 20>50, else skip the stock entirely | EXPLICIT | C | Lec 8 |
| E-09 | On the ETF, only 20-above-50 matters; ignore the 10 | EXPLICIT | C | Lec 1 |
| E-10 | Daily 10/20/50 dropping below the 200 signals a monthly-scale event — go look at the monthly | EXPLICIT | C | Lec 8 |
| E-11 | No fixed numeric gap between 20 and 50 is valid as a rule | EXPLICIT (negative) | — | Lec 7 |
| E-12 | "Every move towards 10 EMA is a buy" — **only** once 10 is above 20 with positive slope and a higher-low/higher-high structure | EXPLICIT | C | Lec 1 |

## X — Expansion

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| X-01 | Expansion candles: full body, open near low, minimal wick | EXPLICIT | A | Lec 3, 6, 11 |
| X-02 | Identify "the candle with which the expansion ended" — the contraction is measured against its high | EXPLICIT | C | Lec 4 |
| X-03 | **Weak expansion** (creeping up) is a disqualifier: the 10 EMA slope flattens and gives no support | EXPLICIT | A | Lec 1, Lec 4 |
| X-04 | A **weak high** (price drifting up rather than stopping and pushing through) is bad for momentum | EXPLICIT | A | Lec 10 |
| X-05 | Expansion quality sets the expectation for the contraction that follows | EXPLICIT | A | Lec 14 |
| X-06 | White candles interleaved in an otherwise "blue" expansion are a defect | UNKNOWN | N | L9745 — depends on RG-01 |

## K — Contraction

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| K-01 | **The whole contraction must stay within the high of the expansion-ending candle** — "one of the most important points I'll ever give you" | EXPLICIT | C | Lec 4 |
| K-02 | Contraction should sit in the **upper half** of that range (shallow, not deep) | EXPLICIT | C | Lec 4 |
| K-03 | Good contraction = small body, small range candles right at the 10 EMA | EXPLICIT | C | Lec 11 |
| K-04 | **VCC** = volatility contraction candle: small body forming at the MA, made possible by the signal candle closing near the MA | EXPLICIT | A | Lec 5 |
| K-05 | Contraction must be **proportionate in time** to the expansion (60% in 6 days is not resolved by 8 days) | EXPLICIT | A | Lec 10 |
| K-06 | Contraction must be **proportionate in depth** — this is relativity | EXPLICIT | A | Lec 1, Lec 7 |
| K-07 | A new contraction begins only once price exceeds the prior contraction's high by a meaningful margin (~4–5%, not <1%) `[threshold: OURS]` | EXPLICIT | C | Lec 12 |
| K-08 | Count contractions since the event; "second contraction post event" is favourable | EXPLICIT | C | Lec 11 |
| K-09 | Base 3 = extended; requires active management, smaller size | EXPLICIT | C | Lec 1 |
| K-10 | A contraction free of **lower circuits** is a positive sign | EXPLICIT | C | Lec 7 |
| K-11 | A red candle in the contraction **bigger than the expansion candles** is a serious defect | EXPLICIT | C | Lec 8, Lec 14 |
| K-12 | A contraction forming in the **lower half of the prior down move** is materially worse | EXPLICIT | C | Lec 10, Lec 13 |

## P — Pivot / demand

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| P-01 | **DC = Demand Candle** | EXPLICIT | — | L2117 |
| P-02 | The pivot is the **low of the demand candle**; the stop goes below it | EXPLICIT | C | Lec 10, Lec 11 |
| P-03 | **ILHS** = immediate left-hand side; every entry is judged against it | EXPLICIT | A | Lec 9 |
| P-04 | A large red candle must be **countered** — an up candle retracing ≥50%, ideally engulfing | EXPLICIT | C | Lec 9, 12, 13, 14 |
| P-05 | Candles hovering **below 50%** of a large red candle = selling pressure = do not buy | EXPLICIT | C | Lec 12 |
| P-06 | **No quality pivot → no definable stop → no sizeable position → skip the trade** | EXPLICIT | A | Lec 10 |
| P-07 | Pivot quality is the most common stated reason for rejection | EXPLICIT | A | Lec 10 (≈20 charts) |
| P-08 | A **large lower wick** stretches the demand zone and is a defect, not strength | EXPLICIT | C | Lec 5 |
| P-09 | Never place a stop **inside** a demand zone — it supplies liquidity to the market | EXPLICIT | C | Lec 5 |
| P-10 | The closer the pivot is to the MA, the better (tighter stop, shallower contraction) | EXPLICIT | C | Lec 5 |
| P-11 | Confluence of **daily 50 EMA + DC-up-move pivot** is the best add point | EXPLICIT | C | Lec 11 point 5 |
| P-12 | If no pivot is visible on the STF, drop to the ETF (1h → 15m → 5m) to find one | EXPLICIT | C | Lec 6, Lec 12 |

## M — MA proximity (lecture 5 framework)

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| M-01 | Case 2 — signal candle **opens near the MA and closes near the MA** — is the best | EXPLICIT | C | Lec 5 |
| M-02 | Opening near the MA creates a nearby pivot → tight stop | EXPLICIT | C | Lec 5 |
| M-03 | Opening far below the MA implies a deep contraction → MA slope turns down | EXPLICIT | C | Lec 5 |
| M-04 | Closing far above the MA means price must travel back, risking a bad red candle or MA-slope decay | EXPLICIT | C | Lec 5 |
| M-05 | Closing near the MA makes a VCC likely, because there is little room for volatility | EXPLICIT | C | Lec 5 |
| M-06 | Case 4 (far below → far above) creates a stretched demand zone; price often keeps falling later | EXPLICIT | C | Lec 5 |

## R — Relativity / extension

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| R-01 | Judge every move against what the stock has already done | EXPLICIT | C | Lec 1, 7, 11 |
| R-02 | After a large move, do **not** expect a shallow 10 EMA pullback — expect 20 or 50 `[threshold: OURS]` | EXPLICIT | C | Lec 1, Lec 7 |
| R-03 | Relativity governs **time** as well as depth | EXPLICIT | C | Lec 11 |
| R-04 | Extension is **timeframe-relative**: monthly-extended can still offer a clean daily setup | EXPLICIT | C | Lec 9 |
| R-05 | Extended stocks produce **snaps** — reversals larger than any the stock has previously shown | EXPLICIT | C | Lec 9 |
| R-06 | Trade extension with tighter management, not avoidance | EXPLICIT | C | Lec 9 |
| R-07 | In all-time highs there is no overhead reference; management must rely on pivots | EXPLICIT | C | Lec 11 |
| R-08 | Overhead high-volume areas are where a "push" should be expected | EXPLICIT | A | Lec 10 |

## N — Entry

Full sequence in `ENTRY_ENGINE.md`.

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| N-01 | Buy in **contraction**, never in momentum | EXPLICIT | C | Lec 6 |
| N-02 | Daily close above the 10 EMA puts a stock on the watchlist | EXPLICIT | C | Lec 1 |
| N-03 | Entry trigger: a candle takes **EMA10 above EMA20** and the configuration **holds** | EXPLICIT | C | Lec 11, Lec 14 |
| N-04 | Three entry types: (1) value buy in the demand zone, (2) repeat of the same zone, (3) certainty buy on the 10>20 cross | EXPLICIT | C | Lec 14 |
| N-05 | The certainty buy costs a higher price and is worth it | EXPLICIT | C | Lec 14 |
| N-06 | Never buy above the high of the bar as a rule in itself | EXPLICIT (negative) | C | Lec 7 |
| N-07 | Do not enter in anticipation of earnings | EXPLICIT | C | Lec 12 |
| N-08 | If not at your price, skip — chasing has negative expected value over 100 trades | EXPLICIT | C | Lec 12 |
| N-09 | Momentum days are poor add points (low liquidity in the first 15–30 min) | CONFLICTING — see RG-04 | C | L9273–9277 |

## S — Risk / stop

Full treatment in `RISK_ENGINE.md`.

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| S-01 | The stop goes **below a structural pivot**, never at a round number or an arbitrary MA | EXPLICIT | C | Lec 11 |
| S-02 | Stop width must be **proportionate to DNA** — a 17–20% stop is wrong when monthly DNA is 25–30% | EXPLICIT | C | Lec 4 |
| S-03 | Switching to a lower timeframe to find a nearer pivot is the correct way to tighten a stop | EXPLICIT | C | Lec 4, Lec 12 |
| S-04 | **Expectational stop** (1.5–2%) is permissible when no structural pivot exists and the thesis is pure momentum | EXPLICIT | C | Lec 12 |
| S-05 | Prefer a structural 3% stop over an expectational 2% when the difference is small | EXPLICIT | C | Lec 12 |
| S-06 | **Never use a 1% stop** — slippage consumes it | EXPLICIT | C | Lec 12 |
| S-07 | Position size is determined by stop width | EXPLICIT | C | Lec 10 |
| S-08 | Starting size is 35–40% of capital; best setups 60–80% | EXPLICIT | C | Lec 14, Lec 4 |
| S-09 | Reject "pilot"/"test" positions — a 20% gain on 15% size is not worth the slot | EXPLICIT | C | Lec 10 |
| S-10 | Size **down** for higher-timeframe (monthly-scale) trades | EXPLICIT | C | Lec 8 |
| S-11 | Once up ~7%, move the stop to near breakeven | EXPLICIT | C | Lec 14 |
| S-12 | Do not ratchet the stop upward on every green day | EXPLICIT (negative) | C | Lec 13 |

## O — Exit

Full sequence in `EXIT_ENGINE.md`.

| ID | Rule | Class | Comp | Evidence |
|---|---|---|---|---|
| O-01 | While above the 10 EMA, do nothing. A touch of the 10 EMA is when you look. | EXPLICIT | C | Lec 14 |
| O-02 | A decisive **close below the 10 EMA** is the full exit trigger | EXPLICIT | C | Lec 11 |
| O-03 | The first candle that **completely eats the expansion candle** and is the biggest down candle of the move = sell signal | EXPLICIT | C | Lec 8 |
| O-04 | Sell a large tranche (50–80%) into the first strong expansion, keep the remainder for the higher timeframe | EXPLICIT | C | Lec 11 (76%), Lec 14 (74%) |
| O-05 | As gains accumulate, tighten from EMA-based to **pivot-based** trailing | EXPLICIT | C | Lec 9, Lec 14 |
| O-06 | At resistance, do not sell blindly — sell on an **ETF pivot break** | EXPLICIT | C | Lec 6, Lec 10 |
| O-07 | Exit as the higher-timeframe DNA target is reached | EXPLICIT | C | Lec 6 |
| O-08 | **Lower circuits → exit the entire position** | EXPLICIT | C | Lec 14 |
| O-09 | Declining volume on a rising leg → become cautious | EXPLICIT | A | Lec 14 |
| O-10 | Let the stock give the sell signal; do not predict | EXPLICIT | C | Lec 8 |
| O-11 | Freed capital should be redeployed into better setups — opportunity cost is an exit reason | EXPLICIT | C | Lec 11, Lec 14 |

## G — Governance (author's explicit refusals)

| ID | Rule | Class | Evidence |
|---|---|---|---|
| G-01 | Do not convert an observation into a formula | EXPLICIT | Lec 4, Lec 7 |
| G-02 | Context beats pattern — a "bad candle" may be correct in context | EXPLICIT | Lec 7 |
| G-03 | No market-regime labelling; markets are neutral | EXPLICIT | Lec 13 |
| G-04 | Win rate matters; STT is non-deductible, so high-frequency low-win-rate strategies lose after charges | EXPLICIT | Lec 13 |
| G-05 | "Left" (declined on quality) vs "missed" (process failure) are different and must be tracked separately | EXPLICIT | Lec 13 |
| G-06 | Opportunity cost is a first-class rejection reason | EXPLICIT | Lec 10 |

---

## Contradictions found

| ID | Description | Resolution |
|---|---|---|
| **RG-04** | Lec 11 L9273–9277: "I don't like to add on these days. These are momentum days... So, for me these are the perfect day to add on to a stock." | Almost certainly a transcription error for "*not* the perfect day". Every other lecture rejects chasing momentum. **Treat momentum days as NOT add points.** |
| **RG-05** | G-01 ("do not make it a formula") is in direct tension with the master prompt's requirement to build a deterministic engine. | Unavoidable. Resolve by keeping deterministic gates for EXPLICIT computable rules and treating all quality judgements as **approximations that must be validated**, per Section 41. Never present an approximation as the author's rule. |

## Unknowns

| ID | Description | Impact |
|---|---|---|
| **RG-01** | The blue/dark-blue/navy-blue candle overlay is never defined | **High** — a first-order selection criterion we cannot reproduce |
| **RG-02** | No numeric threshold is given for: turnover floor, volume elevation multiple, EMA10/20 minimum separation, contraction depth limits, relativity boundaries | **High** — every gate needs a fitted parameter |
| **RG-03** | "Candle quality" is never quantified | **Medium** — approximable by body/range, unvalidated |
| **RG-06** | Whether the MAs are exponential or simple is never stated outright; "EMA" is the dominant term but "moving average" is used interchangeably | **Low** — test both |
