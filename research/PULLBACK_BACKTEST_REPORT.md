# Deliverable 2 — Original Two-Year Backtest

The strategy exactly as reconstructed in
[`PULLBACK_STRATEGY_RULEBOOK.md`](PULLBACK_STRATEGY_RULEBOOK.md) §14, with no
parameter tuning of any kind performed before this result was produced.

Code: [`research/pullback/`](pullback/) · raw outputs: `original.json`,
`robustness.json`, `ablation.json`, `extras.json`, `shorts.json`, `controls.json`
and the per-trade CSVs, reproducible with the commands in §9.

---

## 1. Phase 3 — what the data actually contains

The upload was one file: the transcript. The "2 years of market data" is the
candle store this repository already keeps — `backups/market_data.sqlite3.gz` on
the `db-backup` branch (50 MB compressed, 159 MB on disk).

| Field | Present | Notes |
| --- | --- | --- |
| Symbol | yes | 500 NSE tickers; 485 have ≥260 bars and are used |
| Date | yes | daily, `2021-03-19` → `2026-09-04`, 1,355 sessions, 606,391 rows |
| Open / High / Low / Close | yes | unadjusted for splits/bonuses as far as can be told |
| Volume | yes | share volume; turnover derived as close × volume |
| **Intraday bars** | **no** | 1/5/15/60-minute data does not exist in this store |
| **Index series** | **no** | no Nifty, Bank Nifty, or any index row in `candles` |
| **Sector / industry** | **no** | no mapping table anywhere in the schema |
| **Market capitalisation** | **no** | — |
| **Corporate actions** | **no** | no split/dividend table |
| **News / earnings dates** | **no** | — |
| **Pre-market / after-hours** | **no** | — |

The two-year window used throughout is **2024-09-05 → 2026-09-04** (497 sessions),
matching the window of this repository's earlier audit so the numbers are
comparable. The earlier period, 2021-10-01 → 2024-09-04, is kept untouched as
out-of-sample.

### Rule → data → implementation map

| Video rule | Data required | Available? | How it was implemented |
| --- | --- | --- | --- |
| EMA 9/21/50/150 (T-1) | daily close | YES | `ewm(span, adjust=False)` |
| Weekly 9/21 EMA veto (T-7, T-8) | weekly bars | YES | resampled W-FRI, **shifted one week** so the in-progress week is never read |
| ADR, "fast-moving stock" (U-1) | daily H/L | YES | `mean(high/low − 1)` over 20 bars |
| Dollar volume (U-5) | close, volume | YES | median of close×volume over 20 bars |
| Anchored VWAP (P-2, T-5) | OHLCV + an anchor | PARTIAL | anchored to the highest high of the trailing 60 bars; **the video's "adjust the anchor until price respects it" is not codable** (D-1) |
| Confluence of levels (P-3) | the above | YES | count of the seven named levels touched on the same bar |
| Prior swing high / higher lows (T-6, P-2) | daily OHLC | YES | 3-bar fractals, **published 3 bars late** so no future bar is read |
| Unfilled gap support (P-2) | daily OHLC | YES | most recent unfilled up-gap base, ≤60 bars old |
| Relative strength (U-3) | cross-section | YES | 63-day return, percentile-ranked across the universe each day |
| Market trend / breadth (M-1…M-3) | index | **PROXY** | equal-weighted index built from the 485 constituents; breadth = % above own 50 EMA |
| Theme / sector (U-2) | sector map | **NO** | not implemented, not approximated |
| Small-cap size reduction (U-6) | market cap | **NO** | turnover floor is the only stand-in |
| Intraday trigger (C-1…C-5) | 1/5-min bars | **PROXY** | "break of the previous bar's high" evaluated on **daily** bars: entry when day *t+1* trades above day *t*'s high |
| Stop at low of day (R-1) | intraday | **PROXY** | the setup bar's low |
| Stop ≤ 50% ADR, ≤5% (R-4) | ADR | YES | both readings run — see §2 |
| No-chase >3% off LOD (N-1) | intraday | **NO** | unknowable on daily bars; partly subsumed by R-4 |
| Partials at +3R/+5R (X-2, X-3) | — | YES | 15% of position at each |
| Close below 9 EMA exit (X-5) | daily close | YES | evaluated at the close |
| Risk 0.5%, size = risk/stop (Z-1, Z-3) | — | YES | equity marked at the prior close |
| Sell "when extended on the hourly" (X-4) | hourly | **NO** | discretionary and intraday |
| Everything in rulebook §11 | — | **NO** | discretionary by nature |

> **The honest headline of Phase 3:** the video's entry, its stop and its
> no-chase rule are all intraday constructs, and the supplied data has no
> intraday bars. What is tested below is the daily-bar translation of the
> strategy, not the strategy as the speaker trades it.

