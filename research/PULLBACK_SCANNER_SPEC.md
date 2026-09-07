# Deliverable 4 — Scanner Implementation Specification

Phases 8, 9, 10 and 11.

This document is developer-ready: everything in §4–§12 is deterministic and can
be implemented without watching the interview. §2 is the engineering decision
that must be read first, because it governs whether any of it should be switched
on.

---

## 1. Phase 8 — codability classification of every rule

### 1. FULLY CODABLE — objective, computable from the existing candle store

| Rule | Formula |
| --- | --- |
| T-1, T-2, T-3 | `EMA9 > EMA21 > EMA50`, `EMA21[t] > EMA21[t−5]` |
| T-4 | `close > EMA150` |
| T-6 | last confirmed swing low > previous confirmed swing low (3-bar fractals, published 3 bars late) |
| T-7, T-8 | weekly `EMA9 > EMA21` and `close > EMA9`, computed from **completed weeks only** |
| U-1 | `ADR20 = mean(high/low − 1) × 100` |
| U-4 | inside bar / range contraction over the last N bars |
| U-5 | `median(close × volume, 20)` |
| P-2 | touch of EMA9 / EMA21 / EMA50 / EMA150 / anchored VWAP / prior swing high / unfilled gap base |
| P-3 | confluence = count of levels touched on the same bar |
| P-5 (daily proxy) | `(close − low) / (high − low) ≥ 0.5` |
| P-7 | undercut-and-reclaim: `low < level` and `close ≥ level` |
| C-1 (daily proxy) | next session trades above this session's high |
| R-1 (daily proxy) | stop = setup bar's low |
| R-4 | `stop% ≤ min(5, 0.5 × ADR20)` |
| X-2, X-3 | partial at +3R and +5R, 15% each |
| X-5 | first daily close below the 9 EMA |
| X-8 | shorts: 3-bar time exit |
| Z-1, Z-3, Z-4, Z-6, Z-7 | `shares = 0.005 × equity / (entry − stop)`, capped at 30% of equity, ≤8 open, ≤4 new/day |
| RE-1 | re-entry allowed on a fresh setup |

### 2. PARTIALLY CODABLE — mechanical only after choosing a number the video never gives

| Rule | What is missing | Value used here |
| --- | --- | --- |
| U-1 "fast-moving" | no ADR threshold | ADR20 ≥ 2.0% |
| U-3 relative strength | no lookback, no cutoff | 63-day return, ≥70th percentile |
| U-5 liquidity | no floor | median 20-day turnover ≥ ₹5 crore |
| M-1, M-2 index trend | no index specified for India; "extended" undefined | proxy index > 50 EMA, 21 EMA rising |
| M-3 breadth | "trade less", not "stop" | ≥40% of universe above its own 50 EMA |
| P-2 touch | no tolerance | 0.5% either side |
| P-8 "not extended / mature pattern" | undefined | dip ≥ 1 ATR below the 20-day high, 20-day high within 15 bars |
| T-5 anchored VWAP | anchor is chosen by eye (D-1) | highest high of the trailing 60 bars |
| Z-2 variable risk | "more with conviction" | fixed 0.5% |

### 3. NOT CODABLE WITH CURRENT DATA — required data absent

| Rule | Missing data |
| --- | --- |
| C-2, C-3, C-4, C-5 — intraday trigger, 1/5-min bars, first 30–60 min timing | intraday bars |
| P-5, P-6 — V-shaped recovery, gap-up-then-flush | intraday bars |
| N-1 — no-chase, >3% above the low of day | intraday bars |
| R-2, R-3 — stop at breakout-candle low or opening price | intraday bars |
| RE-2 — same-day re-entry on a higher timeframe | intraday bars |
| U-2 — theme/sector concentration | sector/industry mapping |
| U-6 — reduce size for small caps | market capitalisation |
| M-1, M-5, M-6 in their true form — QQQ/IWM behaviour | index series |
| P-12 — episodic pivots | news/earnings dates (**and the rule is never defined in the video**) |

