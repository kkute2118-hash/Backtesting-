# Step 4: swing mode, and gold on crypto-exchange perpetuals (4 Oct 2026)

Owner's choice: trade global gold like crypto (exchange perpetuals), not MCX.

## Gold perpetuals on Binance (scripts/fetch_fx_crypto.py --only)

| perp | since | premium to spot (median, 5-95%) | 1h return corr | daily turnover |
|---|---|---|---|---|
| XAUUSDT | Dec 2025 | +0.065% (−0.06..+0.16%) | 0.991 | ~$970M |
| PAXGUSDT | Mar 2025 | +0.060% (−0.29..+0.58%) | 0.983 | ~$70M |
| XAUTUSDT | Mar 2026 | −0.229% (−0.55..+0.03%) | 0.994 | ~$30M |

XAUUSDT tracks spot gold closely, so 2021-26 Dukascopy spot with perp fees
stands in for it. Fees used: taker 0.05% + 18% GST + 0.01% slippage a side,
maker 0.02% + GST, funding 0.01% per 8 hours held.

## Swing mode (4h regime, 1h setups, 15m entries; scripts/liquidity_swing_runs.py)

Continuation (run → retest), average R per trade, 2021-24 / 2025-26:

| | before costs | taker fees | maker entries |
|---|---|---|---|
| gold, limit entry | +0.10 / +0.41 | −0.72 / −0.17 | −0.34 / +0.11 |
| gold, LTF entry | +0.36 / +0.47 | −0.39 / +0.09 | n/a |
| crypto, limit entry | +0.13 / +0.14 | −0.04 / −0.12 | +0.04 / +0.00 |
| crypto, LTF entry | +0.15 / +0.24 | −0.00 / +0.01 | n/a |

Reversals lose in every variant. Gold's stops stay small even on 1-hour
structure (median 0.22-0.34% of price) against a 0.14% taker round trip.
Restricting to trades whose cost is a small share of risk makes results
worse, not better: the edge sits in the tight-stop trades.

## Intraday strategy B on gold with perp fees

Limit entry and limit target (maker), stops and time exits at market:

| fee schedule | cost a trade | 2021-24 | 2025-26 |
|---|---|---|---|
| maker 0.02% / taker 0.05% | 0.65R | −0.33R | −0.24R |
| maker 0.01% / taker 0.04% | 0.49R | −0.10R | −0.04R |
| maker 0% / taker 0.05% | 0.46R | −0.04R | +0.00R |
| spread-based (Dukascopy) | ~0.13R | +0.34R | +0.38R |

## Conclusion

The framework's measured edge (a few tenths of R before costs) survives only
where a round trip costs about a tenth of the stop: spread-based execution
at raw spreads. On crypto-exchange perpetuals, gold or crypto, at any of
these timeframes, percentage fees remove it. Not adopted for perps.
