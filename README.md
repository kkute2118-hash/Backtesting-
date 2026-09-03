🧠 Adaptive Trading Intelligence Lab
A Dhan-first, persistent-data trading research and decision-support system for Indian equities, with separate research engines for crypto and forex.
The system is designed around:
Exact strategy rules → candidate detection → quality scoring → risk/safety → forward testing → learning → improved candidate ranking
It is a research and decision-support system. It does not guarantee profits or automatically place real-money orders.
---
🚀 Core Architecture
Indian Equity Data
Primary market-data source:
Dhan API
Dhan instrument master
Dhan historical OHLCV
Dhan live market feed / WebSocket
Historical data is stored locally so the application does not repeatedly download the same data.
The intended workflow is:
```text
Dhan
  ↓
Persistent Local Data Store
  ↓
Precomputed Indicators
  ↓
Fast Scanner / Backtester
  ↓
Strategies 1–4
  ↓
Scoring + Safety
  ↓
Forward Testing
  ↓
Learning Engine
```
---
🕒 Data Freshness & Live Intraday Prices
Stored daily candles can never be newer than the last completed NSE session, so
a scan run during market hours was always evaluating yesterday's close. Two
layers fix that.

**1. Fast top-up.** `sync_latest_sessions()` requests only the last
`LATEST_SYNC_TAIL_DAYS` (10) calendar days per symbol instead of walking the
full 1000-day window, and it re-requests the newest already-stored bars. Without
that re-request a candle first written while its session was still open could
never be corrected: `MAX(dt)` had already moved past it, so the "download the
missing range" branch could not reach back. It is exposed as a button in both
the Daily Scanner and the Data Manager.

**2. Live intraday overlay.** While the cash session is open, the Scanner and
the Early Warning Radar can pull today's still-forming candle from Dhan's bulk
quote feed (`dhan_quote_snapshot`, one request per 1000 instruments) and merge
it into the daily history **in memory only**:

```text
stored daily candles (closed sessions)
        + today's forming bar (open/high/low/LTP/volume)
        = frame the strategies actually evaluate
```

A partial bar is never written to the `candles` table, and features derived from
one are never persisted to the feature-snapshot store, so backtests and research
continue to see completed sessions only.

The feature cache is keyed on last date **plus** row count **plus** last close.
Keying on the date alone silently reused stale features whenever a candle was
revised, or whenever today's forming bar moved.

---
📈 Live Forward-Test P/L
The persistent forward-test tracker shows a real current price and what the
position is actually doing:

| Column | Meaning |
| --- | --- |
| Current Price | live WebSocket tick, else a REST quote, else the last stored close |
| Gain/Loss % and ₹ | move against the recorded entry |
| Unrealized R | that move divided by the position's own risk (entry − stop) |
| To Target % / To Stop % | how far price still has to travel |
| Progress to Target % | share of the planned entry→target distance covered |
| Price Source / Price As Of | provenance, so a stale price is never mistaken for a live one |

Target and stop **resolution** still happens only on completed daily candles. A
live price touching a level raises an alert in this table; it does not close the
record.

---
🚨 Early Warning Radar
The Daily Scanner is binary: a stock is invisible until the day it passes every
rule of a strategy, which is usually the day the move has already started. The
radar answers the other question — which stocks are *about* to trigger.

`strategy_condition_matrix()` decomposes each strategy into its individual
conditions; ANDing them reproduces `strategy_signal()` exactly (verified across
43,200 bar/strategy evaluations). That decomposition is what lets the radar
report "7 of 9 rules pass, the blocker is Monthly RSI ≥ 50 and it is 3.6% away".

Alongside proximity it measures volatility compression, because expansion moves
follow contraction: range percentile against the stock's own 120-day
distribution, NR7, consecutive inside bars, 5-day vs 60-day range ratio, volume
dry-up, and distance from the 52-week high.

```text
Readiness = 55% proximity-to-trigger + 35% compression + regime adjustment
```

The radar changes nothing about S1–S4 qualification. It builds a watchlist.
Setting "how close" to 0 rules reproduces the normal scanner's qualified list
exactly.

