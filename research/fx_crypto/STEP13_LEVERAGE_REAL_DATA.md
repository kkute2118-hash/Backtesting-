# Step 13: the live book's leverage tiers, tested on real prices (4 Oct 2026)

`scripts/trend_leverage_study.py` runs the live paper book's own code
(`backend/app/tasks/trend_paper.py`: `indicators` and `advance`, retest entry,
2 ATR stop, 20-bar-low exit, its charges) bar by bar over real 5-minute history
(release `fx-crypto-data`, Aug 2021 to 2 Oct 2026). Spot gold (XAUUSD) stands
in for the XAUUSDT perpetual, whose history starts Dec 2025. USDCAD is not in
the release and is untested. Selection period 2021-24, hold-out 2025-26.

## The assumed win rates are not real

The tiers in `trend_paper.WIN_RATES` (37-42%, from a step the code itself labels
synthetic) give BTC 6x, EURUSD 6x, AUDUSD 3x, the rest 5x; no market reaches 8x.
Real win rates of the same rules:

| market | trades | win % 2021-24 | win % 2025-26 | assumed | avg R (after charges) | avg R before charges |
|---|---|---|---|---|---|---|
| BTCUSDT | 46 | 30.0 | 12.5 | 42 | +0.58 | +0.70 |
| ETHUSDT | 45 | 22.2 | 33.3 | 40 | +0.03 | +0.11 |
| SOLUSDT | 33 | 50.0 | 44.4 | 38 | +1.26 | +1.34 |
| Gold (XAUUSD) | 52 | 25.7 | 23.5 | 39 | +0.44 | +0.76 |
| EURUSD | 36 | 28.6 | 6.7 | 41 | -0.85 | -0.27 |
| GBPUSD | 39 | 20.0 | 14.3 | 39 | -0.77 | -0.22 |
| USDJPY | 51 | 37.1 | 18.8 | 38 | -0.08 | +0.62 |
| AUDUSD | 47 | 26.3 | 14.3 | 37 | -0.70 | -0.26 |

Forex loses before charges on EUR, GBP and AUD in both periods; on USDJPY the
charges (the crypto fee model applied to a 0.5% stop) take the whole edge.

## Leverage caps, all 8 markets, Rs 1 compounding in exit order

| sizing | 2021-24 | 2025-26 | all | max drawdown (all) | peak open exposure |
|---|---|---|---|---|---|
| live tiers | 1.79x | 0.33x | 0.59x | 77% | 19x equity |
| tiers from real 2021-24 win rates | 2.02x | 0.40x | 0.80x | 71% | 14x |
| flat cap 1x | 2.96x | 0.63x | 1.86x | 45% | 6x |
| flat cap 5x | 1.76x | 0.31x | 0.55x | 78% | 19x |
| no cap (2% risk only) | 1.62x | 0.30x | 0.48x | 80% | 22x |

Higher caps are worse because the cap only binds on forex (stops near 0.5%, so
2% risk needs 4x), and forex loses. On crypto the 2% risk rule already gives
positions under 1x (stops 2-6%), so the cap never binds there.

## Crypto and gold only

| sizing | 2021-24 | 2025-26 | all | CAGR | max drawdown |
|---|---|---|---|---|---|
| live tiers | 3.47x | 1.14x | 3.95x | 31% | 44% |
| flat cap 1x | 3.55x | 0.88x | 3.13x | 25% | 40% |

The difference is gold, the only one where the cap binds (stop near 1%).

## Verdict (evidence rule: chosen on 2021-24, holds on 2025-26)

- Dynamic leverage tiers: **not adopted**. Their win rates are not real, and no
  tiering chosen on 2021-24 made money in 2025-26.
- Forex in this strategy: **drop it**. Negative in 2021-24 (except JPY before
  charges) and negative in 2025-26 on all four pairs; it is what leverage
  magnifies into the 70-80% drawdowns.
- Crypto + gold with 2% risk: positive over the whole period, but 2025-26 is
  roughly flat and the drawdown is 40-44%. Paper-trade it before real money.

Drawdowns are measured on closed trades; open-trade swings make them deeper.
