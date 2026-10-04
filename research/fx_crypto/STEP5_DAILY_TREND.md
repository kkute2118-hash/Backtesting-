# Step 5: daily trend strategy for crypto and gold perpetuals (4 Oct 2026)

scripts/daily_trend_study.py. BTC, ETH, SOL, BNB, XRP (Binance USD-M perps,
real funding) and gold (Dukascopy spot for XAUUSDT, 0.01%/8h funding). Taker
0.05% + 18% GST + 0.01% slippage a side. Signal at the daily close, entry
at the next open, stops on daily highs/lows (a gap exits at the open).

## Grid (28 variants), average R a trade, 2021-24 / 2025-26

- Donchian 20/10: +0.29..+1.07R / −0.01..+0.24R
- **Donchian 55/20 (the Turtle system's textbook parameters): +0.66..+1.51R /
  +0.51..+1.68R, positive in all 8 variants in both periods**
- Donchian 100/50: best in 2021-24 (+1.5..+2.9R) but **negative in 2025-26**
  (−0.1..−0.4R): picking the best of the grid would have failed
- Daily liquidity run (close through the prior week's high/low, strong body,
  stop beyond the run candle): +0.63..+1.28R / +0.06..+0.27R

## Chosen: 55/20, 2-ATR stop, 200-day trend filter, long only

Long only and the trend filter were chosen on 2021-24 (shorts −0.10R there);
the 55/20 and 2-ATR values are the Turtle system's, not fitted here.

| | 2021-24 | 2025-26 |
|---|---|---|
| trades | 52 | 18 |
| win rate | 31% | 39% |
| average | +1.51R | +1.68R |
| profit factor | 3.5 | 3.8 |

Median stop 7.7% of price, median hold 28 days, cost about 0.1R a trade.
The five best trades are about 90% of the total R: like every trend system,
it lives on a few large wins; most trades lose small.

## Rs 10,000 account (positions at once across six markets, compounding)

| risk a trade | pre-tax | after 30% tax on each win, no loss set-off | worst drawdown | peak exposure |
|---|---|---|---|---|
| 1% | Rs 23,911 | Rs 16,920 | −12% / −13% | 1.1x equity |
| 2% | Rs 43,424 | Rs 24,526 | −23% / −25% | 2.3x equity |

No leverage is needed at 1% risk. For comparison, holding from July 2021:
BTC x2.84 with a −77% drawdown, gold x2.29 with −27%. The strategy earns less
than holding the best asset but with a fraction of the drawdown, on any of
the six, long only.
