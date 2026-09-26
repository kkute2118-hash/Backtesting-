# S6 breadth breakout: trade playbook, from selection to exit

S6 buys a fresh 50-day-high breakout, but only while the whole market is
breaking out with it. This file is the operating procedure. The rules live in
`backend/app/engine/core.py` (search `STRATEGY 6`), and the numbers below come
from the Dhan candle store restored from the `db-backup` branch: 511 stocks,
March 2021 to 25 September 2026.

The scanner now carries three strategies: S4 (SEPA), S5 (pocket pivot) and
S6. S1-S3 are retired: flat or negative in every stored backtest run
(`research/SECTOR_TIMING_FINDINGS.md`).

## Where the rules came from

1. Ranked the 1-year gainers (25 Sep 2025 to 25 Sep 2026). The top 25 ran
   +63% to +224%, led by WELCORP, HFCL and ATHERENERG.
2. Measured each winner on the day its run started (first close above its
   prior 50-day high after the year's low).
3. Tested those traits against all 5,026 first-in-four-weeks 50-day-high
   breakouts from 2022 to 2026, picking thresholds on 2022-24 only and
   checking them on 2025-26.

The usual checklist (RS rank >= 80, a volume surge, a tight base, a strong
close) did **not** beat ordinary breakouts. Market breadth, volatility and
position in the 52-week range did.

| 60 sessions after the signal | Win rate | Average return |
|---|---|---|
| Every breakout, 2025-26 (unseen) | 51% | +2.3% |
| S6 rules, 2025-26 (unseen) | 67% | +8.6% |

## Step 1 - Check the market (every day)

**Market breadth**: each day, the share of stored stocks that closed above
their prior 50-session high, summed over the last 10 sessions. 0.50 means that
on average 5% of all stocks broke out every day for two weeks.

- Breadth **>= 0.50**: S6 is live. Signals cluster here: on a signal day there
  are 2.6 on average and up to 14.
- Breadth **< 0.50**: no new S6 entries. Keep managing open trades.

The scan results page shows the reading under "Market regime". On 25 Sep 2026
it was 0.11. It peaked at 0.52 in November 2025, when most of that year's
winners launched.

## Step 2 - Selection: all five rules on the breakout day's close

1. Close above the highest high of the prior **50** sessions, and more than
   **28 calendar days** after the stock's previous such close.
2. Market breadth **>= 0.50**.
3. ATR(14) **>= 2.8%** of the close (simple 14-day mean of the true range).
4. Close at least **60%** above the 52-week low.
5. Close within **15%** of the 52-week high.

The scanner's shared safety gate (illiquid or manipulated-looking names) runs
before any strategy, as it does for S4 and S5.

**When more signals fire than you have room for:** take the higher-ATR names
first. Per trade, the higher-ATR half of each day's signals averaged +21.2%
against +14.4% for the lower half. At portfolio level the gain was small and
not reliable (see Step 5), so do not over-think the tie-break.

## Step 3 - Entry

The daily candle is published by Dhan the next morning, so a scan after the
close cannot see today's breakout. Two ways in:

| How | Average trade | Win rate |
|---|---|---|
| **Best:** run the scan at about 15:00-15:20 IST with "Scan against today's live price" on, and buy before the 15:30 close | +19.5% | 44% |
| Scan the next morning after 09:00 IST and buy at the open | +17.2% | 42% |

If the stock gaps up hard the next morning, the entry is further from the
stop. Recompute the size (Step 4) at the actual fill price.

## Step 4 - Stop and position size

- **Initial stop = entry - 3 x ATR(14).** The scanner shows it in the stop
  column. For these signals it is typically 9-14% below entry (median 10.8%).
- **Risk 1% of capital per trade**: position value = 1% of capital divided by
  the stop distance. With a 10.8% stop that is about a 9% position.
- **Cap any one position at 25% of capital.**
- Place the stop as a stop-loss order. It is hit intraday. If the stock gaps
  below it, the fill is the open.

Do not tighten it. The median winner fell 17% from a high during its run
(about 5.5 x ATR), and 24 of the top 25 gainers closed below their 21-day
EMA at least once. 2 x ATR, 8% and 21-EMA stops threw most winners out.

## Step 5 - How many positions

₹10,00,000, 1% risk per trade, 0.4% round-trip costs, all S6 signals from
January 2022 to 25 September 2026:

| Max open positions | Final value | CAGR | Worst drawdown | 2025 |
|---|---|---|---|---|
| 5 | ₹19.2 lakh | 14.8% | -12.9% | +1.9% |
| 8 | ₹22.4 lakh | 18.7% | -12.3% | +1.2% |
| 10 | ₹27.4 lakh | 23.8% | -14.6% | +7.3% |

More slots took more of each breadth surge. Returns are lumpy: 2023 made
most of the money and 2025 made almost nothing. Expect long flat stretches
while breadth is low.

## Step 6 - Managing the trade

- **No profit target.** Winners are held a median of 140 sessions (about
  seven months). Losers are out in a median of 24.
- **Trailing exit:** after each close, track the highest close since entry.
  Exit at the close on the first day the stock closes **20% or more below
  that high**.
- The initial stop stays in place the whole time. The trail usually passes it
  once the stock is up about 12%.
- Do not add to, average down on or partially sell an S6 position. None of
  that was tested.

## Step 7 - Exit and what to expect

Out of 649 S6 trades from 2022 to 2026 (entry at the signal-day close):

| Exit | Share of trades | Average return | Median days held |
|---|---|---|---|
| Initial stop | 44% | -11.1% | 17 |
| 20% trailing stop | 52% | +42.4% | 127 |
| Still open on 25 Sep 2026 | 4% | +62.2% | 108 |

Overall: 44% win rate, +19.5% average trade, and the average winner is about
five times the average loser. Most trades lose. The system works because
the few that run are allowed to run.

## Step 8 - Review

The daily job now paper-trades S6 signals automatically as forward tests
(strategy label `S6_BREAKOUT`), with the same stop and 20% trail. Compare live
results with the table above every quarter:

- Win rate far below 40%, or the average loss well beyond -11%, means
  something has changed. Stop trading S6 with real money and re-test.
- Only judge it across a breadth cycle, not a few weeks. Signals come in
  bursts.

## Limits

- The stock list is today's Nifty 500, so stocks that grew into the index are
  over-represented in the early years. 2025-26 is the fairer guide.
- Costs are an estimate (0.4% round trip). Slippage on gap-downs through the
  stop is modelled only at the open.
- Daily price and volume only. Results, news and fundamentals are not used.
