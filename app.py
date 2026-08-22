import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import date, timedelta
import yfinance as yf

st.set_page_config(page_title="Multi-Strategy Trading Backtester", page_icon="📈", layout="wide")
st.title("📈 Multi-Strategy Trading Backtester")
st.caption("Nifty 500 / Nifty Smallcap 100 • automatic constituent list • Yahoo Finance price data")

DEFAULT_START = date.today() - timedelta(days=730)

@st.cache_data(ttl=86400, show_spinner=False)
def get_constituents(kind):
    urls = {
        "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "Nifty Smallcap 100": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",
    }
    r = requests.get(urls[kind], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(r.content))
    col = next((c for c in df.columns if str(c).strip().upper() in ["SYMBOL", "SYMBOLS"]), None)
    if col is None:
        raise ValueError(f"Could not find SYMBOL column. Columns: {list(df.columns)}")
    symbols = df[col].astype(str).str.strip().str.upper().tolist()
    return sorted(set(s + ".NS" if not s.endswith(".NS") else s for s in symbols if s and s != "NAN"))

def ema(s, n): return s.ewm(span=n, adjust=False, min_periods=n).mean()
def sma(s, n): return s.rolling(n, min_periods=n).mean()

def rsi(s, n=14):
    d = s.diff()
    gain, loss = d.clip(lower=0), -d.clip(upper=0)
    ag = gain.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    al = loss.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def features(d):
    x = d.copy()
    for n in [10, 15, 20, 50, 200, 250]:
        x[f"ema{n}"] = ema(x.close, n)
    x["vol20"], x["vol30"] = sma(x.volume, 20), sma(x.volume, 30)
    x["rsi14"], x["mom1"] = rsi(x.close), x.close.pct_change() * 100
    x["max30mom"] = x.mom1.rolling(30, min_periods=1).max()
    x["pctema10"] = (x.close - x.ema10) / x.ema10
    x["vwap20"] = (x.close * x.volume).rolling(20).sum() / x.volume.rolling(20).sum()

    m = x.resample("ME").agg({"open":"first","high":"max","low":"min","close":"last"})
    m["rsi14"] = rsi(m.close)
    m["ema10"], m["ema15"], m["ema20"] = ema(m.close,10), ema(m.close,15), ema(m.close,20)
    m["mom1"] = m.close.pct_change() * 100
    m["max20mom"] = m.mom1.rolling(20, min_periods=1).max()
    m = m.shift(1).reindex(x.index, method="ffill")
    for c in m.columns: x["m_" + c] = m[c]

    w = x.resample("W-FRI").agg({"close":"last"})
    w["rsi14"] = rsi(w.close)
    w = w.shift(1).reindex(x.index, method="ffill")
    x["w_rsi14"] = w.rsi14
    return x

def signal(x, s):
    if s == 1:
        return ((x.w_rsi14 >= 50) & (x.m_rsi14 >= 50) & (x.m_close >= x.m_ema15) &
                (x.close >= 15) & (x.vol20 >= 15000) &
                (((x.m_close-x.m_ema10)/x.m_ema10) <= .30) & (x.m_max20mom >= 20))
    if s == 2:
        c1 = (x.ema20 > x.ema50) & (x.ema20.shift(1) <= x.ema50.shift(1))
        c2 = (x.ema50 > x.ema200) & (x.ema50.shift(1) <= x.ema200.shift(1))
        return ((x.max30mom >= 5) & (x.close >= 15) & (x.vol20 >= 10000) &
                (x.m_rsi14 >= 55) & (x.w_rsi14 >= 50) & (x.pctema10 <= .04) &
                (x.ema50 >= x.ema250) & (c1 | c2))
    if s == 3:
        return ((x.vwap20*x.vol20 >= 150_000_000) & (x.close >= x.ema200) &
                (x.w_rsi14 >= 40) & (x.close <= x.ema50*1.04) &
                (x.close >= x.ema50*.96))
    if s == 4:
        cross = (x.ema10 > x.ema20) & (x.ema10.shift(1) <= x.ema20.shift(1))
        reclaim = (x.close > x.ema10) & (x.close.shift(1) <= x.ema10.shift(1))
        return ((x.m_mom1 >= 20) & (x.m_rsi14 >= 50) & (x.m_ema10 >= x.m_ema20) &
                (x.vol30 >= 50000) & (x.close >= 20) & (cross | reclaim) &
                (x.close <= 1.03*x.ema20))
    return pd.Series(False, index=x.index)

@st.cache_data(ttl=3600, show_spinner=False)
def download_prices(tickers, start, end):
    raw = yf.download(tickers, start=start, end=end+timedelta(days=1),
                      auto_adjust=False, progress=False, group_by="ticker", threads=True)
    out = {}
    if len(tickers) == 1:
        if not raw.empty:
            raw.columns = [str(c).lower() for c in raw.columns]
            out[tickers[0]] = raw.dropna(subset=["close"])
        return out
    for t in tickers:
        try:
            d = raw[t].copy()
            d.columns = [str(c).lower() for c in d.columns]
            out[t] = d.dropna(subset=["close"])
        except Exception:
            pass
    return out

