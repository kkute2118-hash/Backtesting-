# Champion-pullback study

Reconstruction and backtest of the strategy described in the interview
*"969% Return in 1 Year: The Winning Pullback Strategy of a Trading Champion"*
(Martin Luk, US Investing Championship 2025), tested on the Nifty-500 daily
candle store this repository already keeps.

**Result: the daily-bar translation loses money. -0.318 R per trade across 3,383
signals, t = -13.18.** Read `../PULLBACK_SCANNER_SPEC.md` §15 before using
anything here.

| File | Role |
| --- | --- |
| `features.py` | point-in-time feature engine — EMAs, ADR, anchored VWAP, confirmed fractals, unfilled gaps, completed-week weekly EMAs, equal-weighted proxy index and breadth |
| `strategy.py` | the rule engine; every ablatable rule is a flag on `Config`, so the ablation never edits rule code |
| `backtest.py` | portfolio simulation, unconstrained signal study, forward-return probes |
| `metrics.py` | performance, risk, period and regime statistics |
| `edge_analysis.py` | does the setup pick stocks that go up, measured against buying at random |
| `run_study.py` | phases: `original`, `shorts`, `robustness`, `ablation` |
| `run_extras.py` | checks needing their own feature build (anchor and RS lookbacks) plus trade examples |
| `test_no_lookahead.py` | truncation test — every feature recomputed on truncated history must equal its full-history value at the cut date |

## Running it

```bash
git cat-file -p $(git rev-parse origin/db-backup:backups/market_data.sqlite3.gz) \
  > /tmp/market_data.sqlite3.gz && gunzip /tmp/market_data.sqlite3.gz

python3 -m research.pullback.test_no_lookahead --db /tmp/market_data.sqlite3
python3 -m research.pullback.run_study  --db /tmp/market_data.sqlite3 \
        --out research/results --cache /tmp/feat_cache.pkl --phase all
python3 -m research.pullback.run_extras --db /tmp/market_data.sqlite3 \
        --out research/results --cache /tmp/feat_cache.pkl --cache-dir /tmp/caches
```

`pandas` and `numpy` only. About 20 minutes end to end. Run the truncation test
first: it is what catches the class of look-ahead defect the earlier audit found
in production.

## Timing contract

Setups are evaluated on the close of day *t* from bars <= *t*; the trigger can
only fire on day *t+1*; fills are `max(open, trigger)`, so a gap through the
trigger fills at the open; sizing uses marks from the close of day *t*; within a
bar the stop is assumed hit before any target; a gap below the stop fills at the
open.