### Known biases in the data itself

1. **Survivorship.** The 500 symbols are today's index membership applied
   backwards. Names demoted during the window are absent. This flatters any
   long strategy; it does not rescue one that loses.
2. **No corporate-action adjustment table.** Splits appear as gaps and can fire
   both stop-outs and setups spuriously.
3. **Costs.** 0.23% round trip (this repo's model) plus 5 bp of slippage per
   side. Impact cost for larger sizes is not modelled.

---

## 2. The stop rule does not survive translation — and both readings are reported

Rule R-1 says "stop at the low of day"; rule R-4 says "stop < 50% of the stock's
ADR, ≤5%". Intraday those are compatible: his low-of-day, measured at 10:00 from
an entry taken minutes after a flush, is a fraction of the day's eventual range.

On daily bars the setup bar's low-to-high span **is** approximately one ADR. So
"enter at the prior bar's high, stop at the prior bar's low" risks roughly one
full ADR — about double what R-4 permits.

Measured over the window: of 4,301 signals whose trigger fired, the required stop
was a median of **3.40%** against a median R-4 cap of **1.73%**. **4,146 of 4,301
(96.4%) are rejected by the literal rule.** The 155 survivors are, by
construction, the tiniest-range setup bars in the sample — and 78 of them
(50.3%) are stopped out on the entry bar itself.

Rather than pick one reading, both are run:

* **Run A — literal.** Both caps applied: `stop ≤ min(5%, 0.5 × ADR20)`.
* **Run B — ceiling only.** The ≤5% ceiling he also states, without the ADR
  half-range term.

Neither is an optimisation; A is the strict reading of what he says, B is the
strict reading of the sentence's second half. Both are reported in full.

---

## 3. Phase 4/5 — headline results

Starting capital ₹1,000,000. No leverage (gross ≤ 100%). Costs and slippage on.

| | **Run A (literal)** | **Run B (5% ceiling)** | Benchmark |
| --- | ---: | ---: | ---: |
| Starting capital | 1,000,000 | 1,000,000 | — |
| Ending capital | **776,034** | **478,252** | — |
| Net profit / loss | **−223,966** | **−521,748** | — |
| Total return | **−22.40%** | **−52.17%** | equal-weight index **+6.90%** |
| CAGR | −11.93% | −30.90% | +3.39% |
| Trades | 145 | 489 | — |
| Winners / losers | 27 / 118 | 104 / 385 | — |
| Win rate | 18.62% | 21.27% | — |
| Average win | +2.63 R (+5.25%) | +1.67 R (+5.69%) | — |
| Average loss | −1.13 R (−1.90%) | −0.91 R (−2.89%) | — |
| Profit factor | **0.561** | **0.467** | — |
| Expectancy | **−0.427 R** | **−0.359 R** | — |
| Total R | −61.9 R | −175.4 R | — |
| t-statistic on R | −3.00 | −6.12 | — |
| Max drawdown | −24.87% | **−52.18%** | −21.36% |
| Drawdown duration | 485 sessions | 481 sessions | — |
| Largest win | +8.92 R | +6.63 R | — |
| Largest loss | −1.93 R | −4.90 R | — |
| Avg holding period | 2.4 bars | 4.6 bars | — |
| Longest losing streak | 25 | 28 | — |
| Longest winning streak | 3 | 4 | — |
| Average stop width | 1.73% | 3.30% | — |
| Sharpe | −1.47 | −2.44 | — |
| Avg concurrent positions | 0.70 | 4.54 | — |
| Days with a position | 36.8% | 73.2% | — |

Signal counts: **6,329 setups** fired in the window. 2,028 never triggered.
Run A traded 145 of the rest; Run B traded 489. Capital was almost never the
binding constraint (3 rejections in Run A) — the stop-width cap was: it rejected
4,146 of Run A's 4,301 triggered signals against 918 of Run B's.

Exit mix:

| Exit | Run A | Run B |
| --- | ---: | ---: |
| Stopped on the entry bar | 73 | 91 |
| Stopped later | 35 | 131 |
| Gapped through the stop | 2 | 13 |
| First close below the 9 EMA | 32 | 244 |
| Position consumed by partials | 3 | 4 |
| Open at window end | 0 | 6 |

### Unconstrained signal-level result

The portfolio can only hold so many positions, so the table above measures 145 or
489 of the 6,329 setups. Running **every** signal independently at one unit of
risk removes that selection:

| | Run A | Run B |
| --- | ---: | ---: |
| Signals | 6,329 | 6,329 |
| Traded | 155 | **3,383** |
| Rejected — stop too wide | 4,146 | 918 |
| Never triggered | 2,028 | 2,028 |
| Average R | **−0.497** | **−0.318** |
| Win rate | 17.4% | 22.3% |
| Profit factor | 0.46 | 0.55 |
| **t-statistic** | **−3.79** | **−13.18** |
| Avg favourable excursion | +3.55% | +4.16% |
| Avg adverse excursion | −2.43% | −3.08% |

A t-statistic of −13.2 across 3,383 independent-ish signals is not sampling
noise. The signal is reliably negative on this data.

---

## 4. Time analysis

**By entry year** (2024 is four months, 2026 is eight):

| Year | Run A trades | Run A avg R | Run A equity | Run B trades | Run B avg R | Run B equity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2024 (Sep–Dec) | 24 | −0.196 | −0.71% | 84 | −0.486 | −14.17% |
| 2025 | 66 | −0.136 | −3.37% | 204 | −0.318 | −26.94% |
| 2026 (Jan–Sep) | 55 | −0.876 | −18.82% | 201 | −0.346 | −23.10% |

Both years lose in both runs. There is no single bad period carrying the result:
Run B's average R is between −0.32 and −0.49 in every calendar year.

**Monthly equity path (Run B)** — 1,000,000 at the start:

| | Sep-24 | Dec-24 | Mar-25 | Jun-25 | Sep-25 | Dec-25 | Mar-26 | Jun-26 | Sep-26 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Equity | 962,242 | 847,347 | 828,083 | 708,994 | 608,871 | 618,916 | 576,783 | 570,513 | 478,252 |

The curve is below its starting value from the first month and never returns to
it. The only meaningful pause is Oct–Dec 2025 (608,871 → 618,916); every other
quarter loses ground.

---

## 5. Market-regime analysis

Regimes are tagged from the proxy index **on the entry date**, so nothing is
known in hindsight.

| Dimension | Regime | Run B trades | Avg R | Win rate |
| --- | --- | ---: | ---: | ---: |
| Index trend | above 50 EMA | 452 | −0.331 | 21.7% |
| Index trend | below 50 EMA | 37 | −0.700 | 16.2% |
| Volatility | above median 21-day vol | 228 | −0.348 | 21.5% |
| Volatility | below median | 261 | −0.368 | 21.1% |

All 145 Run A trades fall in the index-above-50-EMA bucket, so it has no
below-50 sample. Run B has 37 such trades only because the market gate is tested
on the setup day *t* while the regime here is tagged on the entry day *t+1* — the
index crossed below its 50 EMA overnight in those cases. The strategy loses in
every regime it is allowed to trade in, and roughly twice as fast in the few
trades that slip through when the index turns weak, which is consistent with the
video's own market filter being directionally right even though it does not
rescue the result.

---

## 6. Trade analysis (Run B)

**Best trades**

| Symbol | Entry | Exit | Stop % | R | P&L % | Bars | Exit | Confluence | Levels | RS |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |
| ADANIPOWER | 2026-04-10 | 2026-05-11 | 3.53 | +6.63 | +23.4 | 19 | 9 EMA close | 1 | avwap | 94 |
| ABCAPITAL | 2025-06-03 | 2025-07-09 | 3.13 | +5.84 | +18.3 | 26 | 9 EMA close | 3 | ema9, avwap, swing high | 93 |
| KAYNES | 2024-12-02 | 2024-12-26 | 2.87 | +5.20 | +14.9 | 17 | 9 EMA close | 2 | ema9, avwap | 95 |

Why they qualified: each was a high-RS name in a daily uptrend (9>21>50, above
the 150 EMA, weekly 9>21), pulled back to touch one or more of the named levels,
closed in the upper half of its range, and traded above that bar's high the next
session. They are exactly what the rulebook describes — and they are the
strategy working as intended. All three were carried by the 9 EMA trail for 17–26
bars, which is where the payoff comes from.

**Worst trades**

| Symbol | Entry | Exit | Stop % | R | P&L % | Bars | Exit | Confluence |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| MEDANTA | 2025-04-02 | 2025-04-07 | 3.83 | −4.90 | −18.8 | 3 | gap through stop | 3 |
| SHRIRAMFIN | 2025-04-04 | 2025-04-07 | 4.37 | −2.31 | −10.1 | 1 | gap through stop | 2 |
| KOTAKBANK | 2025-03-25 | 2025-04-07 | 4.35 | −1.81 | −7.9 | 8 | gap through stop | 1 |

All three exited on **2025-04-07**, the tariff-shock gap down. This is the
video's own "huge gap down" risk (CTX and the SERV/-30% example at 144:10),
reproduced exactly: the stop does not protect against an overnight gap, and a
0.5%-risk position became a −4.9R loss. Note that the worst trade had
**three** levels of confluence — the video's highest-conviction configuration.

**Typical winner** — DIVISLAB, entered 2026-08-26 at 8,748.87, stop 8,497.00
(2.88%), three levels (9 EMA, anchored VWAP, prior swing high), RS 93. Ran to
+8.2% favourable excursion, exited at the window end for **+1.31 R / +3.78%**
after 7 bars. The median winner gives back most of its excursion to the trail.

**Typical loser** — ENDURANCE, entered 2025-09-09 at 3,054.33, stop 2,929.10
(4.10%), three levels, RS 91. Maximum favourable excursion **+0.84%**; stopped
two bars later for **−1.07 R / −4.37%**. The median loser never goes anywhere at
all: it triggers, fails immediately, and pays the full stop.

---

## 7. The short side, reported separately

The video's pullback-short is the exact mirror (rally into declining EMAs /
anchored VWAP, weekly veto reversed, break of the previous bar's low, stop at the
previous bar's high, X-8's 2–3 day time exit). It is kept out of the headline for
two reasons stated in the source and in the market structure: the speaker's own
conclusion that his shorts carried worse reward-for-risk and should be fewer
(223:20, 225:04), and the fact that **Indian cash equities cannot be held short
overnight at all** — this would require futures or options, which the data does
not contain.