---
⚡ Persistent Data & Fast Scanning
The application maintains a local historical-data cache.
When data already exists locally:
```text
Existing data → reuse
Missing data  → download only missing range
New data      → append/update cache
```
This prevents unnecessary repeated downloads from Dhan.
The architecture is designed to separate:
data acquisition
data storage
feature calculation
strategy evaluation
scoring
learning
so that expensive calculations do not need to be repeated unnecessarily.
---
📊 Strategies
The system currently evaluates four primary strategies:
Strategy 1
Strategy 2
Strategy 3
Strategy 4
The strategy rules are treated as the authoritative signal layer.
The learning engine does not silently modify the original strategy rules.
The hierarchy is:
```text
Strategy Rules
      ↓
Valid Signal
      ↓
Quality Score
      ↓
Risk / Safety
      ↓
Forward Test
      ↓
Learning
```
A stock does not qualify simply because it satisfies one attractive condition.
All mandatory conditions belonging to the selected strategy must be satisfied before the stock becomes a strategy candidate.
---
🎯 Multi-Timeframe Analysis
The equity engine uses:
Daily data
Weekly data
Monthly data
Indicators include:
EMA
SMA
RSI
ATR
Relative volume
Momentum
VWAP-derived measures
Higher-timeframe support/demand analysis
Price/volume footprint analysis
Historical calculations are designed to respect the information that would actually have been available at the historical date being tested.
This is important for avoiding look-ahead bias.
---
🏆 Setup Scoring
A qualifying setup receives a quality score.
The scoring framework considers components including:
Strategy quality
Higher-timeframe demand
Footprint
Trend
Entry quality
Relative strength
Market regime
Safety
The score is used for ranking and prioritisation.
A score is not a guaranteed probability of winning.
The dashboard should therefore present the strongest qualifying candidates first.
---
🛡️ Small / Micro Safety
Small and micro-cap safety is maintained as a separate risk layer.
It can evaluate characteristics such as:
traded value
liquidity
abnormal volatility
large gaps
circuit-like price behaviour
news/event risk
selected fundamental risk indicators
The safety engine can downgrade or reject a candidate.
It must not manufacture a strategy signal that does not otherwise exist.
---
🔬 Strategy 4 Recovery Study
Strategy 4 also contains a separate research-only Recovery Study.
The purpose is to study stocks that may exhibit:
```text
Large prior move
      ↓
Consolidation
      ↓
Controlled retracement
      ↓
Volatility / volume contraction
      ↓
EMA recovery / base reclaim
      ↓
Higher high / breakout confirmation
```
This study is intentionally kept separate from the exact Strategy 4 rules.
It is used to determine whether this additional market structure has a measurable historical edge.
The Recovery Study must prove itself through historical and forward testing before it is considered for integration into the primary Strategy 4 rules.
---
🔬 Backtesting
Backtesting is performed using downloaded/persisted market data wherever possible.
The research engine evaluates historical signals and then follows the subsequent price action to determine:
WIN
LOSS
TIMEOUT
Metrics include:
Number of trades
Win rate
Average return
Average R multiple
Profit factor
Maximum win
Maximum loss
Average holding period
Strategy breakdown
Score breakdown
The backtest should distinguish between:
```text
Signal generation
and
Trade outcome
```
so that the learning engine can analyse what characteristics were associated with successful and unsuccessful setups.
---
🧠 Market Learning
The learning engine is designed to learn from historical and forward-tested trades.
Learning dimensions include:
Strategy
Setup score
Strategy component scores
Higher-timeframe conditions
Footprint
Entry quality
Safety
Market regime
Outcome
R multiple
Holding period
The purpose is not to randomly change strategy rules.
Instead, the system should learn:
> Which types of valid setups historically produced better outcomes?
This information can then improve ranking and candidate selection.
---
🔭 Forward Testing
Forward testing is maintained separately from historical backtesting.
A forward-test candidate can be tracked through:
```text
Signal
↓
Entry
↓
Live price
↓
Maximum favourable excursion
↓
Maximum adverse excursion
↓
Exit
↓
R result
↓
Learning database
```
Forward testing is important because it provides a reality check against historical backtest results.
---
⚡ Live Monitoring
The live monitoring layer uses Dhan's live market feed where configured.
The objective is to monitor selected forward-test candidates without repeatedly downloading complete historical datasets.
The live layer should focus on:
Current price
Entry status
Stop status
Target status
MFE
MAE
Exit condition
Forward-test status
Real-money order execution remains disabled unless explicitly implemented and authorised.
---
💎 Fundamentals
Fundamental analysis is intentionally separated from the primary technical scan.
The preferred workflow is:
```text
Technical scan
      ↓
Shortlist
      ↓
Fundamental enrichment
      ↓
Risk review
      ↓
Final candidate ranking
```
This prevents expensive fundamental/API requests from slowing down the entire market scan.
---
📰 News / Event Risk
News and event information may be used as an additional risk layer.
News should not automatically create a trading signal.
Instead it can be used to:
identify event risk
identify unusual developments
downgrade risky candidates
provide additional context for forward testing
---
🪙 Crypto & Forex Research
Crypto and forex are maintained as separate research engines.
The current application includes Twelve Data connectivity for historical/current market data where configured.
Crypto research can also use CCXT-supported exchanges.
The objective is to build a separate learning dataset for crypto rather than assuming that Indian-equity strategy rules automatically work in crypto.
The research process is:
```text
Historical market data
        ↓
Pattern discovery
        ↓
Strategy hypothesis
        ↓
Backtest
        ↓
Walk-forward test
        ↓
Forward test
        ↓
Learning
```
No crypto strategy should be accepted merely because it produces a high historical return.
---
⚠️ Data Quality Principles
The system should prioritise:
No look-ahead bias
No repeated use of future information
Persistent historical data
Realistic transaction costs
Slippage assumptions
Liquidity awareness
Forward testing
Drawdown analysis
Out-of-sample validation
Avoiding overfitting
Historical results are research results, not guarantees of future performance.
---
📈 Portfolio & Risk
The research architecture can evaluate:
Position sizing
Capital allocation
Number of simultaneous positions
Compounding
Portfolio drawdown
Strategy diversification
Capital constraints
The system should optimise for risk-adjusted expectancy, not simply the highest historical return.
---
🧪 Research Philosophy
The application should behave as an independent research advocate rather than a trade-confirmation machine.
If the evidence is weak:
```text
NO TRADE
```
is a valid result.
The system should not search for reasons to justify a trade merely because a user wants to trade.
---
🔐 Safety
This application is for research and decision support.
Real-money trading is disabled by design unless separately implemented and explicitly enabled.
Users should independently verify:
data quality
broker conditions
transaction costs
liquidity
corporate actions
taxation
regulatory requirements
strategy performance
before making real investment decisions.
---
▶️ Installation
Install the required Python packages:
```bash
pip install -r requirements.txt
```
Run the Streamlit application:
```bash
streamlit run app.py
```
---
🔑 Streamlit Secrets
Dhan credentials should be stored in Streamlit Secrets rather than hard-coded in Python.
Dhan access tokens expire every 24 hours (SEBI/exchange requirement) with no refresh-token
flow for a bare access token. Two ways to configure Dhan:

Manual (token must be regenerated in Dhan's console and pasted here daily):
```toml
DHAN_CLIENT_ID = "YOUR_DHAN_CLIENT_ID"
DHAN_ACCESS_TOKEN = "YOUR_DHAN_ACCESS_TOKEN"
```
Automatic renewal (recommended — the app mints a fresh token itself via headless
PIN+TOTP login once the cached one is ~23h old):
```toml
DHAN_CLIENT_ID = "YOUR_DHAN_CLIENT_ID"
DHAN_PIN = "YOUR_DHAN_TRADING_PIN"
DHAN_TOTP_SECRET = "YOUR_DHAN_TOTP_BASE32_SECRET"
```
`DHAN_TOTP_SECRET` is the base32 secret shown once when enabling TOTP-based API login in
Dhan's console (the same kind of secret an authenticator app would be seeded with) — not a
6-digit code. If both PIN+TOTP and a manual access token are present, PIN+TOTP auto-renewal
takes priority; the manual token remains a fallback if PIN+TOTP secrets are ever removed.
For Twelve Data features:
```toml
TWELVEDATA_API_KEY = "YOUR_TWELVE_DATA_API_KEY"
```
Never commit API keys or access tokens to GitHub.
---
💾 Persistent Data
Do not unnecessarily delete the application's local market-data or forward-testing databases.
Historical data is valuable because it allows the system to:
reduce repeated API downloads
accelerate future scans
reproduce previous research
build larger learning datasets
compare strategy performance over time
---
🏗️ Long-Term Development Goal
The long-term objective is a continuously improving research platform:
```text
DATA
 ↓
FEATURES
 ↓
STRATEGIES
 ↓
SCORING
 ↓
BACKTEST
 ↓
FORWARD TEST
 ↓
OUTCOMES
 ↓
LEARNING
 ↓
BETTER RANKING
 ↓
NEW DATA
 ↓
REPEAT
```
The learning process should improve the system's evidence and ranking, while preserving the integrity of the original strategy definitions.
The goal is not to create a system that promises perfect predictions.
The goal is to create a system that becomes:
faster, more statistically disciplined, more transparent, and more useful as its dataset grows.
---
📌 Current Status
Indian Equities
Dhan historical data
Persistent market-data cache
Dhan live feed
Strategies 1–4
Multi-timeframe analysis
Setup scoring
Market regime
Small/micro safety
Forward testing
Market learning
Strategy 4 Recovery Study
Research Extensions
Crypto data
Forex data
Fundamental enrichment
News/event risk
Continuous research and learning
---
⚠️ Important
This software is for research and decision support.
Past performance does not guarantee future performance.
A high backtest return can result from:
overfitting
survivorship bias
unrealistic execution
insufficient sample size
market-regime dependence
data-quality problems
Always validate important findings with out-of-sample and forward testing.