### 4. DISCRETIONARY — must not be represented as objective

Rulebook §11 in full: anchor-fitting (D-1), "what would a great trader do"
(D-2), trading less when depleted (D-3), watchlist grading (D-4), judging which
setup type the market currently rewards (D-5), selling "when it feels extended"
(D-6), M-7 (own-position feedback as the primary regime read), N-8/N-9
(anti-revenge rules), X-4/X-7 (portfolio-state-dependent exits).

**These are approximately half of what makes the speaker's record. A scanner that
implements the other half and reports a score is not implementing his strategy,
and must not be labelled as if it were.**

---

## 2. The engineering decision

**Do not enable this as a signal-generating strategy on the current data.**

Evidence, in one place:

| Test | Result |
| --- | --- |
| Two-year portfolio, literal rules | **−22.4%** (benchmark +6.9%) |
| Two-year portfolio, 5%-ceiling reading | **−52.2%** |
| Signal-level expectancy, 3,383 trades | **−0.318 R, t = −13.18** |
| Out-of-sample 2021–2024, 5,896 signals | −0.016 R, t = −0.60 (flat) |
| Best of 48 parameter settings tested | −0.14 R (still negative) |
| Best of 7 exit readings | −24.1% |
| Forward edge vs buying at random | none at any horizon; significantly negative at 3 bars |
| Confluence (the video's core claim) | **inverted** — 1 level beats 2, 3 and 4 |
| Selection quality with stops removed | worse than random selection |
| Best single rule's contribution | +0.040 R against a −0.318 R hole |

What **should** be built from this work is listed in §13.

The spec below is written anyway, in full, because (a) the request was for a
deterministic developer-ready version, (b) it is the artefact that makes the
negative result reproducible and re-testable when better data arrives, and (c)
with `enabled: false` it is exactly the form this repository already uses for
unvalidated strategies (`research/strategy_config.proposed.json`).

---

## 3. Strategy name and objective

**S5 — Confluence Pullback (Champion Reconstruction)**

> Buy a liquid, fast-moving stock that is already in a daily and weekly uptrend
> and leading its universe on 3-month relative strength, at the moment it dips
> into a support level that other traders are watching — a moving average, an
> anchored VWAP, a prior breakout level or an unfilled gap — closes back above
> that level in the upper half of its range, and then trades above that bar's
> high on the following session. Risk is fixed at a small fraction of equity, the
> stop sits under the dip, and the position is trailed out on the first close
> below the 9 EMA after two trims into strength. The strategy is designed to lose
> small four times out of five and to be carried by the fifth.

---

## 4. Required data

| Field | Frequency | Mandatory |
| --- | --- | --- |
| symbol, date, open, high, low, close, volume | daily | yes |
| the same, resampled to weekly (completed weeks only) | weekly | yes |
| universe membership **with effective dates** | daily | yes for honest backtests — currently absent |
| a market index series | daily | proxy acceptable, real index preferred |
| sector / industry mapping | static | for U-2, currently absent |
| market capitalisation | daily or static | for U-6, currently absent |
| 5-minute bars | intraday | for the real entry (C-1…C-5), currently absent |

---

## 5. Indicators and exact settings

| Indicator | Setting |
| --- | --- |
| EMA | 9, 21, 50, 150 on daily close, `adjust=False` |
| Weekly EMA | 9, 21 on weekly close, resampled `W-FRI`, **shifted one week** |
| ATR | 14, Wilder (`ewm(alpha=1/14, adjust=False)` of true range) |
| ADR20 | `mean(high/low − 1, 20) × 100` |
| Turnover | `median(close × volume, 20)` |
| Anchored VWAP | anchored at the highest-high bar of the trailing 60 bars; `Σ(typical×vol)/Σ(vol)` from the anchor to today, typical = (H+L+C)/3 |
| Swing points | 3-bar fractals, **published 3 bars after the pivot** |
| Unfilled gap base | prior bar's high on an up-gap; expires when pierced or after 60 bars |
| Relative strength | 63-day return, cross-sectional percentile per date |
| Breadth | share of universe with `close > EMA50` |

---

## 6. Market filters (hard)

```
M1  index_close        >  index_EMA50
M2  index_EMA21[t]     >  index_EMA21[t-5]
M3  breadth50          >= 0.40
```

## 7. Stock filters (hard)

```
U1  median(close*volume, 20) >= 50_000_000        # INR
U2  ADR20                    >= 2.0               # percent
T1  EMA9 > EMA21 > EMA50
T2  EMA21[t] > EMA21[t-5]
T3  close > EMA150
T4  weekly_EMA9 > weekly_EMA21  AND  weekly_close > weekly_EMA9
U3  rs_rank_63d >= 70                             # percentile
P4  bars_since_20day_high <= 15
T5  swing_low > swing_low_prev
```

## 8. Setup conditions (hard, evaluated on the close of day t)

```
levels = [EMA9, EMA21, EMA50, EMA150, AVWAP,
          swing_high if close > swing_high else None,
          gap_base]

touched(L) := low[t] <= L * 1.005  AND  close[t] >= L * 0.995
confluence  = count of non-null L with touched(L)

S1  confluence >= 1
S2  (close[t] - low[t]) / (high[t] - low[t]) >= 0.50
S3  low[t] <= high20[t] - 1.0 * ATR14[t]
```

## 9. Entry conditions

```
E1  trigger   = high[t]
E2  valid only on session t+1
E3  fires when high[t+1] >= trigger
E4  fill      = max(open[t+1], trigger) * (1 + slippage)
E5  reject if (fill - stop) / fill > min(5%, 0.5 * ADR20)
E6  reject if the symbol is already held
```

## 10. Stop loss

```
SL  stop = low[t]                       # the setup bar's low
    a gap below the stop fills at the open, not at the stop
    within a bar, assume the stop is hit before any profit target
```

## 11. Target

```
There is no price target.  The video has none (rule X-1) and none must be
invented.  A scanner UI that requires a target field should display the +3R
partial level and label it "first trim", not "target".
```

## 12. Position sizing, management, exits, no-trade, re-entry

```
SIZE   shares = floor( 0.005 * equity(t) / (fill - stop) )
       cap at 30% of equity, at available cash, and at the leverage budget
       (base run: gross exposure <= 100%)

MANAGE  at +3R: sell 15% of the original position
        at +5R: sell 15% of the original position
        remainder trails; the 9 EMA rule governs it

EXIT    1. stop hit          -> exit at the stop, or at the open if gapped through
        2. close < EMA9      -> exit the remainder at that close
        3. partials exhausted
        4. (shorts only) 3 bars elapsed

NO-TRADE  any hard filter false; stop wider than E5; symbol already held;
          8 positions already open; 4 new entries already taken today;
          leverage budget exhausted

RE-ENTRY  permitted without limit, on a fresh setup + trigger
```

---

## 13. Signal score / ranking

The score must **not** convert a hard requirement into a soft point, and the
ranking factors below are ordered as the video orders them (relative strength,
then tightness, then dollar volume — 196:34 to 198:22).

**Hard requirements (pass/fail, no points):** every condition in §6–§9.
A candidate failing any of them does not appear at any score.

**Confirmation factors (max 40):**

| Factor | Points | Evidence |
| --- | ---: | --- |
| Reversal close (close in the top third of the range) | 15 | the only setup rule with a measurable positive contribution (+0.017 R) |
| ADR20 ≥ 4% | 15 | the best single parameter in the whole sweep (−0.178 vs −0.318 R) |
| Weekly 9 EMA rising as well as above the 21 | 10 | neutral in the ablation; kept because it is a stated hard rule in the video |

**Ranking factors (max 60), used only to order candidates that already pass:**

| Factor | Points | Note |
| --- | ---: | --- |
| RS percentile (linear 70→100 mapped to 0→25) | 25 | mildly *harmful* in the ablation; kept as a tiebreak only, per U-3 |
| Turnover percentile within the passing set | 20 | U-5; execution quality, not edge |
| Range contraction — today's range ÷ mean of the last 10 | 15 | U-4 |

**Confluence is deliberately NOT scored.** On this data it is inverted
(Deliverable 3 §2): one level beats two, three and four. It should be *displayed*
on the signal card, because it is central to the source material, with the
measured relationship shown next to it. It must not add points.

**Interpretation to render in the UI:** *"Score orders candidates within this
strategy. It is not a probability of profit. This strategy's measured expectancy
on 2024–2026 Indian daily data is −0.32 R per trade."*

---

## 14. Phase 10 — implementation pseudocode

Matches this engine's existing convention (`strategyN_features` → boolean
`strategyN_signal` → `_sN_quality`), so it drops into `core.py` alongside S1–S4.