| | Literal stop cap | 5% ceiling |
| --- | ---: | ---: |
| Portfolio trades | 59 | 439 |
| Portfolio return | +1.5% | −25.6% |
| Win rate | 35.6% | 36.7% |
| Profit factor | 1.08 | 0.75 |
| Max drawdown | −6.7% | −31.7% |
| Signal-level count | 66 | 1,780 |
| Signal-level avg R | +0.033 | +0.010 |
| **Signal-level t-stat** | **0.15** | **0.33** |

The +1.5% is 59 trades with a t-statistic of 0.15. That is indistinguishable from
zero. **No conclusion either way should be drawn from the short side.**

---

## 8. Look-ahead controls — what was done and what it proves

**Timing contract enforced by the simulator** (`research/pullback/backtest.py`):

* setups are evaluated on the close of day *t* from bars ≤ *t*;
* the trigger can only fire on day *t+1*;
* the fill is `max(open(t+1), trigger)` — a gap through the trigger fills at the
  open, never at the trigger price;
* position size and exposure use marks from the close of day *t*;
* **within a bar the stop is assumed to be hit before any profit target**;
* a gap below the stop fills at the open, not at the stop.

**Confirmation candles.** The video's confirmation is intraday (break of the
previous 1- or 5-minute bar's high). The daily translation makes day *t*'s high
the trigger and day *t+1* the only session it can fire in. This is strictly
weaker than what he does — the intraday version enters hours earlier at a better
price — and no daily version can be closer without inventing intraday structure.

