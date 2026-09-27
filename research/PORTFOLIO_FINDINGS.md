# Portfolio replay of S4/S5/S6, with Indian costs (27 Sep 2026)

Tools: `backend/app/engine/portfolio_bt.py` (engine) and
`scripts/portfolio_backtest.py` (command line). Trades come from the engine's
own replays: S6 `run_s6_backtest`, S5 `run_s5_pocket_pivot_backtest`, S4
`run_raw_signal_backtest`. S4 and S5 pass through the live entry filter as it
stood on each signal day (`historical_entry_verdict`). Trades collected from
Jan 2022 to 25 Sep 2026: S4 325, S5 1,364, S6 649. S4 has no signals before
Oct 2022, because it needs long monthly history.

## Costs

`IndianDeliveryCosts`, FY2025-26 rates, each a field:

- STT 0.1% on each side
- NSE transaction charge 0.00297%
- SEBI fee Rs 10 per crore
- stamp duty 0.015% on the buy
- GST 18% on the fees
- DP charge Rs 12.5 + GST per sell
- zero delivery brokerage (Dhan)
- slippage 0.10% on each fill, on top of stops already filled at the open when
  a stock gaps through them

On a Rs 1 lakh position a round trip costs about 0.44% with slippage, 0.24%
without.

## Rs 1,00,000 from Jan 2022, 1% risk per trade, whole shares

| Setup | Final | CAGR | Worst drawdown | Trades | Win % | Costs paid | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|---|---|
| S4 only, 10 slots | 1,44,315 | 8.1% | -8.7% | 69 | 46 | 3,565 | -3.1% | +11.8% |
| S5 only, 10 slots | 3,21,303 | 28.0% | -36.7% | 459 | 35 | 26,704 | +9.3% | +42.1% |
| S6 only, 10 slots | 2,62,229 | 22.6% | -10.6% | 70 | 47 | 3,207 | +6.6% | +23.5% |
| S4+S5 shared, 10 slots | 3,88,980 | 33.3% | -36.6% | 465 | 38 | 30,285 | +11.0% | +41.0% |
| S4+S5+S6 shared, 10 slots | 3,34,930 | 29.2% | -35.8% | 437 | 36 | 25,225 | +7.7% | +44.2% |
| Separate money, 1/3 each, 4 slots each | 1,72,143 | 12.2% | -14.7% | 323 | 44 | 10,286 | +4.0% | +9.8% |
| Separate money, S5 50% / S6 50%, 5 slots each | 2,24,373 | 18.7% | -22.9% | 341 | 43 | 15,352 | +4.5% | +11.8% |

What this changes:

- **One shared pool beats separate money per strategy.** Splitting capital
  left the quiet strategy's share idle while the busy one was capped. An
  earlier, rougher simulation in this conversation suggested splitting; this
  replay says not to.
- **S6 alone has by far the best return for its risk:** 22.6% a year for a
  -10.6% worst drop. Everything that includes S5 runs about -36% at its worst.
- **Costs matter mainly for S5.** 459 trades paid about Rs 26,700, and they
  pull its win rate from 45% to 35%. S4 and S6 trade rarely and barely notice.
- The S5 figures for 2022-24 are optimistic by an unknown amount: its early
  edge halves when restricted to stocks that were already large at the time
  (research/SURVIVORSHIP.md).

## A market filter for S5 (tested, not adopted)

S5's worst stretch was 2022. The question was whether trading it only in
healthy markets fixes that. Thresholds were judged on 2022-24 and confirmed
on 2025-26.

| S5 filter | Trades 2022-24 | Avg % 2022-24 | Trades 2025-26 | Avg % 2025-26 |
|---|---|---|---|---|
| none | 853 | 3.04 | 511 | 2.45 |
| Nifty 500 above its 200-day SMA | 628 | 4.22 | 136 | 0.78 |
| Nifty 500 above its 50-day SMA | 468 | 4.29 | 151 | 2.48 |
| breadth >= 0.3 | 416 | 3.97 | 94 | 3.07 |

Portfolio effect, costs on:

| Filter | S5 only CAGR / drawdown | S4+S5 CAGR / drawdown |
|---|---|---|
| none | 28.0% / -36.7% | 33.3% / -36.6% |
| Nifty 500 above its 200-day SMA | 24.4% / -28.4% | 26.1% / -24.0% |
| breadth >= 0.3 | 14.5% / -33.3% | 21.9% / -39.0% |

The 200-day filter does what it looks like it should on 2022-24: it turns 2022
from -19% into +5% and cuts the worst drawdown by a third. It fails the
out-of-sample check, though: in 2025-26 its trades averaged +0.8% against
+2.5% unfiltered, and it gives up 4-7 points of CAGR. S5's rules are
therefore unchanged. If a smaller drawdown matters more than return to you,
it is a reasonable personal choice. To see its effect, pass only the
qualifying S5 trades to `run_portfolio`; the tool does not have a switch for
it.
