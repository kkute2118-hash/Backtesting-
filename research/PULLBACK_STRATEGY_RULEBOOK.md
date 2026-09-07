# Deliverable 1 — Complete Strategy Rulebook

**Source:** transcript of *"969% Return in 1 Year: The Winning Pullback Strategy of a
Trading Champion"* — an interview with Martin Luk (US Investing Championship 2025,
+969%; 2024, +280%), hosted by Richard Moglen.

**Transcript facts you should know before reading anything below.**

* The transcript is entirely in English. There is no Hindi/Hinglish content in it.
* Its final timestamp is `248:60`, i.e. it is a **~4 hour 10 minute** interview, not
  a 16-hour course. Roughly 39,000 words of spoken content survive de-duplication.
* The speaker trades **US equities** (and US leveraged ETFs), intraday-timed and
  held for days, from Hong Kong. Almost every example is a US ticker.
* It is an **interview**, not a course. The speaker repeatedly says he has no
  strict rules on the sell side, adjusts anchors "by feel", and took trades he
  cannot justify afterwards. That is not a defect of the extraction below — it is
  the material.

Legend for every rule:

| Field | Meaning |
| --- | --- |
| **Objective?** | `OBJ` fully mechanical · `SEMI` mechanical once a threshold is chosen · `DISC` requires human judgement |
| **Testable here?** | `YES` · `PROXY` (approximated, with the approximation named) · `NO` (data missing) |

---

## 0. Context the speaker gives about his own record (not rules)

| ID | Statement | Timestamp | Why it matters |
| --- | --- | --- | --- |
| CTX-1 | 209 winning trades vs 731 losing trades in 2025 (~940 trades, ~22% win rate) | 20:36, 24:31 | The strategy is explicitly a low-win-rate, high-payoff system. Any backtest that produces a 50% win rate has not reproduced it. |
| CTX-2 | Traded far more in 2025 than 2024 because pullbacks generate more entries than breakouts | 22:40 | Signal frequency is expected to be high. |
| CTX-3 | 26% drawdown in December 2025 alone, after a strong 11 months | 46:37 | The record is not smooth; the worst month was caused by behaviour, not by the setup. |
| CTX-4 | ~46% of December trades were, by his own judgement, trades he should not have taken | 49:06 | Roughly half the trade log in a bad month does not follow the rules below. |
| CTX-5 | Prior history: 50% drawdown in 2021, breakeven 2022, recovery mid-2023 | 07:01–11:08 | The +969% year follows several unremarkable ones. |
| CTX-6 | 2025 P&L split: ~80–85% from longs, ~10–15% from shorts (including December losses) | 29:16 | The long side is the strategy. Shorts are a small, self-criticised sleeve. |

> **INSUFFICIENT INFORMATION — DO NOT ASSUME.** No trade log, no per-setup statistics,
> no equity curve data, and no dates for most trades are given. Every number above is
> the speaker's spoken recollection. None of it is independently verifiable.

---

## 1. Market-condition rules

| ID | Rule | Timestamp | Meaning | Rationale given | Objective? | Testable here? | Data needed | Ambiguity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M-1 | Watch QQQ and IWM every day to judge the general market | 227:19, 231:31 | Index trend is the top-down gate | "Most individual stocks follow the indices" | SEMI | PROXY | Index OHLC — **absent**; replaced by an equal-weighted index built from the 500 constituents | "Watch" is not a rule; the trading consequence is left implicit |
| M-2 | Be aggressive when the index **pulls back to a rising 9/21 EMA**, not when it is extended | 228:12, 230:40 | Add risk on index pullbacks | Best reward-for-risk on new entries | SEMI | PROXY | Index EMAs | "Extended" is never quantified |
| M-3 | When market breadth is declining, **trade less** | 55:23 | Reduce activity, not necessarily stop | Choppy markets punish tight stops | SEMI | PROXY | Breadth — reconstructed as % of universe above its 50 EMA | "Less" is not a number |
| M-4 | In a **choppy** market, trade less; expect little follow-through | 53:39, 141:08 | Chop is the identified enemy | Stops get hit both ways | DISC | PROXY | — | "Choppy" is only defined after the fact |
| M-5 | Do not short while the index is above its 50 EMA (open question he wants to study) | 237:54 | Candidate short veto | His December shorts failed with QQQ above the 50 EMA | OBJ | PROXY | Index EMA50 | He states it as an unresolved hypothesis, not a rule |
| M-6 | If IWM (small caps) is leading, the probability of a >15% index correction is low | 238:50 | Reduce short exposure when small caps lead | His own 20-year study: post-2008, no 15% QQQ drawdown began with IWM leading | OBJ | **NO** | Two index series with distinct constituents | Self-reported study; sample size unstated |
| M-7 | Market **feedback from your own open positions** is the primary regime signal | 227:19 | If new positions work, press; if they fail, cut back | Faster than any indicator | DISC | **NO** | Requires a live book | Cannot be a scanner rule; it is a portfolio-state rule |
| M-8 | Track the count of names on the "leading" vs "lagging" watchlist as a breadth read | 230:40 | Manual breadth | — | DISC | **NO** | Requires his watchlists | — |

