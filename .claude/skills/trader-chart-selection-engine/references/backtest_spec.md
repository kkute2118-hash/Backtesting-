# BACKTEST_SPEC

Design for the mandatory validation (master prompt Sections 30–37). **Nothing from the
knowledge model may be deployed before this runs and passes.**

This spec is written to be executable against our existing platform. It reuses the
golden regression harness in `backend/tests/golden/` and the engine in
`backend/app/engine/core.py`, and it changes neither.

---

## 1. The ABSOLUTE RULE, restated as a test

S1–S5 selection and scoring are frozen. This layer is a **post-filter and re-ranker**
over scanner output. The existing golden harness enforces it:

> The full-history signal census (`strategy_signal_census.json`, 25,603 signals) must
> be **byte-identical** before and after this work. If it changes, the ABSOLUTE RULE has
> been broken and the change is reverted.

Run `pytest backend/tests/test_golden_scan.py` as the first and last step of every
backtest iteration. This is not a formality — it is the only mechanical guarantee that
the second-stage layer stayed second-stage.

---

## 2. Arms (Section 30)

| Arm | Definition |
|---|---|
| **BASELINE** | S1–S5 as they run today, including the existing entry-evidence filter. No changes. |
| **MODEL A** | BASELINE + hard gates only (Gates 1–4 of `STOCK_SELECTION_ENGINE.md`). No ranking. |
| **MODEL B** | BASELINE + hard gates + Tier-2 ranking, take top N per day. |
| **MODEL C** | MODEL B + the author's entry timing (`ENTRY_ENGINE.md`) and exit rules (`EXIT_ENGINE.md`) replacing our current stop/target. |

Arms are strictly nested, so each increment is attributable. If MODEL B does not beat
MODEL A, the ranking adds nothing and should be dropped regardless of whether B beats
BASELINE.

**MODEL C is the riskiest arm** because it changes trade management as well as
selection, and our existing stop/target logic is itself frozen for the live system.
MODEL C must run in a research harness only, never against the live engine path.

---

## 3. Universe, period and data

- **Universe:** NSE All Cash as stored, with the existing Nifty 500 / Smallcap /
  Midcap subsets available as slices. Report per-universe.
- **Period:** the full stored candle history (~5 years where available).
- **Bars:** daily, completed candles only. This matches the existing forward-test
  resolution rule and is non-negotiable for look-ahead reasons.
- **Weekly and monthly** series are resampled from daily, and must be resampled using
  **only completed weeks/months** as of the decision bar.

### Survivorship (Section 32)

Our candle store is built from current index membership, so it is **survivorship-biased
by construction**. This cannot be fixed with the data we have.

**Required action:** state the bias in every result table rather than working around
it. Additionally, run the comparison **within the same universe for all arms**, so the
bias is common-mode and the *relative* comparison between BASELINE and MODEL A/B/C
remains informative even though absolute returns are inflated.

Do not claim absolute CAGR. Claim only differences between arms.

---

## 4. Costs (Section 33)

Lecture 13 makes this load-bearing rather than a refinement. Model, per side:

| Component | Treatment |
|---|---|
| Brokerage | flat or bps, per the user's actual broker |
| STT | **non-deductible** — track separately and subtract at the end |
| Exchange transaction charges | bps |
| SEBI charges, stamp duty | bps |
| GST | on brokerage + exchange charges |
| **Slippage** | bps, scaled by position size relative to `avg_turnover_20d` |

Slippage must scale with size. The author's whole objection to 1% stops is that fixed
slippage assumptions hide the real cost at size (lecture 12). A flat slippage constant
reproduces exactly the error he warns about.

**Report gross and net side by side.** Net is the headline.

---

## 5. Look-ahead (Section 31)

Specific hazards in this methodology, each with its required control:

| Hazard | Control |
|---|---|
| "The expansion-ending candle" is identified in hindsight | Define it causally: the highest close of the last M bars, fixed as of the decision bar and never revised |
| "Contraction contained within the high" uses the full contraction | Evaluate containment using only bars up to the decision bar |
| "Counter candle" requires a later candle | Only counters that occurred **before** the decision bar count |
| "Event survived the contraction" | Survival is evaluated only over bars already closed |
| `avg_turnover_20d` | Must exclude the decision bar itself, or use it only if the decision is made at that bar's close |
| Weekly/monthly resampling | Use only completed higher-timeframe bars |
| DNA estimation | Computed from history strictly before the decision bar |

**Mechanical check:** run the whole pipeline with all future bars truncated at the
decision date and confirm the signal set is identical to the full-history run. Any
difference is look-ahead. This is cheap to implement and catches most leaks.

---

## 6. Statistics

Reuse the discipline already established in this project (`SECTOR_TIMING_FINDINGS.md`):

1. **Per-year control.** Report every arm year by year. A result driven by one year is
   not a result.
2. **Per-strategy breakdown.** S1/S2/S3/S5 use the ATR filter and S4 uses sector rank;
   they behave differently and pooling hides it. This project has already been burned
   once by a pooled result dominated by S1+S3 — do not repeat it.
3. **Shuffled/permutation nulls**, on **both** the sign-count and mean statistics.
4. **Circular-shift nulls** to preserve autocorrelation.
5. **Best-of-N adjustment.** Every parameter swept counts toward N. Declare the sweep
   size before running.
