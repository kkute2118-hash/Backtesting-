# IMPLEMENTATION_SPEC

How this would be built against the existing platform, if and only if
`BACKTEST_SPEC.md` passes. Written now so the backtest targets the real thing rather
than a throwaway.

---

## 1. Placement

```
scanners (S1-S5, FROZEN)
        |
        v
   scanner_signals      <- existing table, every signal recorded
        |
        v
  [ NEW: second-stage layer ]     <- read-only w.r.t. everything above
        |
        v
   ranked candidates -> forward test / UI
```

The layer **reads** scanner output and **writes** to new columns and a new table. It
never mutates scanner output, never reorders scanner logic, and never touches the
candle store.

### Files

| Path | Status | Purpose |
|---|---|---|
| `backend/app/engine/core.py` | **unchanged** | Scanners, filters, scoring, stops — all frozen |
| `backend/app/engine/trader_layer.py` | new | Deterministic features + gates + ranking |
| `backend/app/engine/trader_params.json` | new | Every fitted parameter, versioned |
| `backend/tests/test_trader_layer.py` | new | Unit tests per feature |
| `backend/tests/golden/` | **unchanged** | Guarantees the ABSOLUTE RULE |

New table, additive only:

```sql
CREATE TABLE IF NOT EXISTS trader_layer_verdicts (
    signal_id       INTEGER NOT NULL,     -- FK to scanner_signals
    evaluated_on    TEXT    NOT NULL,
    params_version  TEXT    NOT NULL,
    passed          INTEGER NOT NULL,
    reject_reason   TEXT,
    rank_score      REAL,
    risk_distance   REAL,
    avg_turnover_20 REAL,
    cluster_score   REAL,
    candle_quality  REAL,
    containment_ok  INTEGER,
    upper_half_ok   INTEGER,
    event_survived  INTEGER,
    ema_separation  REAL,
    PRIMARY KEY (signal_id, params_version)
);
```

`params_version` in the primary key means a re-run under new parameters adds rows
rather than overwriting them. Consistent with the existing "never delete, never
rewrite" rule for stored records.

---

## 2. Deterministic vs contextual (Section 41)

### Deterministic — implement exactly

| Feature | Definition |
|---|---|
| `ema(n)` | 10, 20, 50, 200 |
| `avg_turnover_20d` | rolling mean of `close * volume` over **20** bars, ₹ crore |
| `turnover_spike_ratio` | today's turnover / `avg_turnover_20d` |
| `avg_turnover_slope` | linear slope of `avg_turnover_20d` over the expansion |
| `ema_separation` | `abs(ema10 - ema20) / close` |
| `ema_compression` | `(max(ema10,20,50,200) - min(...)) / close` |
| `event_bar` | most recent bar where a tracked crossover occurred |
| `event_survived` | crossover configuration held from `event_bar` to now |
| `expansion_end_bar` | highest close in the last M bars, fixed causally |
| `containment_ok` | `max(high) since expansion_end_bar <= high[expansion_end_bar]` |
| `upper_half_ok` | `min(low) since expansion_end_bar >= midpoint of that bar's range` |
| `up_move_pct` | **sum of positive daily returns** across the leg (D-04 — not high−low) |
| `dna_single_candle` | high percentile of positive daily returns over lookback |
| `dna_up_move` | mean `up_move_pct` over historical legs |
| `pivot_low` | low of the most recent qualifying demand candle |
| `risk_distance` | `(close - pivot_low * (1 - buffer)) / close` |
| `counter_ratio` | up-candle body / prior red-candle body |
| `engulf_flag` | down candle fully engulfing the prior expansion candle |
| `lower_circuit` | limit-locked down bar |

`up_move_pct` deserves emphasis: the author explicitly rejects high-minus-low
(lecture 11). Getting this wrong changes every DNA figure and therefore every target.

### Contextual — approximate, label as approximate, validate

| Concept | Proxy | Validation |
|---|---|---|
| Candle quality | `body / (high - low)`, aggregated | Against lecture 10's ~20 labelled charts |
| Expansion quality | mean candle quality + cluster score + consistency | Same |
| Contraction quality | mean range ratio vs expansion + candle count | Same |
| Volume cluster | fraction of expansion bars with `volume >= K * median` | Same |
| Pivot quality | pivot candle quality + counter ratio + MA proximity | Same |
| Relativity | `up_move_pct / dna_up_move` → expected pullback MA | Against lectures 1, 7 |
| Blue candle | **not implemented** | RG-01 — unresolvable |

