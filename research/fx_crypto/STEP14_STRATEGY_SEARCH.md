# Step 14: search across the liquidity framework and trend breakouts (4 Oct 2026)

Real 5-minute prices, Aug 2021 to 2 Oct 2026, 8 markets (BTC, ETH, SOL perps
with real funding; spot gold; EURUSD, GBPUSD, USDJPY, AUDUSD at recorded
spreads). Crypto pays taker 0.05% + 18% GST + 0.01% slippage a side.
Candidates were chosen on 2021-24 only (enough trades, 3 of 4 years positive,
ranked by R a year); 2025-26 was looked at only afterwards.

Scripts: `search_trend_grid.py` (1,296 Donchian configs: 4h/daily,
18 entry/exit channel pairs, stop 1.5/2/3 ATR, trend filter none/100d/200d,
market/limit entry, long or long+short), `search_liquidity_runs.py` (the
framework engine, 16 variants: intraday/swing timeframes, limit/LTF entry,
min R:R 1.5/2, stop buffer 0.10/0.25), `search_strategies.py` (every filter
combination on the recorded setups: event family, score floor 0/55/65/75,
session, HTF alignment, strong MSB, FVG, premium/discount; six market
groups), `search_finalists.py` (Rs 10,000 accounts).

50,718 candidates; 5,184 qualified on 2021-24; 77% of those were also
positive in 2025-26.

## Leaders (chosen on 2021-24)

| | 2021-24 | 2025-26 (hold-out) |
|---|---|---|
| **T1 trend: 4h, 40-bar high in, 30-bar low out, 1.5 ATR stop, no trend filter, long, market entry; BTC ETH SOL gold** | 232 trades, +1.30R | 122 trades, +0.72R |
| L1 liquidity: intraday, run then retest, limit entry, R:R 1.5, London + NY hours; fx + gold | 1,744 trades, +0.19R | 814 trades, +0.12R |
| T0 today's live rules (4h 55/20, 2 ATR, 200-day filter), same engine | 147 trades | 59 trades |

T1's neighbours (30/20, 40/20, 55/50, 80/50 with 1.5 ATR) rank next to it: a
plateau, not a single lucky setting. The tighter 1.5 ATR stop and dropping the
200-day filter were the two largest improvements over today's rules. Score,
FVG and premium/discount filters did not improve the liquidity framework
(section 29: their weight drops); the run-then-retest family in London/NY
hours carries its whole edge, as in steps 1-3.

## Rs 10,000 account, compounding, overlapping positions

| system | risk | 2021-24 | 2025-26 | whole period | max drawdown |
|---|---|---|---|---|---|
| T1 trend | 1% | Rs 81,872 | Rs 20,624 | Rs 1,68,849 (73%/yr) | 30% |
| T1 trend | 2% | Rs 2,65,144 | Rs 33,836 | Rs 8,97,147 | 52% |
| T0 today's rules | 1% | Rs 24,302 | Rs 15,213 | Rs 36,970 (29%/yr) | 15% |
| L1 liquidity | 1% | Rs 1,64,246 | Rs 22,711 | Rs 3,73,023 | 51% |
| T1 + L1 | 1% | Rs 10,79,728 | Rs 43,545 | Rs 47,01,659 | 53% |

T1 by year: 2021 +21R, 2022 -18R, 2023 +195R, 2024 +103R, 2025 +65R, 2026
+23R; 26% of trades win. L1: a 67R drawdown and 14 losses in a row in
2025-26; GBPUSD lost in 2025-26.

## Verdict

**T1 is the best tradeable strategy**: highest return for its drawdown in
both periods, positive in 5 of 6 years, on markets an Indian resident can
trade on crypto exchanges. Use 1% risk (30% drawdown) rather than 2% (52%).
L1 has a real but thin edge, a 51% drawdown at 1% risk, and needs forex
pairs that Indian residents may trade only on Indian exchanges (NSE/BSE),
where hours and costs differ from this test. Not adopted for live trading.

Caveats: best of 50,718 candidates, so 2021-24 figures flatter it; judge it by
2025-26. Long only: it lost in the 2022 bear market. Account returns assume
fills at the next 4h open and no exchange outage.
