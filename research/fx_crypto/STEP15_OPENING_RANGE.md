# Step 15: Opening-range breakout (the owner's idea, 12 Oct 2026)

**Idea.** After a market opens, the first 15-minute candle sets a range. A break
above it is a buy, a break below a sell. Stop at the candle's far end, or at
its middle (50%).

**Test.** `scripts/search_orb.py` on real 5-minute prices, Jan 2021 - Oct 2026:
EUR/USD, GBP/USD, USD/JPY, AUD/USD, gold (Dukascopy, recorded spreads) and
BTC, ETH, SOL perpetuals (Binance, 0.05% taker + GST + slippage).

- Opens: London 08:00, New York 08:00 and 09:30, Tokyo 09:00, India 09:15, and
  00:00 UTC for crypto.
- Entry: on the touch (a stop order at the edge), or after a 15-minute close
  beyond it.
- Stop: the far edge, or the middle.
- Exit: 1R, 1.5R, 2R or 3R target, or an 8-hour hold.
- Filter: all trades, or only those whose cost is under 1/3 R.
- One trade per open. When a 5-minute bar spans both the stop and the target,
  the stop is counted.

Evidence rule: choose on 2021-24, check on 2025-26.

## Result: it does not work as a general strategy

- 1,670 variants have enough trades (150+ in 2021-24, 50+ in 2025-26).
  Only **45** made money in 2021-24, and **23** in both periods.
- **The 50% stop loses everywhere.** It is worse than the edge stop for every
  market and open. The tighter stop triples the stop-outs, and costs grow
  relative to the smaller risk.
- **Crypto loses heavily.** For example, BTC at New York 09:30 with a 2R target
  averaged -0.31R in 2021-24 and -0.41R in 2025-26. A 15-minute crypto range is
  small next to exchange fees: costs alone are about a third of the risk.
- **Gold and EUR/USD, GBP/USD and AUD/USD** are flat to negative in at least
  one period.

## The one exception: USD/JPY, London 08:00

Rules: a 15-minute close beyond the opening candle, entry at the next open,
stop at the far edge, no target, closed after 8 hours, and skipped when the
cost exceeds 1/3 R.

| | trades | win | avg | Rs 10,000 at 1% risk | max drawdown | worst losing run |
|---|---|---|---|---|---|---|
| 2021-24 (chosen) | 1,010 | 32% | +0.12R | Rs 26,641 | 45% | 15 |
| 2025-26 (check) | 442 | 33% | +0.14R | Rs 16,475 | 26% | 11 |

Average R by year: 2021 -0.01, 2022 +0.23, 2023 +0.10, 2024 +0.16, 2025 +0.20,
2026 +0.07. Both directions contribute: shorts made +0.58R a trade in 2024,
so this is not just the yen's long fall.

USD/JPY with the other opens (New York 08:00, India 09:15, Tokyo) is also
positive in both periods, but weaker in 2025-26 (+0.05 to +0.09R) with
drawdowns up to 48%.

**Compared with what runs now:** liquidity strategy B averages +0.36R a trade
with a 17% maximum drawdown, and the crypto 4h breakout +0.72R in 2025-26.
The USD/JPY opening range earns less per trade with deeper drawdowns, but it
trades about 250 times a year.

**Verdict.** Do not replace the current strategies. The USD/JPY London version
passes the evidence rule and could run as a separate paper book; the owner
decides.

About 1,800 of 1.48 million simulated trades (0.1%) had no recorded spread
and were left out.
