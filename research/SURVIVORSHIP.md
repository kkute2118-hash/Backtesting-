# Survivorship bias in the S4/S5/S6 backtests

Every study before 27 Sep 2026 replayed the strategies over **today's**
Nifty 500. That list knows the future. Companies that grew into the index are
in it and companies that shrank out of it are not, so the early years look
better than anyone could have traded.

## What was changed

- `core.point_in_time_universe(data, top_n)`: on each day, the `top_n` stocks
  by median traded value over the previous 60 sessions. It uses only data known
  before that day, so a stock's own breakout day cannot vote it in. This
  approximates index membership, which in practice follows size, because
  historical constituent lists are not published in a usable form.
- `core.historical_entry_verdict()` and `core.sector_rank_history()`: the
  scanner's live entry filter (turnover floor, ATR floor, top-3 sector rank)
  evaluated with what was known **on the signal day**. On the latest day it
  agrees with the live `entry_filter_verdict()` on all 400 stock/strategy
  checks tried.
- `core.run_s6_backtest(..., eligible=...)`: S6 replay that skips signals on
  days the stock was not in the point-in-time universe.
- `scripts/survivorship_study.py` and `.github/workflows/survivorship-study.yml`:
  the full check (below).

## What the stored data already shows

The store holds today's list only, so this bounds the bias but cannot remove
it. Each row keeps only trades whose stock was in the point-in-time top N on
its signal day. The trades are the raw engine signals before each strategy's
entry filter, so S4 and S5 averages here are lower than their filtered
figures.

| Strategy | Universe | Trades | Win % | Avg % | Avg 2022-24 | Avg 2025-26 |
|---|---|---|---|---|---|---|
| S6 | today's list | 649 | 44.4 | 19.5 | 20.3 | 11.3 |
| S6 | point-in-time top 400 | 572 | 43.7 | 17.7 | 18.2 | 12.1 |
| S6 | point-in-time top 300 | 410 | 42.0 | 16.3 | 16.5 | 14.2 |
| S6 | point-in-time top 200 | 232 | 40.5 | 14.8 | 14.2 | 20.4 |
| S5 (raw) | today's list | 2,848 | 40.5 | 3.8 | 4.7 | 1.9 |
| S5 (raw) | point-in-time top 300 | 1,803 | 40.5 | 2.7 | 3.1 | 1.9 |
| S5 (raw) | point-in-time top 200 | 1,102 | 39.4 | 2.1 | 2.4 | 1.5 |
| S4 (raw) | today's list | 2,774 | 39.1 | 2.7 | 4.8 | 1.4 |
| S4 (raw) | point-in-time top 300 | 1,382 | 39.9 | 2.7 | 4.0 | 2.0 |
| S4 (raw) | point-in-time top 200 | 782 | 40.4 | 2.3 | 5.2 | 1.2 |

- **S6 holds up.** Restricting to stocks that were already large when they
  signalled costs a few points per trade, and in 2025-26 the larger names did
  better. That is the pattern of a real edge, not a survivorship artefact.
- **S5's early edge is partly survivorship.** Its 2022-24 average halves from
  4.7% to 2.4% in the top 200, while 2025-26 barely moves. The pre-2025 S5
  numbers in earlier reports should be read as optimistic.
- **S4 is roughly stable** across universe sizes.

## What is still missing, and how to close it

Stocks that were in the index years ago but are not today have no candles in
the store at all, so no reweighting of the stored universe can include them.
The survivorship-study workflow downloads the whole NSE cash market (about
2,000 stocks from Dhan's instrument list) into a throwaway copy of the
database. It then replays S4, S5 and S6 with the point-in-time universe, the
live entry filters and a point-in-time S6 breadth, and reports each
strategy's results split into stocks in today's list and stocks not in it.

It is read-only with respect to the backup (`contents: read`), and it runs
only when started by hand: Actions, then "Survivorship study", then Run
workflow. Expect a few hours, most of it the download. The results are in the
run's summary and in the `survivorship-study` artifact.

Two limits remain after that run:

- Companies delisted before today are not in Dhan's current instrument list,
  so they are still missing. They are few in the Nifty 500 over 2022-26, but
  not zero.
- Traded value is a proxy for index membership, not the list itself.