---

## 2. Stock-eligibility rules

| ID | Rule | Timestamp | Meaning | Rationale given | Objective? | Testable here? | Data needed | Ambiguity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| U-1 | Trade **fast-moving (high ADR) stocks only** | 18:50 | Volatility is required for the payoff | Tight stop + fast stock ⇒ better reward-for-risk | SEMI | YES | Daily H/L → ADR20 | No ADR threshold is given |
| U-2 | Trade names inside a **hot theme/sector**; several names in one industry moving together | 150:41, 151:30 | Theme confirmation | Themes carry the biggest moves | SEMI | **NO** | Sector/industry mapping — **absent from the candle store** | — |
| U-3 | Among names in the same theme, prefer the one with the highest **relative strength** | 196:34 | Leadership ranking | Leaders move first and furthest | SEMI | PROXY | Cross-sectional return rank (63-day used here) | Lookback never specified |
| U-4 | Next tiebreak: the **tighter recent price action** (inside bar, smaller candles) | 197:28 | Prefer tight consolidation | Lower entry risk | OBJ | YES | Daily OHLC | Which bars count is unstated |
| U-5 | Next tiebreak: the highest **dollar volume** (not share volume) | 198:22 | Liquidity | Less slippage, better follow-through | OBJ | YES | close × volume | No floor is given |
| U-6 | Reduce size on small/micro caps because of gap-down risk | 16:21 | Position-size adjustment, not exclusion | Short reports, 10–30% gaps | SEMI | PROXY | Market cap — **absent**; turnover used as a stand-in | — |
| U-7 | Candidates come from pre-market gap scans, prior-day-gainer scans and manually-graded watchlists | 150:41, 232:19 | Discovery process | — | DISC | **NO** | Pre-market quotes — **absent** | The scans themselves are not specified in this video |

---

## 3. Trend / structure rules (the "is this stock in a state I will buy" test)

| ID | Rule | Timestamp | Meaning | Objective? | Testable here? | Ambiguity |
| --- | --- | --- | --- | --- | --- | --- |
| T-1 | Indicators used: **EMA 9, 21, 50 and 150**, on all timeframes | 25:18, 30:03 | The only moving averages in the system | OBJ | YES | — |
| T-2 | Buy pullbacks where the **9 EMA is above the 21 EMA and the two are close together** | 84:01 | Near-term uptrend, coiled | OBJ | YES | "Close together" unquantified |
| T-3 | The EMAs must be **rising**, not flat or declining | 84:59, 122:05 | Trend must exist | SEMI | YES | Slope window unstated |
| T-4 | The 150 EMA is treated as a major support ("the great EMA") | 77:40, 170:15 | Long-term trend line | OBJ | YES | — |
| T-5 | Price should be **above the anchored VWAP**; basing below it is not a buy zone | 90:17, 122:05 | AVWAP as the bull/bear line of the base | OBJ | PROXY | Anchor choice is discretionary — see AMBIG-1 |
| T-6 | The base should show **higher lows** | 124:27, 154:06 | Constructive base | OBJ | YES | How many lows, over what window |
| T-7 | Check the **weekly** chart: weekly 9/21 EMA and weekly closes | 92:02, 97:19 | Higher-timeframe veto | OBJ | YES | — |
| T-8 | **Never short a stock whose weekly is still above its 9 EMA** — stated as a lesson learned from a loss | 96:24, 127:56 | Weekly veto for shorts | OBJ | YES | — |
| T-9 | A weekly **pin bar / inside week** after a base is a strong tell | 186:31 | Weekly compression | OBJ | YES | — |
| T-10 | A prior **strong wide green bar closing above the 50 EMA** is the character change that puts a name on the radar | 83:14 | Change-of-character trigger for watching | SEMI | YES | "Strong" unquantified (he cites one ~8% bar) |

