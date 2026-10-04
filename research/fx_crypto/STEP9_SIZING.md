# Step 9: market entry and position sizing for the 4h trend strategy (5 Oct 2026)

The live strategy switched from a limit at the broken high to a market buy at
the next 15-minute open after the 4h breakout close (the owner's choice;
2021-24 / 2025-26: +0.83R / +0.57R a trade against +0.96R / +0.38R). A
bar-by-bar replay of 2025-26 through backend/app/tasks/trend_paper.py enters
the same 97 trades at the same times as scripts/trend_4h_study.py.

313 trades, Jul 2021 - Oct 2026, 30% winners. Longest winning streak 5,
longest losing streak 14. Stop distance median 3.1% (0.6% to 11.2%). Up to 6
positions at once. Worst trade −9.9% of its position (a gap through the stop),
best +293%.

## Rs 10,000, full compounding, after all charges, no tax

Risk a % of the whole account per trade (position = risk / stop distance):

| risk | end | worst fall | peak total leverage | worst trade (of account) |
|---|---|---|---|---|
| 1% | Rs 57,437 | −22% | 3.7x | −1.6% |
| **2%** | **Rs 1,56,879** | **−40%** | **7.4x** | **−3.2%** |
| 3% | Rs 2,79,321 | −54% | 11.1x | −4.8% |
| 5% (best result) | Rs 3,92,771 | −74% | 18.4x | −8.0% |
| 7.5% | Rs 2,17,382 | −88% | 27.6x | −13.2% |
| 10% | Rs 52,349 | −95% | 36.9x | −20.6% |
| 15% | Rs 302 | −100% | 56.5x | −46.1% |
| 20% and more | wiped out | | | |

Whole account times a fixed leverage on every position: 1x Rs 3,69,575
(−56%, up to 6x total), 2x Rs 4,01,623 (−84%), 3x Rs 83,253 (−96%), 5x and
more wiped out.

A cap of 5x per position changes nothing up to 3% risk and slightly lifts 5%
(Rs 4,17,616, −72%); it stops a tiny stop (0.6%) from becoming a 30x position.

The largest result in hindsight (5% risk) needs sitting through a 74% fall;
the "best" risk level is also fitted to this one history, so the real optimum
is lower. Falls are measured on closed trades only; with open positions
marked to market they are deeper.

Paper book (live): 2% risk a trade, at most 5x per position.
