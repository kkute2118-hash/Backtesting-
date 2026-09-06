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
| `diag.py` | duplicate zones, the quarters with no signals, the F5 distribution |

**Nothing here imports `backend/app/engine/core.py`.** The prior audit found
look-ahead in that engine's higher-timeframe features, and the brief's rule is
that a contaminated backtest is never the thing you optimise.