---

## 4. Setup rules — the pullback buy (the core of the video)

| ID | Rule | Timestamp | Meaning | Rationale | Objective? | Testable here? | Ambiguity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P-1 | Buy a **pullback into support**, not a breakout, when the market is rewarding pullbacks | 13:26, 27:06 | Setup selection is regime-dependent | Breakouts were shaking him out in 2024–25 | DISC | PROXY | "Rewarding" is judged in hindsight |
| P-2 | Valid support levels: **9 EMA, 21 EMA, 50 EMA, 150 EMA, anchored VWAP, prior swing highs (break-and-retest), unfilled gaps** | 59:36, 100:09, 187:40 | The level menu | Places other traders also buy | OBJ | YES | Touch tolerance never specified |
| P-3 | **Confluence is the edge**: the more of those levels that line up at one price, the higher the probability | 67:04–70:32 | Central claim of the video | "Highest probability point that the stock will find support" | OBJ | YES | "Line up" tolerance unspecified |
| P-4 | Prefer the **first pullback** into support after a base breakout ("break and retest") | 77:40, 124:27 | Freshness of the setup | First test is cleanest | SEMI | YES | "First" needs a counter |
| P-5 | The stock should **touch the level and reverse quickly** — a V-shaped recovery, not a slow grind | 86:51, 101:36 | Demand must be immediate | "The faster it rebounds, the stronger the stock" | SEMI | PROXY | Intraday shape is invisible on daily bars; approximated by close position in the daily range |
| P-6 | Prefer stocks that **gap up or open higher, get slammed into support, then recover** | 01:26, 57:43 | The specific intraday pattern he trades | Very common in 2025 | OBJ | **NO** | Needs intraday bars |
| P-7 | An **undercut-and-reclaim** of the 9/21 EMA (or prior day's low) is a valid pullback | 89:29, 204:35 | Shakeout then reclaim | — | OBJ | YES | — |
| P-8 | Do **not** buy a pullback "in the middle of nowhere" — the pattern must be mature | 65:31, 113:27 | Anti-randomness rule | His own losers came from this | DISC | PROXY | "Mature" is undefined; approximated by the base/higher-low/fresh-leg tests |
| P-9 | A pullback to the **daily 9 EMA has the lowest win rate**; pullbacks to slower EMAs (21/50) have higher win rates | 199:15 | Depth preference | "From my study" | OBJ | YES | His study is not shown; direction is testable |
| P-10 | Pullback entries are preferred because they give a **tighter stop** and avoid chasing | 60:37, 61:32 | Why pullbacks over breakouts | — | OBJ | YES | — |

### The other three setups (named, not detailed)

| ID | Setup | Timestamp | Status |
| --- | --- | --- | --- |
| P-11 | **Breakout** buys — previous day/week high, inside-bar breakouts, VCP-ish handles | 13:26, 172:55, 209:40 | Described by example only; no explicit entry rule set. Traded throughout 2025. |
| P-12 | **EP / episodic pivot** — gap up on news out of a base | 13:26, 180:53 | Named, never defined in this video. **INSUFFICIENT INFORMATION — DO NOT ASSUME.** |
| P-13 | **Parabolic long/short** — buying capitulation (e.g. index 20% below the hourly EMA after three gap-down days) or shorting a vertical top | 156:26, 213:21 | One example each. The threshold ("20% below the 1-hour EMA", "15% below the daily 9 EMA") is intraday and index-specific. |

---

## 5. Confirmation / entry-trigger rules

| ID | Rule | Timestamp | Meaning | Objective? | Testable here? | Ambiguity |
| --- | --- | --- | --- | --- | --- | --- |
| C-1 | Wait for the flush into support, then buy the **breakout of the previous bar's high** on an intraday chart | 116:55, 118:37 | The actual trigger | OBJ | PROXY | On daily data this becomes "next day trades above today's high" |
| C-2 | Timeframe of that trigger: **1-minute** bar in the first 15 minutes; **5-minute** bar from 15–60 minutes | 117:47 | Trigger granularity changes with time of day | OBJ | **NO** | Requires intraday data |
| C-3 | Opening-range-high breakouts are an acceptable trigger, including the 1-minute opening range | 150:02, 158:19 | Alternative trigger | OBJ | **NO** | Requires intraday data |
| C-4 | The stock must react **in the first 30–60 minutes** — he cannot trade late-day recoveries (time-zone constraint) | 86:51, 101:36 | Time-of-day filter | OBJ | **NO** | Requires intraday data |
| C-5 | If the first trigger fails, a later, larger-timeframe trigger the same day is acceptable (5-min then 15-min) | 123:40, 200:54 | Intraday re-entry | OBJ | **NO** | Requires intraday data |

> **This is the single largest translation loss in the whole exercise.** Rules C-2
> through C-5 — and P-5, P-6 — are all intraday, and the supplied data is daily.
> Everything measured in Deliverable 2 uses C-1 in its daily form.

---

## 6. Stop-loss rules

| ID | Rule | Timestamp | Meaning | Objective? | Testable here? | Ambiguity |
| --- | --- | --- | --- | --- | --- | --- |
| R-1 | Default stop = **low of day** (used ~60–70% of the time) | 19:54, 118:37 | Primary stop | OBJ | PROXY | On daily bars, the setup bar's low |
| R-2 | If that is too wide: stop = **low of the breakout candle**, or of the previous candle | 118:37, 131:41 | Tightening alternative | OBJ | **NO** | The alternative candles are intraday |
| R-3 | Occasionally: stop at the **day's opening price** | 179:02 | Third variant | OBJ | **NO** | Intraday |
| R-4 | Hard rule: stop must be **< 50% of the stock's ADR**, and **≤ 5%** in all cases | 18:17 | The only numeric risk ceiling stated | OBJ | YES | ADR period unstated (ADR20 used) |
| R-5 | In practice he rarely exceeds **3%**, and targets **≤ 2.5%**, often 1.0–1.5% | 18:17, 30:44, 33:29 | Practical band | OBJ | YES | Preference, not a rule |
| R-6 | The stop is **always set before entry** — even on trades that break his other rules | 220:39 | Non-negotiable | OBJ | YES | — |
| R-7 | Fully respect the stop; ignoring stops was the 2024 mistake he removed in 2025 | 23:33 | Discipline rule | DISC | n/a | — |
| R-8 | When trailing with the 9 EMA and unable to watch the close, place the stop **slightly below the 9 EMA / below the candle low**, leaving room for an undercut | 173:50, 203:46 | Trailing stop placement | OBJ | YES | "Slightly" unquantified |

---

## 7. Target, exit and trade-management rules

| ID | Rule | Timestamp | Meaning | Objective? | Testable here? | Ambiguity |
| --- | --- | --- | --- | --- | --- | --- |
| X-1 | **There is no strict sell rule.** Stated twice, explicitly | 01:26, 147:32 | The exit is discretionary by admission | DISC | — | This is the honest headline of the exit section |
| X-2 | Sell **partials into strength when up 3R or 5R** | 01:26, 147:32 | The only numeric profit rule | OBJ | YES | Which R first, and how often, is not fixed |
| X-3 | Each trim is about **15%** of the position (first trim 15–20%) | 148:24, 176:20 | Trim size | OBJ | YES | — |
| X-4 | Alternatively sell when the stock is **extended on the lower timeframe** (especially hourly) | 147:32 | Discretionary trim trigger | DISC | **NO** | "Extended" undefined; needs hourly bars |
| X-5 | Close the remaining position on the **first daily close below the 9 EMA** | 149:15, 171:55 | The trailing exit | OBJ | YES | **When it arms is not stated** — see AMBIG-3 |
| X-6 | Alternatively trail the whole position with the 9 EMA and take no partials, when the market is strong and other positions carry cushion | 01:26, 177:09 | Regime-dependent exit | DISC | PROXY | Condition is subjective |
| X-7 | Take partials **more** aggressively early in a campaign (starting from cash), **less** when the book is working | 176:20 | Exit depends on portfolio state | DISC | **NO** | — |
| X-8 | **Shorts**: take profits within the first **2–3 days**, close into weakness | 216:12, 217:05 | Shorts are time-boxed | OBJ | YES | — |
| X-9 | Rationale for X-8: a short's payoff is mathematically capped (−50% then −50% = +75% short vs +125% long) | 217:52 | Why shorts get less rope | — | — | Arithmetic is correct |
| X-10 | He admits he sells winners too early and wants to hold longer | 167:23, 210:31 | Self-identified weakness | DISC | — | Means the coded exit may *understate* the real system's upside |

---

## 8. Position sizing and portfolio rules

| ID | Rule | Timestamp | Formula / value | Objective? | Testable here? |
| --- | --- | --- | --- | --- | --- |
| Z-1 | Risk per trade ≈ **0.5% of portfolio** | 15:27 | `risk = 0.005 × equity` | OBJ | YES |
| Z-2 | Risk **less** when trades aren't working, **more** (up to 6–8%) with conviction or a profit cushion | 16:21, 34:22, 225:04 | Variable risk | DISC | PROXY |
| Z-3 | Size = risk ÷ stop distance | 183:25 | `shares = 0.005 × equity ÷ (entry − stop)` | OBJ | YES |
| Z-4 | Typical resulting position: **20–30%** of portfolio; ~20% for small caps; >35% only for slow names (commodity/index ETFs) | 16:21, 17:18, 34:22 | Size band | OBJ | YES |
| Z-5 | No explicit margin cap; peak observed **280% long** | 41:02, 43:08 | "Limit risk per trade and the margin handles itself" | OBJ | YES (as a leverage parameter) |
| Z-6 | Normally **3–4 positions**; 6–7 when the book is trending; maximum observed 11 | 43:56 | Concurrency band | OBJ | YES |
| Z-7 | Enters ~3–4 new positions on a good day, then pyramids on the next pullback day | 44:53 | Entry cadence | OBJ | YES |
| Z-8 | Think in **percentages, never dollars**; scale size up as the account grows | 185:43 | Compounding rule | OBJ | YES |

---

## 9. No-trade conditions and invalidations

| ID | Rule | Timestamp | Objective? | Testable here? |
| --- | --- | --- | --- | --- |
| N-1 | Do not chase: if price is **more than 3% above the low of day**, skip the entry | 24:31 | OBJ | **NO** (intraday); partially subsumed by R-4/R-5 |
| N-2 | Do not buy a pullback that is **extended** — far from the 9 EMA, after several weeks of advance, with no consolidation | 113:27, 129:45 | SEMI | PROXY |
| N-3 | Do not buy a pullback on a stock in a **strong downtrend** (declining 21/50 EMA, below AVWAP, no higher lows) | 122:05 | OBJ | YES |
| N-4 | Do not buy when the previous day closed **below all EMAs** / very weak | 135:46 | OBJ | YES |
| N-5 | Do not short only because the daily 9/21 EMA broke, if the **weekly is still constructive** | 97:19, 127:56 | OBJ | YES |
| N-6 | Do not short into an uptrending market — his shorts were "too aggressive on an uptrending market" | 223:20 | SEMI | PROXY |
| N-7 | Do not enter on an **hourly-only** signal (e.g. hourly 21 EMA) when the daily 9 EMA is far away | 50:03, 129:45 | OBJ | PROXY |
| N-8 | Do not flip between long and short in a chopping market | 51:05, 133:24 | DISC | **NO** |
| N-9 | Do not trade to recover losses (revenge / "behavioural slippage") | 51:05, 135:46, 242:25 | DISC | **NO** |
| N-10 | Do not size up when the market is extended after a multi-month run | 114:24, 174:42 | DISC | PROXY |
| N-11 | Do not take shorts when the reward-for-risk is small (e.g. weekly support just below) | 127:56 | SEMI | PROXY |

---

## 10. Re-entry rules

| ID | Rule | Timestamp | Objective? | Testable here? |
| --- | --- | --- | --- | --- |
| RE-1 | Re-entry after a stop-out is explicitly permitted and used — IONQ was tried three times before it worked | 187:29 | OBJ | YES |
| RE-2 | Same-day intraday re-entry on a higher timeframe trigger after a stop-out | 123:40 | OBJ | **NO** (intraday) |
| RE-3 | Getting stopped out and watching the stock go without you is normal and must not change behaviour | 241:34 | DISC | — |
| RE-4 | No stated limit on re-entries per name | — | — | **INSUFFICIENT INFORMATION — DO NOT ASSUME** |

---

## 11. Discretionary and psychological rules (explicitly NOT codable)

| ID | Rule | Timestamp | Why it cannot be coded |
| --- | --- | --- | --- |
| D-1 | Anchored-VWAP anchor selection: place it at the swing high/low of a base, a large gap, or a high-volume reversal bar — **then move it until the price respects it most** | 71:28, 80:15, 103:27, 105:05 | Fitting the anchor to the reactions it produces is curve-fitting by hand. Any deterministic anchor is a *different* indicator. |
| D-2 | "What would a great trader do?" as a pre-trade filter | 244:06 | — |
| D-3 | Trade less when mentally depleted; recognise behavioural slippage | 39:34, 51:56 | Requires trader state |
| D-4 | Upgrade/downgrade names between watchlists by feel | 152:19 | Requires his watchlists |
| D-5 | Judging whether the market "rewards pullbacks or breakouts" this season | 27:06, 63:23 | Judged in hindsight |
| D-6 | Selling into strength "when it feels extended" | 147:32, 174:42 | Explicitly not a rule |
| D-7 | Copy a mentor early, then adapt the system to your own personality | 36:22 | Meta-advice |

---

## 12. Recorded ambiguities that materially change a backtest

| ID | Ambiguity | Readings | How Deliverable 2 handles it |
| --- | --- | --- | --- |
| AMBIG-1 | Anchored VWAP anchor | (a) latest swing high of the base; (b) any large gap/volume bar; (c) whichever anchor "works best" (D-1) | Reading (a), made deterministic: the highest high of the trailing 60 bars. Reading (c) is untestable by construction. |
| AMBIG-2 | Stop width rule R-4 vs R-1 | "Low of day" and "≤50% of ADR" are compatible intraday, **contradictory on daily bars** — a daily bar's low-to-high span *is* roughly one ADR | Both readings run and reported: **A (literal)** applies both caps; **B** applies only the ≤5% ceiling |
| AMBIG-3 | When the 9-EMA exit arms | (a) from entry; (b) once the trade is in profit; (c) only after partials | All three tested; (a) is the literal reading and is the headline |
| AMBIG-4 | "Confluence" tolerance | How close two levels must be to count as lined up | Each level tested independently; confluence = count of levels touched on the same bar |
| AMBIG-5 | Relative-strength lookback | Never stated | 63 trading days, with 21/126-day variants in sensitivity |
| AMBIG-6 | "Fast-moving stock" threshold | No ADR number given | ADR20 ≥ 2.0% baseline, swept 0–4% |
| AMBIG-7 | Partial order (3R first or 5R first) and whether both always happen | Unstated | 15% at +3R, 15% at +5R; geometry swept |
| AMBIG-8 | Breadth / "trade less" | No threshold, and "less" is not "none" | Breadth ≥ 40% of universe above 50 EMA, swept 0–50% |

---

## 13. What the video contains that this dataset cannot test at all

| Rule | Missing data |
| --- | --- |
| C-2…C-5, P-5, P-6, N-1, R-2, R-3, RE-2 | Intraday (1/5/15/60-minute) bars |
| M-1, M-2, M-5, M-6 in their true form | QQQ, IWM, or any real index series |
| U-2 (theme/sector) | Sector or industry classification |
| U-6 (small-cap size adjustment) | Market capitalisation |
| P-12 (episodic pivots) | News/earnings dates — and the rule itself is undefined in this video |
| M-7, D-1…D-7, N-8, N-9, X-4, X-7 | Not a data problem: these are discretionary by nature |

---

## 14. The strategy as a decision tree (Phase 2 reconstruction)

Long side, daily-bar reading. Each line cites the rule it comes from.

```
A. MARKET ELIGIBILITY  (evaluated on the close of day t)
   A1  index_close > index_EMA50                                  [M-1, M-5]
   A2  index_EMA21 rising over 5 bars                             [M-2]
   A3  breadth (% of universe > own EMA50) >= 40%                 [M-3]
   -> if any fails: NO NEW LONGS today

B. STOCK ELIGIBILITY  (day t)
   B1  median 20-day turnover >= INR 5 crore                      [U-5, U-1]
   B2  ADR20 >= 2.0%                                              [U-1]
   B3  EMA9 > EMA21 > EMA50  AND  EMA21 rising                    [T-2, T-3]
   B4  close > EMA150                                             [T-4]
   B5  weekly EMA9 > weekly EMA21  AND  weekly close > weekly EMA9 [T-7, T-8]
   B6  63-day return rank >= 70th percentile of universe          [U-3]
   B7  a 20-day high occurred within the last 15 bars             [P-4]
   B8  last confirmed swing low > previous confirmed swing low    [T-6]

C. SETUP DETECTION  (day t)
   C1  the bar's low reaches within 0.5% of at least one of:
         EMA9, EMA21, EMA50, EMA150, anchored VWAP,
         a prior swing high now below price, an unfilled gap base [P-2, P-3]
   C2  the bar's close holds within 0.5% above that level         [P-7]
   C3  close in the upper half of the bar's range                 [P-5]
   C4  the bar's low is at least 1 ATR below the 20-day high      [P-8]
   confluence = how many of the seven levels C1 matched           [P-3]

D. CONFIRMATION / ENTRY  (day t+1 only)
   D1  trigger price = high of day t                              [C-1]
   D2  the trade activates the moment day t+1 trades >= trigger
   D3  fill = max(open(t+1), trigger) + 5 bp slippage
   D4  reject if (fill - stop)/fill > min(5%, 0.5 x ADR20)        [R-4]

E. STOP
   E1  stop = low of day t                                        [R-1]
   E2  a gap below the stop fills at the open, not at the stop

F. TARGET
   F1  none. There is no price target in this system.             [X-1]

G. TRADE MANAGEMENT
   G1  sell 15% of the position at +3R                            [X-2, X-3]
   G2  sell 15% of the position at +5R                            [X-2, X-3]
   G3  close everything on the first daily close below EMA9       [X-5]

H. EXITS (complete list)
   H1  stop hit                                                   [R-1]
   H2  first close below the 9 EMA                                [X-5]
   H3  position fully consumed by partials
   H4  end of the test window (forced, reported separately)

I. NO-TRADE
   I1  any of A1-A3 false                                         [M-3, M-5]
   I2  any of B1-B8 false                                         [N-2..N-4, N-7]
   I3  required stop wider than the R-4 cap                       [R-4]
   I4  already holding the same symbol                            [implicit]
   I5  book already at 8 positions or 4 new entries today         [Z-6, Z-7]
   I6  gross exposure would exceed the leverage cap               [Z-5]

J. POSITION SIZE
   J1  shares = floor( 0.005 x equity(t) / (fill - stop) )        [Z-1, Z-3]
   J2  capped at 30% of equity                                    [Z-4]
   J3  capped by remaining cash / leverage budget                 [Z-5]

K. RE-ENTRY
   K1  permitted without limit once the position is closed        [RE-1]
   K2  the symbol must produce a fresh setup (C) and trigger (D)
```

Short side (reported separately, see Deliverable 2 §7): the exact mirror, plus
`max holding 3 bars` [X-8] and the weekly veto [T-8] applied in reverse.
