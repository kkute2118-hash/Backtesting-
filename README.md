# Multi-Strategy Trading Backtester

Streamlit dashboard using Yahoo Finance (`yfinance`).

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Upload a CSV with a `Ticker` column, e.g.

```csv
Ticker
RELIANCE.NS
TCS.NS
INFY.NS
HDFCBANK.NS
```

The dashboard supports:
- Strategies 1–4
- Nifty 500 / Smallcap 100 via uploaded constituent CSV
- Configurable stop loss and target R
- Slippage
- Position sizing
- Trade log
- Strategy comparison

**Important:** Strategy 3 contains Chartink-specific IDs `{33489}` and `{166311}`. Their definitions are not included in the expression, so the dashboard implements the visible technical conditions only.

For a survivorship-bias-aware historical index backtest, use historical constituent lists rather than only today's constituents.