6. **Minimum sample.** The existing `MIN_CLOSED_FOR_VERDICT = 30` applies. Fewer than
   30 closed trades in a cell means "insufficient sample", not a weak result.

---

## 7. Out-of-sample (Section 34)

- **Train:** earliest 60% of the period. All parameter fitting happens here and only
  here.
- **Validate:** next 20%. Used once, to select among a small number of candidate
  configurations.
- **Test:** most recent 20%. **Touched once, at the end.** If the test result
  disappoints, that is the answer — it is not an invitation to refit.

Freeze the parameter set in a committed JSON file before the test split is read.

---

## 8. Ablations (Sections 35–36)

Remove one gate at a time from MODEL B and measure the delta:

| Ablation | Removes |
|---|---|
| A1 | Liquidity gate (Gate 1) |
| A2 | Event / EMA structure (Gate 2) |
| A3 | Weekly 10>20>50 filter |
| A4 | Contraction containment (3a) |
| A5 | Upper-half rule (3b) |
| A6 | Counter-candle rule (3d) |
| A7 | Volume cluster (3f) |
| A8 | Pivot quality / risk distance ranking |
| A9 | Earnings exclusion |
| A10 | Top-N cap |

Plus the two overlap checks that matter most here:

| Check | Question |
|---|---|
| **O1** | Does the layer add anything **beyond S3 alone**? S3 (EMA50 pullback) already resembles the point-3→5 sequence. |
| **O2** | Does the layer add anything **beyond S5 alone**? S5 (pocket pivot) already resembles the volume-cluster and turnover-spike logic. |

If the layer's entire benefit is reproducible by S3+S5, it is not a new edge — it is a
re-derivation of scanners we already run.

---

## 9. Metrics

Per arm, per year, per strategy, per universe:

- Trades; win rate; mean/median return per trade
- **Net** expectancy after all costs; gross expectancy as diagnostic
- Max intra-trade drawdown distribution (lecture 8 predicts this is wide)
- Portfolio CAGR, max portfolio drawdown
- **Capital efficiency**: return per unit of capital-days deployed
- Candidates per day before and after the funnel
- **Rejected-candidate forward returns** — see below

### The "left vs missed" diagnostic

Lecture 13 supplies a falsification test the author states himself:

> "if [the trades you left] all are moving up, and the ones I'm picking are all coming
> down — if that is the case, **then there is a big, big, major fault in your
> framework.**"

So: track the forward returns of **rejected** candidates alongside accepted ones. If
rejects outperform accepts, the funnel is inverted and should be discarded regardless
of what the headline expectancy says. This is the cheapest and most informative single
diagnostic in the whole spec.

---

## 10. Portfolio construction

A per-trade backtest will **understate** this methodology. A large part of the author's
stated return comes from recycling capital out of a 20%-up position into a better
setup (lectures 11, 13, 14).

Therefore:

- Portfolio-level simulation, ₹1,00,000 initial capital (consistent with the user's
  earlier analyses).
- **2–3 concurrent slots**, consistent with 35–40% starting size.
- One position per stock (matches the live forward-test constraint already enforced).
- Tranche exits per `EXIT_ENGINE.md`; freed capital immediately available.
- Slot contention resolved by the Tier-2 rank.

Report **both** per-trade and portfolio metrics. The gap between them measures how much
of the methodology is capital recycling rather than selection.

---

## 11. Pass criteria — declared before running

MODEL A/B/C is accepted only if **all** of the following hold:

1. Net expectancy exceeds BASELINE **on the test split**, not merely in training.
2. The improvement survives the best-of-N adjustment for the declared sweep size.
3. It is positive in **at least 4 of 5 years** — not carried by one year.
4. It holds for **at least 3 of the 5 strategies** individually.
5. Rejected candidates do **not** outperform accepted ones (§9).
6. It survives ablations O1 and O2 — the edge is not just S3+S5 restated.
7. The golden signal census is unchanged (§1).

**If these are not met, the honest outcome is to report that the transcript-derived
layer did not improve on the existing scanners.** That is a legitimate and useful
result, and it is the one Section 37 demands if the data says so.

---

## 12. Sequencing

1. Golden harness green. **← gate**
2. Implement deterministic features only (turnover, EMAs, containment, separation,
   engulf/counter, pivots). Unit-test each against hand-worked transcript examples.
3. Validate the approximations (candle quality, cluster score) against the author's own
   accept/reject calls in lecture 10 — roughly twenty labelled charts. **If the
   approximation cannot reproduce his labels on his own examples, it is not a usable
   proxy** and must be dropped rather than tuned.
4. MODEL A on the training split.
5. MODEL B, parameter sweep on training only.
6. Ablations on training.
7. Validation split, once, to pick the final configuration.
8. Freeze parameters to a committed file.
9. Test split, once.
10. Report — including a negative result if that is what comes out.
11. Golden harness green. **← gate**

Step 3 is the one most likely to stop this project early, and it should. If our
`body/range` proxy cannot separate the charts the author accepted from the ones he
rejected, then the quality layer is not reproducible from the transcripts and the
honest deliverable is the hard gates alone.
