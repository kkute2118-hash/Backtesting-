# GTF "Trading in the Zone" — quantitative research

Reproduces the study end to end.

```bash
pip install pandas numpy pyarrow pytest
python -m pytest test_gtfcore.py -q          # 15 point-in-time / rule tests

DB=/path/to/market_data.sqlite3
python build_events.py  --db $DB --out events.parquet     # ~85 s, 104,592 arrivals
python build_control.py --db $DB --events events.parquet --out control.parquet

python analysis_control.py     # is it a bull market or an edge?
python analysis_claims.py      # every video claim, train / val / test
python analysis_mechanism.py   # why the video's own score is inverted
python analysis_exits2.py      # stop x target discovery vs the placebo
python analysis_candidates.py  # candidate strategies
python analysis_challenge.py   # sensitivity, walk-forward, concentration, regime
python analysis_portfolio.py   # no-trade filter and portfolio constraints
python analysis_final.py       # survivorship probe, selection variance

python build_exits.py   --db $DB --events events.parquet --out exits.parquet
python analysis_exit_policy.py  # trailing vs static, chosen on train
python analysis_winners.py      # winner anatomy + cross-validated score
python analysis_walkforward.py  # quarterly refit, no fold sees its future
python analysis_robust.py       # exit / liquidity / model-choice sensitivity
python analysis_production.py   # the as-deployed configuration
python scan.py          --db $DB            # tomorrow's ranked signals

python score7.py               # 7/7 only, per trade and as a portfolio
python score7b.py              # why the score flipped: the stop, not the score
python last2y.py               # win rate and ROI for the last two years
python walkthrough.py          # one real trade end to end, winner and loser

python trades_2y.py            # the prior audit's own window + trades_audit_window.csv
python chart_check.py          # raw candles of real trades, to check by eye
python diag.py                 # duplicates, dark quarters, what F5 really admits
```

| file | role |
| --- | --- |
| `CONCEPT_INVENTORY.md` | every testable concept extracted from the 52-hour transcript |
| `FINDINGS.md` | round one: the video's claims tested, what survived, what did not |
| `FINDINGS_V2.md` | round two: better exits, a learned score, and what removing the illiquidity tilt cost |
| `STRATEGY.md` | GTF-D13, round one's specification (kept for the record) |
| `SYSTEM.md` | **GTF-D14, the running system** |
| `scan.py` | produces tomorrow's ranked signals |
| `gtf_strategy.json` | both, machine-readable |
| `gtfcore.py` | zone detection, point-in-time aggregation, indicators |
| `build_events.py` | every demand-zone arrival, with context and forward path |
| `build_control.py` | the matched placebo |
| `evaluate.py` / `exits.py` / `candidates.py` | scoring under an explicit exit policy |
| `trades_2y.py` | the strategy on 2024-09-04..2026-09-04, and the trade list |
| `chart_check.py` | prints a trade's raw candles with the zone marked |
| `walkthrough.py` | one 7/7 trade start to finish, and the arithmetic of the edge |
| `score7.py` / `score7b.py` | the 7/7 result and the stop-vs-score correction |
| `last2y.py` | the last two years on their own |
| `diag.py` | duplicate zones, the quarters with no signals, the F5 distribution |

**Nothing here imports `backend/app/engine/core.py`.** The prior audit found
look-ahead in that engine's higher-timeframe features, and the brief's rule is
that a contaminated backtest is never the thing you optimise.

## Round four — the liquidity course, on the speaker's definitions

`liq.py` implements liquidity grabs, sweeps and runs as the 93-minute course
defines them, replacing the earlier `sweep.py`, which turned out to encode my
paraphrase rather than his rules. `test_liq.py` covers point-in-time
correctness; it caught two contaminations that would have flattered the
results (see FINDINGS_V4.md §2).

    python build_liq.py --db $DB --out /tmp/gtf/liq.parquet
    python build_liq_control.py --db $DB --setups /tmp/gtf/liq.parquet \
        --out /tmp/gtf/liq_control.parquet
    python analysis_liq.py    # each pattern, and which discriminators work
    python analysis_liq2.py   # against the matched placebo and the mirror trade
    python analysis_liq3.py   # as a filter on GTF and S1-S4, split by period
    python analysis_liq4.py   # rank on 2021-2023, read the held-out period once
    python analysis_liq5.py   # significance for the one rule that survived
    python analysis_liq6.py   # that rule used as a filter, split by period

Result: a small real edge standalone, harmful as a filter. Not deployed.

## Round five — one ranked queue, two trades a week

The allocation problem, which round four showed matters more than which
strategy generates a signal. Every source is pooled onto identical terms and
ranked; the marking system is in MARKING.md.

    python build_pool.py --db $DB --out /tmp/gtf/pool.parquet   # 289,924 candidates
    python analysis_rank.py    # walk-forward expected-R model, decile behaviour
    python analysis_rank2.py   # why it looked inverted; simple rankers
    python analysis_rank3.py   # the turnover floor, then re-measure
    python analysis_rank4.py   # 3 a week, every rule, against random and the index
    python analysis_rank5.py   # gating, budget sweep, win-probability target
    python analysis_rank6.py   # the surviving rule, paired against random
    python weekly.py 2026-08-07                                 # the shortlist

`rank.py` holds the walk-forward scaffolding, `portfolio.py` the one
simulator everything uses, `weekly.py` the production marking system.
