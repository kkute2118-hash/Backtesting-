# Which strategies to keep: S1-S6 on ₹1 lakh, with and without margin

Run 28 Sep 2026 on the database backup, trades from 1 Jan 2022 to 25 Sep
2026. Each strategy uses its own exits, the live entry filter and the data guard
replayed on the signal day (`portfolio_bt.collect_trades`). All accounts:
₹1 lakh, one pool, 10 slots, 1% risk per trade, 25% position cap, Indian
delivery costs. MTF: risk and cap scale with leverage, 12.5% a year interest
on borrowed cash charged daily, ₹20 pledge per buy, margin calls not modelled.
Scripts: `scripts/all_strategies_mtf.py`, `scripts/breadth_gate_study.py`.

## Account results

| Strategy | 1x final | 1x CAGR | 1x worst drop | 2x final | 2x CAGR | 2x worst drop | 4x final | 4x worst drop |
|---|---|---|---|---|---|---|---|---|
| S1 | ₹1.01 L | 0.1% | -49% | ₹0.32 L | -21% | -85% | ₹492 | -99.6% |
| S2 | ₹1.76 L | 12.7% | -31% | ₹2.38 L | 20.1% | -56% | ₹2.51 L | -88% |
| S3 | ₹1.39 L | 7.2% | -35% | ₹0.39 L | -18% | -79% | ₹88 | -99.9% |
| S4 | ₹1.43 L | 7.9% | -7% | ₹1.99 L | 15.6% | -15% | ₹3.16 L | -29% |
| S5 | ₹3.29 L | 28.6% | -37% | ₹4.40 L | 36.9% | -62% | ₹1.20 L | -93% |
| **S6** | **₹2.64 L** | **22.8%** | **-13%** | **₹4.58 L** | **38.0%** | **-22%** | ₹8.77 L | -42% |
| S4+S5+S6 (scanner today) | ₹3.34 L | 29.1% | -35% | ₹3.92 L | 33.5% | -61% | ₹3.54 L | -88% |
| **S4+S6** | **₹2.85 L** | **24.8%** | **-18%** | **₹5.14 L** | **41.4%** | **-34%** | - | - |

Yearly, 1x:

| Strategy | 2022 | 2023 | 2024 | 2025 | 2026 (to Sep) |
|---|---|---|---|---|---|
| S1 | -11.6% | +44.7% | +5.9% | -25.3% | -0.7% |
| S2 | +17.0% | +36.0% | +16.5% | -12.0% | +7.9% |
| S3 | +0.6% | +39.2% | +0.7% | -11.2% | +11.0% |
| S4 | +4.7% | +14.0% | +11.0% | -3.1% | +11.8% |
| S5 | -20.4% | +115.0% | +22.3% | +10.0% | +42.7% |
| S6 | +6.0% | +60.8% | +17.5% | +6.6% | +23.5% |
| S4+S5+S6 | -17.5% | +105.2% | +27.2% | +11.0% | +39.7% |
| S4+S6 | +9.6% | +69.9% | +29.0% | -1.7% | +20.7% |

## Reward to risk per trade (closed trades, R = profit / initial risk)

| Strategy | Trades | Win % | Avg R | Avg winner | Avg loser | Payoff (win/loss) | Avg hold |
|---|---|---|---|---|---|---|---|
| S4 | 304 | 52% | 0.92 | +2.66 R | -0.98 R | 2.7 : 1 | 35 days |
| S5 | 1,338 | 40% | 0.67 | - | - | - | 28 days |
| S6 | 628 | 43% | 1.76 | +5.26 R | -0.88 R | 6.0 : 1 | 138 days |

## Findings

- **S1 and S3 do not work.** Flat or barely positive in cash, with half the
  account lost at the worst point; any margin wipes them out. S2 is
  mediocre and lost 12% in 2025. All three are already out of the scanner.
- **S5 makes money only with large swings.** The highest cash return, but a
  -37% drop, a -20% year (2022), the lowest reward per trade (0.67 R), and
  the survivorship study found its edge only in stocks that stayed in the
  Nifty 500 (-0.2% per trade in those that dropped out). Adding it to S4+S6
  raises the return by about 4 points a year and doubles the worst drop
  (-18% to -35%).
- **S6 has the best reward to risk by a wide margin.** Winners average 5.3
  times the risk taken, losers lose 0.9 of it, and the account never fell
  more than 13%. Its return per unit of worst drop (22.8 / 12.9 = 1.8) is
  more than twice S5's (0.8). The survivorship study says to expect about
  15% per trade live, not 19%.
- **S4 is steady but small.** Few trades (about 15 a year after its filter),
  a 2.7 : 1 payoff and a -7% worst drop alone. With S6 it adds 2 points a
  year and 5 points of drawdown, and fills some of the time S6 waits for
  breadth. It lost money in 2025, as S6+S4 did (-1.7%).
- **Margin only suits S6 (and S4).** At 2x S6 keeps a -22% worst drop;
  S5 at 2x falls 62% at the worst point, and at 4x every strategy except S4
  and S6 is close to wiped out.

## Market breadth on S4 and S5

S6 buys only when market breadth is at least 0.50, which was true on 29% of
days since 2022. Per closed trade, by the breadth on the signal day:

| Strategy | below 0.25 | 0.25-0.50 | 0.50 and above |
|---|---|---|---|
| S4 | 41 trades, +0.2% (29% win) | 111, **+11.1% (69% win)** | 152, +4.8% (47% win) |
| S5 | 746, +1.9% | 350, +2.2% | 242, **+7.0%** |
| S6 without the gate | 324, +20.8% | 494, +8.9% | 628, +19.5% |

Split by period (evidence rule), average per trade:

| | 2022-24 | 2025-26 |
|---|---|---|
| S4, 0.25-0.50 | +15.3% (44) | +8.3% (67) |
| S4, below 0.25 | none | +0.2% (41) |
| S5, 0.50 and above | +7.1% (202) | +6.2% (40) |
| S5, below 0.50 | +1.9% (631) | +2.1% (465) |
| S6 without gate, below 0.50 | +19.5% (620) | -3.9% (198) |
| S6 with the gate | +20.6% (590) | +2.3% (38) |

- Applying the 0.50 gate to S4 and S5 cuts the account result: S4+S5+S6
  falls from 29.1% to 23.2% a year (worst drop -35% to -25%), because it
  removes most trades.
- S5 trades on high-breadth days make more than three times the rest in
  both periods. That passes the evidence rule, but it leaves only about
  eight S5 trades a year in 2025-26.
- S4 does best at middle breadth and has not worked below 0.25; that band
  has no 2022-24 trades, so it cannot be tested out of sample yet.
- S6's gate is what kept S6 positive in 2025-26: without it the low-breadth
  trades lost money there.
