# Golden regression harness

One question: **did a change move what a scan selects or scores?**

Strategy behaviour is frozen. Everything else - how data is loaded, cached,
paginated, displayed or secured - is fair game. These snapshots are the line
between the two.

## Running it

```
cd backend && pytest tests/test_golden_scan.py
```

Run it before every commit. If it fails, either a scan rule changed (not
allowed) or the snapshot genuinely needs to move.

## What is pinned

| file | what it protects |
|---|---|
| `strategy_signal_census.json` | **every signal S1-S5 fires on every bar** of the fixture - 25,603 across all five |
| `scan_nifty500_ungated.json` | the full scan row with the entry filter off |
| `scan_nifty500_all.json` | the live path: scan with the entry filter on |
| `forward_summary/results/positions.json` | the forward-test read endpoints |
| `scanner_signals.json` | the signal record |

The census is the one that matters most. A scan only evaluates the **latest
bar**, so a single-date snapshot covers whichever strategies happen to fire
that day - here S1, S3 and S5, which left S2's and S4's entry conditions
completely unprotected. Walking the history exercises all five and names the
symbol and date of anything that moves.

## Why a fixture database

`fixture_market_data.sqlite3.gz` (3.7 MB): 161 stocks, 10 index series, 750
bars each, plus the sector, forward-test and signal tables.

Hermetic on purpose. The harness pins the **symbol list** rather than resolving
"Nifty 500" over the network, because an index whose membership changes on
NSE's review schedule would make every failure ambiguous about whether the code
or the universe moved. 750 bars because at 400 S4 fired zero times and SEPA's
rules went unpinned.

## What is deliberately NOT pinned

`Adaptive Score`, `Learned Rank`, `Historical Edge R` and `Win Probability %`
are functions of accumulated learning data, so they move as the forward record
grows even when no scan rule changed. Freezing them would make the harness cry
wolf. See `FROZEN_COLUMNS` in `conftest_helpers.py`.

## Regenerating

```
python backend/tests/golden/generate.py          # snapshots only
python backend/tests/golden/build_fixture.py /path/to/market_data.sqlite3
```

Only when a change is **intended** to move the output. Review the diff - that
diff is the evidence about what the change did. A green test after an
accidental regeneration proves nothing.

## Sensitivity

The harness was checked against two deliberate perturbations before being
trusted:

| perturbation | result |
|---|---|
| `ENTRY_MIN_ATR_PCT` 4.0 -> 4.5 | 30 differences in the gated scan |
| S1 `wrsi14 >= 50` -> `>= 51` | 172 differences, naming symbol, count and first/last date |

A 4.0 -> 4.01 nudge passes, because no fixture row sits in that gap. Worth
knowing: this catches rule changes, not arbitrarily small threshold drift.
