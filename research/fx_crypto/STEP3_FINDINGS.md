# Step 3: real fills, real Indian costs, live paper trading (4 Oct 2026)

Strategy B (STEP2_FINDINGS.md): forex + gold, liquidity run → first retest of
the broken level, limit entry, entries 11:30-13:30 and 17:30-21:30 IST,
framework score >= 65.

## 1. Stricter fills

A limit order now fills only if price trades a margin *through* it (a buy
limit needs the ask, not the bid, to reach it). B, 2021-24 / 2025-26:

| fill rule | 2021-24 | 2025-26 |
|---|---|---|
| touch = filled (step 2) | +0.48R | +0.47R |
| **0.05 ATR through (realistic, adopted)** | **+0.39R** | **+0.32R** |
| 0.1 ATR through | +0.23R | +0.30R |
| 0.2 ATR through (harsh) | +0.13R | +0.06R |

Guard added: the stop must be at least three spreads away (cost ≤ 0.33R).
Neutral at bank spreads (+0.49/+0.46R), better at 3x spreads (+0.27/+0.23R
vs +0.22/+0.22R), and it removes setups nobody could trade.

## 2. Legal Indian venues

Charges used: Rs 20 brokerage per order, MCX CTT 0.01% on the sell side,
exchange 0.0021%, stamp 0.002% on the buy side, 18% GST on brokerage and
exchange fees; bid-ask Rs 1/gram on Gold Petal, Rs 0.3/gram on Gold Mini; 2
ticks on NSE cross-currency futures. Gold at Rs 11,700/gram.

MCX gold (open 9:00-23:30 IST, so both sessions), B's gold trades:

| account | risk | contract | cost a trade | result |
|---|---|---|---|---|
| Rs 10,000 | 1% | Petal (1 g) | 0.73R | **−0.11R** |
| Rs 10,000 | 2% | Petal | 0.46R | +0.10R (margin about the whole account) |
| Rs 50,000 | 1% | Petal | 0.31R | +0.24R |
| Rs 1,00,000 | 1% | Petal | 0.26R | +0.29R |
| Rs 5,00,000 | 1% | Mini (100 g) | 0.18R | +0.33R |

NSE cross-currency futures (EURUSD, GBPUSD, USDJPY; 1,000-unit lots; open
only to 19:30 IST, so half the New York window is lost): Rs 10,000 at 1%
−0.46R; Rs 1,00,000 at 1% +0.14R with a 2-tick spread, −0.24R at 4 ticks.

The flat Rs 20 per order is the problem: on a Rs 100 risk it is 0.4R before
anything else. With Rs 10,000 the edge does not survive Indian costs; on MCX
gold it starts to at about Rs 50,000.

## 3. Live paper trading

scripts/fx_paper.py + .github/workflows/fx-paper.yml: every 15 minutes,
10:30-22:30 IST on weekdays, the frozen rules run on fresh Twelve Data
candles (cost from the Dukascopy spread table,
research/fx_crypto/spread_by_hour.json). The book lives on branch `fx-paper`
(README.md, state.json); new pending limit orders and closed trades are
posted to the "FX paper trading" issue. Paper start 5 Oct 2026. Needs the
repository secret TWELVEDATA_API_KEY.

Replay check on stored data (1-25 Sep 2026): 4 paper trades, +11.1R; one
1-pip AUDUSD order correctly dropped by the spread guard.