**The one genuinely ambiguous case: a bar that both triggers and breaches the
stop.** Without intraday bars the order is unknowable. The base run takes the
adverse assumption (entry then stop). The benign assumption (the low happened
before the trigger fired, so the position was not yet open) is reported as a
sensitivity: Run B moves from **−52.2% to −43.9%**, signal average R from −0.318
to −0.280. The assumption matters, but it does not change the sign.

**Truncation test.** `research/pullback/test_no_lookahead.py` rebuilds every
feature on history truncated at a cut date and requires it to equal the
full-history value at that date, across six symbols × eight random cut dates.
This is what catches the class of defect this repository's earlier audit found in
production (`monthly_lookahead`). It **passes** for every column, including the
weekly EMAs, the fractal swing points and the anchored VWAP.

**Arithmetic reconciliation.** Sum of per-trade P&L = −522,164.81; equity change
= −521,747.60; difference 417.21, which is the mark-to-market on positions still
open at the window end. Three trades picked at random were re-derived by hand
from the raw candles and matched the reported P&L to the paisa.

**Positive control.** A harness that can only produce losses proves nothing. See
`controls.json` and §3 of Deliverable 3.

---

## 9. Reproducing this

```bash
# the dataset lives on the db-backup branch, not in the working tree
git cat-file -p $(git rev-parse origin/db-backup:backups/market_data.sqlite3.gz) \
  > /tmp/market_data.sqlite3.gz && gunzip /tmp/market_data.sqlite3.gz

python3 -m research.pullback.test_no_lookahead --db /tmp/market_data.sqlite3
python3 -m research.pullback.run_study  --db /tmp/market_data.sqlite3 \
        --out research/results --cache /tmp/feat_cache.pkl --phase all
python3 -m research.pullback.run_extras --db /tmp/market_data.sqlite3 \
        --out research/results --cache /tmp/feat_cache.pkl --cache-dir /tmp/caches
```

Runtime is about 20 minutes end to end; `pandas` and `numpy` are the only
dependencies.
