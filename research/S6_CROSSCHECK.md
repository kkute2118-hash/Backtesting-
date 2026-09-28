# S6 cross-check, 28 Sep 2026

`scripts/s6_crosscheck.py` on the stored universe (485 stocks), signals
1 Jan 2022 to 28 Sep 2026, S6's own entry and exit, gross per closed trade.

## 1. The code matches the rules

`core.strategy6_features` / `strategy6_condition_matrix`:

- close above the highest **high** of the prior 50 sessions;
- more than 28 calendar days since the previous such close (re-arm);
- market breadth >= 0.50;
- ATR(14) >= 2.8% of price;
- at least 60% above the 52-week low;
- within 15% of the 52-week high.

Exit: stop at entry - 3 x ATR, trailing 20% below the highest close.

The live scan, `run_s6_backtest`, `historical_entry_verdict` and the page all
call these same functions.

**Page fix.** The watchlist on the page was wrong in two ways:

- it showed the breakout level of the last completed day, not of the next
  decision close;
- it counted the re-arm from the previous breakout, ignoring one on the
  latest bar.

ENGINERSIN showed "above 309.50, eligible 22 Oct" when it had broken out on
25 Sep; the real next level is 318.90, from 24 Oct. The fix is
`scripts/claude_dashboard.py:s6_next_decision`, and
`backend/tests/test_s6_watchlist.py` checks it against the engine on random
price histories.

## 2. The top gainers it was built from

The 30 biggest 1-year gainers to 28 Sep 2026:

- **7 were signalled.** The average trade was +21.4%, and 5 of the 7 are
  still open.
- **19 more passed every S6 stock rule** on 1 to 4 days during the year, but
  market breadth was below 0.50 each time. Breadth reached 0.50 on only 22 of
  246 sessions in the last year.
- **4 failed a stock rule.** WELCORP, SONACOMS and AEGISLOG broke out less than
  60% above their 52-week low; FEDERALBNK's ATR was under 2.8%.

For comparison, only 24 of the 485 stocks were signalled at all that year.
S6 therefore picks big movers about five times more often than chance (7 of 30
against 24 of 485). The stock rules recognise the stocks that go on to be top
gainers; the breadth gate is what kept most of them out last year.

The gate is still right on average. Without it, 2025-26 breakouts on
low-breadth days lost money: 198 trades averaging -3.9%
(research/STRATEGY_SHORTLIST.md). The top-gainer list is chosen with
hindsight; the trades a gate-free S6 would actually have taken include many
failures that are not on it.

## 3. Robustness: one notch either side of each setting

Average return per closed trade (number of trades):

| Setting | Down | Live | Up |
|---|---|---|---|
| Breadth 0.40 / **0.50** / 0.60 | 17.5% (767) · -1.3% (62) | 20.6% (590) · 2.3% (38) | 25.7% (426) · 3.1% (27) |
| ATR 2.3 / **2.8** / 3.3 % | 23.0% (702) · 1.1% (44) | 20.6% · 2.3% | 19.2% (409) · 7.8% (23) |
| Above 52w low 50 / **60** / 70 % | 20.2% (658) · 0.2% (48) | 20.6% · 2.3% | 20.7% (528) · 1.8% (31) |
| Below 52w high 10 / **15** / 20 % | 20.9% (562) · -3.2% (29) | 20.6% · 2.3% | 20.9% (605) · 2.2% (44) |
| Re-arm 21 / **28** / 35 days | 21.2% (744) · 3.4% (45) | 20.6% · 2.3% | 19.0% (490) · 3.7% (34) |

In each cell, the first figure is 2022-24 and the second is 2025-26.

- **Not fitted to noise.** Every variant earns 17-26% a trade on 2022-24. No
  setting sits on a knife-edge.
- **2025-26 is weak under every variant.** Plus 2 to 8% a trade on 23 to 62
  trades. The recent edge is small, and the sample is too small to tell the
  variants apart.
- **Breadth 0.60** is better in both periods, so it passes the evidence rule
  on its face. It was, however, the best of ten variants looked at together,
  and it cuts trades by a quarter. It is **not adopted**: it needs an
  account-level test and more 2025-26 trades first. Re-run this script
  quarterly.
- **Breadth 0.40** is the one change that clearly hurts: 2025-26 turns
  negative. It confirms that the gate matters.