```
DATA INPUT
  daily OHLCV per symbol, >= 260 bars
  weekly resample (W-FRI), shifted one week          # never read the open week
  universe-level: proxy index + breadth, RS percentile per date
  ↓
MARKET FILTER                                        # one boolean per date
  market_ok[t] = index_close[t] > index_ema50[t]
              AND index_ema21[t] > index_ema21[t-5]
              AND breadth50[t] >= 0.40
  ↓
STOCK FILTER                                         # one boolean per symbol/date
  stock_ok = dv20 >= 5e7
         AND adr20 >= 2.0
         AND ema9 > ema21 > ema50
         AND ema21 > ema21.shift(5)
         AND close > ema150
         AND w_ema9 > w_ema21 AND w_close > w_ema9
         AND rs_rank63 >= 70
         AND bars_since_high20 <= 15
         AND swing_low > swing_low_prev
  ↓
SETUP DETECTION                                      # on the close of day t
  for L in [ema9, ema21, ema50, ema150, avwap,
            swing_high if close > swing_high else NULL, gap_base]:
      touched[L] = (low <= L*1.005) and (close >= L*0.995)
  confluence = count(touched)
  setup_ok = market_ok and stock_ok
         and confluence >= 1
         and (close-low)/(high-low) >= 0.50
         and low <= high20 - 1.0*atr14
  ↓
CONFIRMATION                                         # day t+1 only
  trigger = high[t];  stop = low[t]
  if high[t+1] < trigger: EXPIRE                     # trigger dies with the day
  ↓
ENTRY
  fill = max(open[t+1], trigger) * (1 + 0.0005)
  stop_pct = (fill - stop)/fill * 100
  if stop_pct > min(5.0, 0.5*adr20): REJECT
  ↓
SL / TARGET
  stop   = low[t]                                    # hard
  target = NONE                                      # by design
  size   = floor(0.005*equity / (fill - stop)),
           capped at 30% of equity, cash and leverage budget
  ↓
TRADE MANAGEMENT                                     # each subsequent bar
  if low <= stop:  exit all at (open if open <= stop else stop);  DONE
  if high >= fill + 3*(fill-stop) and not trimmed_3R: sell 15%
  if high >= fill + 5*(fill-stop) and not trimmed_5R: sell 15%
  if close < ema9: exit the remainder at the close;  DONE
  ↓
EXIT   stop | 9-EMA close | partials exhausted | (shorts) 3 bars
  ↓
SIGNAL RANKING
  score = confirmation_points(max 40) + ranking_points(max 60)
  order by score desc, then RS desc, then turnover desc
  cap at 4 new entries per day, 8 open positions
```

