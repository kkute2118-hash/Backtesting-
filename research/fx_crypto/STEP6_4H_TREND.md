# Step 6: 4-hour trend with 15-minute entries, and the Oracle paper book (4 Oct 2026)

scripts/trend_4h_study.py. Same six markets, fees, GST and funding as step 5.
Signal: 4h close above the previous 55 (or 20) 4h highs, last completed daily
close above its 200-day average, long only. Stop 2 ATR(4h); exit on a 4h close
below the previous 20 (or 10) 4h lows. Entries executed on 15-minute bars.

| variant | 2021-24 | 2025-26 |
|---|---|---|
| 55/20, market at the next 4h open | +0.83R (216) | +0.57R (97) |
| **55/20, limit at the broken high for 24h (chosen on 2021-24)** | **+0.96R (199)** | **+0.38R (93)** |
| 55/20, 15m micro-MSB after the retest | +0.71R (209) | +0.36R (97) |
| 20/10, any entry | +0.16..+0.25R | +0.21..+0.32R |

Median stop 3.1% of price, cost about 0.07R a trade, about 56 trades a year,
31% winners, median hold 4 days.

## Rs 10,000 after all charges, no tax (chosen variant)

| risk a trade | end (Jul 2021 - Oct 2026) | a year | worst drawdown | peak exposure |
|---|---|---|---|---|
| 1% | Rs 53,072 | ~38% | −24% | 3.7x equity |
| 2% | Rs 1,38,514 | ~66% | −43% | 7.3x |
| 3% | Rs 2,43,812 | ~85% | −58% | 11x |

2025-26 alone at 2% risk: Rs 10,000 → Rs 15,017 (worst drawdown −22%). Most
of the full-period gain came in 2024's crypto rally (Rs 15.5k → Rs 40.7k at
1%); 2026 so far is slightly negative.

## Live paper book on Oracle

backend/app/tasks/trend_paper.py, every 15 minutes (ati-lab-trend.timer),
report at /reports/trend.html. Replaying 2025-26 bar by bar through it gives
the same trade count as the backtest on five of six markets and average R
within about 0.1R (the rest are the same trades filled hours apart).