Every contextual output must carry an `is_approximation: true` marker through to the
UI. If a user sees a number, they should be able to tell whether it is the author's or
ours.

---

## 3. Parameters

All fitted parameters live in one versioned file. None are hard-coded.

```json
{
  "version": "unfitted-v0",
  "author_constants": {
    "AVERAGE_TURNOVER_LOOKBACK": 20,
    "EMAS": [10, 20, 50, 200],
    "COUNTER_RATIO_MIN": 0.5,
    "MIN_STOP_PCT": 1.5
  },
  "fitted": {
    "TURNOVER_FLOOR_CR": null,
    "MIN_EMA_SEP": null,
    "VOLUME_ELEVATION_MULTIPLE": null,
    "EXPANSION_LOOKBACK_M": null,
    "EVENT_LOOKBACK": null,
    "HOLD_BARS": null,
    "STOP_BUFFER": null,
    "CONTRACTION_TIME_RATIO": null,
    "TOP_N": null,
    "RANK_WEIGHTS": {}
  },
  "system_constants": {
    "SYSTEM_TURNOVER_LOOKBACK": 21
  }
}
```

`author_constants` are transcript-supported and must not be tuned.
`fitted` are ours; every one is a degree of freedom that counts toward the best-of-N
adjustment in `BACKTEST_SPEC.md` §6.
`SYSTEM_TURNOVER_LOOKBACK` stays separate from the author's 20, per Section 9.

---

## 4. Non-negotiable constraints

1. **Never modify** S1–S5 entry rules, indicators, lookbacks, thresholds, the
   entry-evidence filter, score calculation, the forward gate, universe definitions,
   stop/target/R calculation, or forward-test resolution.
2. **Never delete, rewrite or migrate** stored candles or forward-test records.
3. **Never log or return a secret.** Existing guard middleware and the server-side
   Next.js gateway continue to own that.
4. The golden signal census must remain byte-identical.
5. New API routes are **reads** and go direct to the backend; any mutation goes through
   `/api/gateway`.
6. Respect the memory envelope. The 485-stock scan currently peaks at 243 MB against a
   512 MB instance. New features are rolling-window computations over frames already
   loaded — they must not hold additional full-history frames. Cache under the existing
   bounded LRU (`CACHE_MAX_ENTRIES`), not a new unbounded memo.

---

## 5. Rollout, if validated

| Phase | Scope | Reversible |
|---|---|---|
| 1 | Compute and store verdicts. **Display nothing.** Accumulate live agreement data against actual forward-test outcomes. | Trivially |
| 2 | Display rank and reject reasons in the UI as advisory columns. No behaviour change. | Trivially |
| 3 | Optional user toggle to filter the candidate list by the layer. Off by default. | Yes |
| 4 | Feed the forward test, only after phase 1 has accumulated ≥30 closed trades under the layer and the live agreement matches the backtest. | Via the toggle |

Phase 1 is the important one and should run for a full quarter. It costs nothing, it
cannot break the live system, and it produces the only evidence that actually matters:
whether the layer's verdicts correlate with real forward outcomes on our own data.

The existing `MIN_CLOSED_FOR_VERDICT = 30` threshold applies to any displayed verdict
about the layer's performance, exactly as it does for strategy performance today.

---

## 6. Explicit warning against premature deployment

The methodology is derived from:
- One trader's discretionary process,
- Explained through roughly 40 hand-picked charts,
- Selected by that trader, with hindsight, to illustrate his own points.

That is a **survivorship-biased teaching sample**, not a dataset. The author himself is
careful to distinguish real-time from hindsight — "it's the hindsight analysis that can
say oh you could have bought it here; the point is **at this point what are the
guarantees? None**" (lecture 7) — but the *selection of which charts to teach from* is
unavoidably retrospective.

None of this makes the methodology wrong. It does mean the transcripts provide
**hypotheses**, and only our own 5-year candle store can provide evidence. Sections 30
and 37 of the master prompt say the same thing.