Flagged as **not objectively expressible** and therefore absent from the code
above: the intraday trigger and its timing, the no-chase rule, the V-shaped
recovery requirement, theme/sector concentration, anchor fitting, variable risk
by conviction, and every rule in rulebook §11.

---

## 15. Phase 11 — final verdict

**Does the strategy make money on the supplied two-year data?** No.

| Question | Answer |
| --- | --- |
| Exact net return | **−22.40%** (literal reading, 145 trades) and **−52.17%** (5%-ceiling reading, 489 trades), from ₹1,000,000 |
| Maximum drawdown | −24.87% and −52.18% |
| Profit factor | 0.561 and 0.467 |
| Win rate | 18.6% and 21.3% — the win rate *does* reproduce his 22% |
| Expectancy | **Negative**: −0.427 R and −0.359 R per trade |
| Consistent across the two years? | Yes — consistently negative. 2024 −0.49 R, 2025 −0.32 R, 2026 −0.35 R |
| Robust or overfit? | Neither. Nothing was fitted; the parameter surface is flat and negative everywhere across 48 settings |
| Which rules are genuinely useful? | None decisively. The largest measurable contributions are the 9 EMA trailing exit (+0.040 R), the reversal close (+0.017 R) and the ADR floor (+0.014 R) — all trivial against a −0.318 R deficit |
| Which rules appear unnecessary? | The 150 EMA filter (changes 1 signal in 3,383), the breadth floor, the liquidity floor, the daily trend stack and the index slope are all inert. The higher-low requirement, the confluence requirement and the RS floor are mildly **harmful** |
| Which rules could not be tested? | The intraday trigger, timing and stop placement; the no-chase rule; theme/sector selection; small-cap sizing; episodic pivots; the real QQQ/IWM filters; and every discretionary rule (roughly half the system) |
| Can it be implemented reliably in the scanner? | Mechanically, yes — §4–§14 are deterministic and the code exists. It should be implemented with `enabled: false` |
| What additional data is required? | **1. 5-minute intraday bars** (without them the entry, the stop and the R-multiple denominator are all wrong). **2. A real index series.** **3. Sector/industry mapping.** **4. Point-in-time index membership** (the current universe is survivorship-biased). **5. Market capitalisation.** |
| Deploy live, paper trade, or reject? | **Reject in this form.** Not paper trading either — paper trading a strategy with a t = −13.2 negative expectancy only costs time |
| What must change before any deployment? | Get intraday data and re-run; drop the confluence claim or re-test it on the market it came from; abandon the daily-bar translation of the stop rule, which is self-contradictory |

