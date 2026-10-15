# Step 17: adding shorts to the crypto trend book (14 Oct 2026)

The owner asked for short trades as well as buys. The forex book (liquidity B)
already trades both ways. The crypto/gold trend book (T1, step 14) was long only.

## What was tested

The step 14 grid (`scripts/research/search_trend_grid.py`, real 5-minute prices Aug 2021 -
Oct 2026, crypto fees and funding) already holds every channel/stop/trend-filter
configuration as long-only and as long+short. The short side alone is the
difference between the two.

- **T1's own channels, no filter** (short below the 40-bar low, cover above the
  30-bar high): -0.11R a trade in 2021-24 (216 trades), +0.12R in 2025-26.
  This fails the evidence rule.
- **Forex and gold shorts** lose in most configurations, so they are not added.
- **Choosing on 2021-24 only**, with step 14's rule (3 of 4 years positive), on
  BTC, ETH and SOL: one configuration of 250 qualifies.

| short rule | 2021-24 | 2025-26 (hold-out) |
|---|---|---|
| sell after a 4h close below the 20-bar low, only while the daily close is below its 100-day average; stop 1.5 ATR above; buy back after a 4h close above the 10-bar high | 153 trades, +0.19R | 111 trades, +0.18R |

R by year: 2021 -8, 2022 +31, 2023 +1, 2024 +5, 2025 -13, 2026 +32. The
shorts earn in falling markets: 2022 and 2026.

## Combined with the long side (one position per market)

The live code (`backend/app/tasks/trend_paper.py`) was replayed bar by bar over
the same history (`scripts/research/trend_live_check.py`). Shorts never blocked a long:
long trades are identical with and without them.

| | 2021-24 | 2025-26 |
|---|---|---|
| longs (unchanged) | 234 trades, +1.18R, +275R | 122 trades, +0.60R, +74R |
| shorts (BTC, ETH, SOL) | 150 trades, +0.17R, +25R | 104 trades, +0.17R, +18R |

Sequential Rs 10,000 at 1% risk (grid engine, spot gold):

| | 2021-24 | 2025-26 | max drawdown |
|---|---|---|---|
| long only | Rs 1,28,375 | Rs 21,674 | 30% |
| long + short | Rs 1,59,972 | Rs 27,401 | 30% |

By year, the long+short book makes 2022 +14R instead of -18R, and 2026 +60R
instead of +23R.

## Verdict

Adopted for the paper book from 14 Oct 2026. The book restarts under the new
RULES; no position was open, so nothing was lost. The short edge is thin
(+0.17R a trade) and comes mainly from bear phases. It was chosen among 250
configurations, so its hold-out result matters more than its 2021-24 one.
