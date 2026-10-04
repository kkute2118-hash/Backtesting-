# Forex, gold and crypto: step 1 findings (4 Oct 2026)

Data: 5-minute history 2021-01 to 2026-10-02 (release `fx-crypto-data`):
EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD (Dukascopy, real BID/ASK spread) and
BTC, ETH, SOL, BNB, XRP perpetuals (Binance; 0.05% taker + 0.01% slippage a
side). Rules may be chosen on 2021-24; they must hold on 2025-26.

## Market structure (scripts/fx_structure_study.py)

- Intraday moves mean-revert: variance ratio below 1 from 15 minutes to 4
  hours on every symbol, in both periods. Crypto most of all.
- A break of the prior day's high or low holds at the close only 44-59% of
  the time.
- Single concepts lose after costs on every symbol: fading a wick through a
  15-minute swing −0.15 to −0.33R a trade; following a close through it −0.01
  to −0.18R.
- Costs: one crypto round trip is 10-25% of a typical hourly range (taker
  fees); EURUSD and gold 1.5-5% in active hours.
- Biggest moves and lowest cost share: 17:30-21:30 IST (London/New York overlap)
  on every market.

## The owner's liquidity framework (backend/app/engine/liquidity_pa.py)

Every setup, after two look-ahead fixes (continuation stop from closed bars
only; a limit fill stopped inside its own bar counts as a loss):

| slice | 2021-24 | 2025-26 |
|---|---|---|
| all symbols, all hours (limit entry) | −0.05R fx/gold, −0.18R crypto | −0.09R, −0.27R |
| fx + gold, entries 17:30-21:30 IST, limit | **+0.12R**, 2,030 trades, PF 1.18 | **+0.08R**, 959 trades, PF 1.11 |
| same, run → S/R-flip retest only | **+0.19R** (1,100) | **+0.23R** (534) |
| same, sweep/grab reversals only | +0.05R (930) | −0.11R (425) |
| fx + gold overlap, LTF micro-MSB entry | +0.09R (526) | +0.14R (267) |

By year (fx + gold overlap, limit): +0.17, +0.18, +0.09, +0.07, +0.10, +0.06R.

- Gross edge exists almost everywhere (+0.06 to +0.20R before costs); crypto
  costs (0.31-0.43R a trade at 15-minute risk sizes) take all of it.
- Strong MSB beats weak MSB in both periods, as the framework says, but too
  few strong reversals at major levels to trade alone.
- The /100 score as written does not sort winners from losers (A+ was the
  worst grade). Its weights need refitting on 2021-24 (framework section 29).
- Premium/discount and HTF alignment did not help at this timeframe.

Next: step 2, refine the run → retest continuation in the overlap session on
gold and forex, refit the score weights on 2021-24, check 2025-26; test crypto
with maker (limit) fees and larger structures.