### The blunt version

The video describes a real trader with a real, audited-competition record. That
is not in question. What this study establishes is narrower and harder:

1. **The mechanical core of the strategy transfers to Indian daily data as a
   reliably losing system** — −0.32 R per trade over 3,383 signals, t = −13.2,
   negative in every calendar year, every regime, every parameter setting and
   every exit reading tested.
2. **Its two most specific, testable claims fail on this data.** Confluence is
   inverted: a single level beats four. Tighter stops make things worse, not
   better — the opposite of the presentation's central slide.
3. **The failure is in stock selection, not in the exits.** Strip the stop out
   entirely, apply only the selection rules, and hold for three months: −12.0%
   against a −2.5% unfiltered control. No exit engineering can fix a selection
   that is worse than random.
4. **The likely reason is not that he is wrong; it is that the strategy is
   intraday and this data is daily.** His edge lives in a 1–2.5% stop placed
   minutes after a flush, turning a 30% move into 15 R. The daily translation
   risks a whole day's range for the same move and gets 1.7 R. That gap is
   structural and no amount of parameter work closes it.
5. **Roughly half the system is not rules at all** — no strict sell rule, an
   anchor moved until it fits, a self-reported month in which half the trades
   broke the plan. Whatever edge survives beyond the mechanical rules is
   unmeasurable from a transcript, and a scanner that claims to implement it is
   overstating what it has.

### What is worth building instead

Two findings from this study stand on their own and are worth pursuing:

* **ADR is the strongest single ranking variable found** (avg R −0.178 at ADR ≥
  4% vs −0.318 at ≥2%). It is monotonic across the sweep and consistent with the
  earlier audit's `ema200_proximity` finding that low-extension, high-volatility
  names behave differently. Worth testing as a universe filter for the existing
  strategies.
* **The equal-weighted proxy index and breadth series built here** (`features.py
  :: build_market`) fill a real gap — this repository's engine has carried
  `nifty_trend`, `market_breadth` and `sector_trend` as `None` placeholders since
  Phase 2b. That code is reusable immediately and is point-in-time by
  construction.