def trades_for_stock(d, s, capital, risk, sl, rr, slip):
    x = features(d).dropna()
    sig = signal(x, s).fillna(False)
    equity, trades, i = capital, [], 0
    while i < len(x)-1:
        if not bool(sig.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        ep = float(x.close.iloc[entry_i]) * (1 + slip)
        stop = ep * (1 - sl)
        rps = ep - stop
        shares = int((equity*risk)/rps)
        if shares <= 0:
            i += 1
            continue
        target = ep + rr*rps
        exit_i = exit_p = None
        reason = ""
        for j in range(entry_i, len(x)):
            lo, hi = float(x.low.iloc[j]), float(x.high.iloc[j])
            if lo <= stop:
                exit_i, exit_p, reason = j, stop*(1-slip), "Stop/BE/Trail"
                break
            if hi >= target:
                exit_i, exit_p, reason = j, target*(1-slip), f"{rr:g}R Target"
                break
            if hi >= ep + 2*rps:
                stop = max(stop, ep)
                if not pd.isna(x.ema10.iloc[j]):
                    stop = max(stop, float(x.ema10.iloc[j])*(1-slip))
        if exit_i is None:
            exit_i, exit_p, reason = len(x)-1, float(x.close.iloc[-1])*(1-slip), "End of test"
        pnl = (exit_p-ep)*shares
        equity += pnl
        trades.append({
            "Ticker": getattr(d, "name", ""),
            "Entry Date": x.index[entry_i].date(),
            "Exit Date": x.index[exit_i].date(),
            "Entry": ep, "Exit": exit_p,
            "Return %": (exit_p/ep-1)*100,
            "R": pnl/(rps*shares), "PnL ₹": pnl,
            "Holding Days": (x.index[exit_i]-x.index[entry_i]).days,
            "Reason": reason
        })
        i = exit_i + 1
    return pd.DataFrame(trades), equity

st.sidebar.header("Backtest Settings")
start = st.sidebar.date_input("Start date", DEFAULT_START)
end = st.sidebar.date_input("End date", date.today())
capital = st.sidebar.number_input("Starting capital (₹)", value=1000000, step=100000)
risk = st.sidebar.number_input("Risk per trade (%)", value=1.0, step=.25)/100
sl = st.sidebar.number_input("Stop-loss (%)", value=7.0, step=.5)/100
rr = st.sidebar.selectbox("Target", [2.0, 2.5, 3.0, 3.5, 4.0, 5.0], index=2)
slip = st.sidebar.number_input("Slippage per side (%)", value=.10, step=.05)/100

st.sidebar.header("Universe")
universe = st.sidebar.selectbox("Select universe", ["Nifty 500", "Nifty Smallcap 100", "Both"])
selected = st.sidebar.multiselect("Strategies", [1,2,3,4], default=[1,2,3,4],
                                  format_func=lambda n: f"Strategy {n}")

st.info("No CSV upload is required. The constituent list is fetched automatically from NSE Indices; historical OHLCV is fetched directly from Yahoo Finance through yfinance.")

if st.button("🚀 Load Universe & Run Backtest", type="primary"):
    try:
        kinds = ["Nifty 500", "Nifty Smallcap 100"] if universe == "Both" else [universe]
        tickers = sorted(set(t for k in kinds for t in get_constituents(k)))
        st.write(f"Loaded **{len(tickers)} stocks** from {universe}.")
    except Exception as e:
        st.error(f"Could not load the NSE constituent list: {e}")
        st.stop()

    if not selected:
        st.error("Select at least one strategy.")
        st.stop()

    data = download_prices(tickers, start, end)
    rows, alltrades = [], []
    progress = st.progress(0)

    for n, (ticker, d) in enumerate(data.items()):
        if len(d) < 260:
            progress.progress((n+1)/max(len(data),1))
            continue
        d.name = ticker
        for s in selected:
            try:
                tr, final = trades_for_stock(d, s, capital, risk, sl, rr, slip)
                if len(tr):
                    tr["Strategy"] = f"Strategy {s}"
                    alltrades.append(tr)
                    wins, losses = tr[tr.R>0], tr[tr.R<0]
                    gp, gl = wins["PnL ₹"].sum(), abs(losses["PnL ₹"].sum())
                    rows.append({
                        "Strategy": f"Strategy {s}", "Ticker": ticker, "Trades": len(tr),
                        "Win %": 100*len(wins)/len(tr),
                        "Avg Win %": wins["Return %"].mean() if len(wins) else 0,
                        "Avg Loss %": losses["Return %"].mean() if len(losses) else 0,
                        "Expectancy R": tr.R.mean(), "Total R": tr.R.sum(),
                        "Profit Factor": gp/gl if gl else np.nan, "Final Equity": final
                    })
            except Exception:
                pass
        progress.progress((n+1)/max(len(data),1))

    if not rows:
        st.error("No qualifying trades found for the selected settings.")
        st.stop()

    r = pd.DataFrame(rows)
    trades = pd.concat(alltrades, ignore_index=True)

    st.subheader("🏆 Strategy Comparison")
    summary = r.groupby("Strategy").agg({
        "Trades":"sum","Win %":"mean","Avg Win %":"mean","Avg Loss %":"mean",
        "Expectancy R":"mean","Total R":"sum","Profit Factor":"mean"
    }).reset_index()
    summary = summary.sort_values(["Expectancy R","Profit Factor"], ascending=False)
    st.dataframe(summary, use_container_width=True)
    best = summary.iloc[0]
    st.success(f"Best by average expectancy R: **{best['Strategy']}**. Check drawdown and sample size before using any strategy live.")

    st.subheader("📋 Trade Log")
    st.dataframe(trades.sort_values(["Entry Date","Ticker"]), use_container_width=True)
    st.download_button("⬇️ Download trade log CSV",
                       trades.to_csv(index=False).encode(),
                       "trade_log.csv", "text/csv")

    st.caption("This uses the current constituent list. Because index membership changes over time, it is not a survivorship-bias-free historical membership test. Strategy 3's Chartink IDs {33489} and {166311} are not reconstructed because their definitions were not supplied.")

st.markdown("---")
st.caption("Educational backtesting tool. Validate data, costs, historical constituents and execution assumptions before using results for live trading.")
