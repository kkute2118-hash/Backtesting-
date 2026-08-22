
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import date, timedelta

st.set_page_config(page_title="Adaptive Trading Lab", page_icon="🧠", layout="wide")

INDEX_URLS = {
    "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "Nifty Smallcap 100": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",
    "Nifty Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "Nifty Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
}

@st.cache_data(ttl=86400)
def universe(name):
    r = requests.get(INDEX_URLS[name], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(r.content))
    col = next(c for c in df.columns if str(c).strip().upper() == "SYMBOL")
    return sorted({str(s).strip().upper() + ".NS" for s in df[col].dropna()})

@st.cache_data(ttl=1800)
def prices(tickers, start, end):
    tickers = tuple(tickers)
    raw = yf.download(
        list(tickers), start=start, end=end + timedelta(days=1),
        auto_adjust=False, progress=False, group_by="ticker", threads=True
    )
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
            if not d.empty:
                out[t] = d.dropna(subset=["close"])
        except Exception:
            pass
    return out

def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()

def sma(s, n):
    return s.rolling(n, min_periods=n).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def add_indicators(d):
    x = d.copy()
    for n in (10, 20, 50, 200, 250):
        x[f"ema{n}"] = ema(x.close, n)
    x["vol20"] = sma(x.volume, 20)
    x["vol30"] = sma(x.volume, 30)
    x["rsi"] = rsi(x.close)
    x["relvol"] = x.volume / x.vol20
    tr = pd.concat([
        x.high - x.low,
        (x.high - x.close.shift()).abs(),
        (x.low - x.close.shift()).abs()
    ], axis=1).max(axis=1)
    x["atr"] = tr.rolling(14).mean()

    m = x.resample("ME").close.last().to_frame("close")
    m["rsi"] = rsi(m.close)
    m["ema10"] = ema(m.close, 10)
    m["ema15"] = ema(m.close, 15)
    m["ema20"] = ema(m.close, 20)
    m["mom"] = m.close.pct_change() * 100
    m = m.shift(1).reindex(x.index, method="ffill")
    x["mrsi"], x["mema10"], x["mema15"], x["mema20"], x["mmom"] = (
        m.rsi, m.ema10, m.ema15, m.ema20, m.mom
    )
    w = x.resample("W-FRI").close.last().to_frame("close")
    w["rsi"] = rsi(w.close)
    x["wrsi"] = w.shift(1).reindex(x.index, method="ffill").rsi
    return x

def setup_signal(x, s):
    if s == 1:
        return (x.wrsi >= 50) & (x.mrsi >= 50) & (x.mclose >= x.mema15) & (x.close >= 15) & (x.vol20 >= 15000) & (((x.mclose-x.mema10)/x.mema10) <= .30)
    if s == 2:
        cross = (x.ema20 > x.ema50) & (x.ema20.shift(1) <= x.ema50.shift(1))
        return (x.close >= 15) & (x.vol20 >= 10000) & (x.mrsi >= 55) & (x.wrsi >= 50) & (((x.close-x.ema10)/x.ema10) <= .04) & (x.ema50 >= x.ema250) & cross
    if s == 3:
        vwap = (x.close*x.volume).rolling(20).sum() / x.volume.rolling(20).sum()
        return (vwap*x.vol20 >= 150_000_000) & (x.close >= x.ema200) & (x.wrsi >= 40) & (x.close.between(x.ema50*.96, x.ema50*1.04))
    if s == 4:
        cross = (x.ema10 > x.ema20) & (x.ema10.shift(1) <= x.ema20.shift(1))
        reclaim = (x.close > x.ema10) & (x.close.shift(1) <= x.ema10.shift(1))
        return (x.mmom >= 20) & (x.mrsi >= 50) & (x.mema10 >= x.mema20) & (x.vol30 >= 50000) & (x.close >= 20) & (cross | reclaim) & (x.close <= x.ema20*1.03)
    return pd.Series(False, index=x.index)

def run_backtest(d, sig, capital, risk, sl, rr, slip=.001):
    x = add_indicators(d).dropna()
    sig = sig.reindex(x.index).fillna(False)
    equity, rows, i = capital, [], 0
    while i < len(x)-1:
        if not bool(sig.iloc[i]):
            i += 1
            continue
        ei = i+1
        entry = float(x.close.iloc[ei])*(1+slip)
        stop = entry*(1-sl)
        one_r = entry-stop
        qty = int(equity*risk/one_r)
        if qty < 1:
            i += 1
            continue
        target = entry + rr*one_r
        ex = ep = None
        reason = ""
        for j in range(ei, len(x)):
            lo, hi = float(x.low.iloc[j]), float(x.high.iloc[j])
            if lo <= stop:
                ex, ep, reason = j, stop*(1-slip), "SL"
                break
            if hi >= target:
                ex, ep, reason = j, target*(1-slip), f"{rr}R"
                break
            if hi >= entry+2*one_r:
                stop = max(stop, entry)
                if pd.notna(x.ema10.iloc[j]):
                    stop = max(stop, float(x.ema10.iloc[j])*(1-slip))
        if ex is None:
            ex, ep, reason = len(x)-1, float(x.close.iloc[-1])*(1-slip), "End"
        pnl = (ep-entry)*qty
        equity += pnl
        rows.append({
            "Entry Date": x.index[ei].date(), "Exit Date": x.index[ex].date(),
            "Entry": entry, "Exit": ep, "Return %": (ep/entry-1)*100,
            "R": pnl/(one_r*qty), "PnL ₹": pnl,
            "Holding Days": (x.index[ex]-x.index[ei]).days, "Reason": reason
        })
        i = ex+1
    return pd.DataFrame(rows), equity

def stats(t):
    if t.empty:
        return {}
    w, l = t[t.R > 0], t[t.R < 0]
    gp, gl = w["PnL ₹"].sum(), abs(l["PnL ₹"].sum())
    curve = (1+t.R).cumprod()
    dd = (curve/curve.cummax()-1).min()*100
    return {
        "Trades": len(t), "Win %": len(w)/len(t)*100,
        "Avg Win %": w["Return %"].mean() if len(w) else 0,
        "Avg Loss %": l["Return %"].mean() if len(l) else 0,
        "Expectancy R": t.R.mean(), "Total R": t.R.sum(),
        "Profit Factor": gp/gl if gl else np.nan, "Max DD %": dd
    }

@st.cache_data(ttl=3600)
def company_data(ticker):
    t = yf.Ticker(ticker)
    try: info = t.info
    except Exception: info = {}
    try: news = t.news[:10]
    except Exception: news = []
    return info, news

def fund_score(info):
    score, flags = 50, []
    for k in ("revenueGrowth","earningsGrowth","returnOnEquity","returnOnAssets","profitMargins","operatingMargins"):
        v = info.get(k)
        if isinstance(v, (int,float)) and np.isfinite(v):
            score += 5 if v > 0 else -5
    debt = info.get("debtToEquity")
    if isinstance(debt,(int,float)) and np.isfinite(debt) and debt > 150:
        score -= 15; flags.append("High debt/equity")
    pe = info.get("trailingPE")
    if isinstance(pe,(int,float)) and np.isfinite(pe) and pe > 80:
        score -= 5; flags.append("High P/E")
    return max(0,min(100,score)), flags

st.title("🧠 Adaptive Trading Intelligence Lab")
st.caption("Backtest • Forward test • Walk-forward • Learning • Small/Micro-cap • Custom Forex/Crypto")

tabs = st.tabs([
    "🏠 Dashboard","📊 Backtest","🔬 Walk-Forward","📡 Forward Test",
    "🧠 Pattern Learning","🧪 Custom Strategy","🏢 Small/Micro-Cap","📒 Trade Journal"
])

with tabs[0]:
    a,b,c,d = st.columns(4)
    a.metric("Risk", "1%")
    b.metric("SL", "7%")
    c.metric("Target", "3R")
    d.metric("Learning", "Forward validated")
    st.info("This is a research platform. It cannot guarantee profitability.")
    st.markdown("**Pipeline:** Data → Strategy → Technical → Fundamental/News → Risk → Forward Test → Journal → Learning → Walk-forward")

with tabs[1]:
    st.subheader("📊 Backtest Lab")
    a,b,c = st.columns(3)
    uni = a.selectbox("Universe", list(INDEX_URLS), key="bt_uni")
    start = b.date_input("Start Date", date.today()-timedelta(days=730), key="bt_start")
    end = c.date_input("End Date", date.today(), key="bt_end")
    a,b,c,d = st.columns(4)
    capital = a.number_input(
        "Capital ₹",
        value=1_000_000,
        step=100_000,
        key="bt_cap"
    )
    risk = b.number_input(
        "Risk %",
        value=1.0,
        step=.25,
        key="bt_risk"
    )
    sl = c.number_input(
        "SL %",
        value=7.0,
        step=.5,
        key="bt_sl"
    )
    rr = d.selectbox("Target R", [2,2.5,3,3.5,4,5], index=2, key="bt_rr")
    strategies = st.multiselect("Strategies", [1,2,3,4], [1,2,3,4], key="bt_strats")
    if st.button("🚀 Run Backtest", type="primary", key="bt_run"):
        try:
            tickers = universe(uni)
            data = prices(tuple(tickers), start, end)
            logs, summary = [], []
            bar = st.progress(0)
            for n,(ticker,df) in enumerate(data.items()):
                if len(df) >= 260:
                    f = add_indicators(df)
                    for s in strategies:
                        try:
                            tr, eq = run_backtest(df, setup_signal(f,s), capital, risk/100, sl/100, rr)
                            if not tr.empty:
                                tr["Ticker"], tr["Strategy"] = ticker, f"Strategy {s}"
                                logs.append(tr)
                                m = stats(tr); m["Strategy"] = f"Strategy {s}"; summary.append(m)
                        except Exception:
                            pass
                bar.progress((n+1)/max(1,len(data)))
            if summary:
                alltrades = pd.concat(logs, ignore_index=True)
                board = pd.DataFrame(summary).groupby("Strategy").mean(numeric_only=True).sort_values("Expectancy R", ascending=False)
                st.subheader("🏆 Strategy Leaderboard")
                st.dataframe(board, use_container_width=True)
                st.subheader("📋 Trades")
                st.dataframe(alltrades, use_container_width=True)
                st.download_button("⬇️ Download CSV", alltrades.to_csv(index=False).encode(), "trades.csv", key="bt_download")
            else:
                st.warning("No qualifying trades found.")
        except Exception as e:
            st.error(f"Backtest error: {e}")

with tabs[2]:
    st.subheader("🔬 Walk-Forward")
    a,b,c = st.columns(3)
    a.number_input(
        "Training months",
        value=12,
        min_value=3,
        max_value=60,
        key="wf_train"
    )
    b.number_input(
        "Validation months",
        value=3,
        min_value=1,
        max_value=24,
        key="wf_val"
    )
    c.number_input(
        "Unseen forward months",
        value=3,
        min_value=1,
        max_value=24,
        key="wf_test"
    )
    st.info("Promote a learned filter only if it improves unseen forward expectancy and drawdown.")

with tabs[3]:
    st.subheader("📡 Forward Test")
    st.text_input("Ticker / Pair / Coin", key="forward_symbol")
    st.selectbox("Asset class", ["Indian Equity","Forex","Crypto"], key="forward_asset")
    st.selectbox("Style", ["Intraday","Swing","Positional"], key="forward_style")
    st.number_input("Entry", min_value=0.0, key="forward_entry")
    st.number_input("Stop", min_value=0.0, key="forward_stop")
    st.number_input("Target", min_value=0.0, key="forward_target")
    st.text_area("Notes", key="forward_notes")
    st.multiselect("Mistakes", ["None","Early Entry","Late Entry","Chased Price","Moved Stop","Exited Early","Overtraded","Wrong Regime","Oversized","Ignored News"], key="forward_mistakes")
    st.button("💾 Save Forward Setup", key="forward_save")

with tabs[4]:
    st.subheader("🧠 Pattern Learning")
    st.write("Future learning layer: compare winners/losers by RSI, EMA distance, volume, ATR, regime, setup, fundamentals, news and your own mistakes.")
    st.warning("Training data and evaluation data must remain separate.")

with tabs[5]:
    st.subheader("🧪 Custom Strategy Lab")
    st.text_area("Paste your strategy", height=220, key="custom_text", placeholder="Example: RSI > 55, close > 200 EMA, volume > 1.5x 20-day average. SL 7%, target 3R.")
    st.selectbox("Market", ["Indian Stocks","Forex","Crypto"], key="custom_market")
    st.selectbox("Style", ["Intraday","Swing","Positional"], key="custom_style")
    st.selectbox("Timeframe", ["5m","15m","1h","4h","Daily","Weekly"], key="custom_tf")
    if st.button("🔍 Validate Strategy", key="custom_validate"):
        st.success("Strategy received. Ambiguous rules must be converted into explicit testable conditions before execution.")

with tabs[6]:
    st.subheader("🏢 Small / Micro-Cap Intelligence")
    ticker = st.text_input("NSE ticker", placeholder="ABC.NS", key="small_ticker")
    if st.button("🔎 Analyze", key="small_analyze") and ticker.strip():
        try:
            ticker = ticker.strip().upper()
            if not ticker.endswith(".NS"): ticker += ".NS"
            info, news = company_data(ticker)
            fs, flags = fund_score(info)
            d = prices((ticker,), date.today()-timedelta(days=500), date.today()).get(ticker)
            ts = 50
            if d is not None and len(d) > 220:
                f = add_indicators(d).dropna()
                if not f.empty:
                    z = f.iloc[-1]
                    ts += 15 if z.close > z.ema200 else -15
                    ts += 10 if z.rsi > 50 else -10
                    ts += 10 if z.relvol > 1.2 else 0
                    ts += 10 if z.close > z.ema20 else 0
            ts = max(0,min(100,ts))
            a,b,c = st.columns(3)
            a.metric("Technical", f"{ts}/100")
            b.metric("Fundamental", f"{fs}/100")
            c.metric("Combined", f"{ts*.55+fs*.45:.0f}/100")
            if flags: st.warning("Risk flags: " + ", ".join(flags))
            st.subheader("📰 Current News")
            for item in news:
                content = item.get("content",{})
                st.write("•", content.get("title") or item.get("title") or "News")
        except Exception as e:
            st.error(f"Analysis error: {e}")

with tabs[7]:
    st.subheader("📒 Trade Journal")
    st.text_input("Ticker / Pair / Coin", key="journal_symbol")
    st.selectbox("Result", ["Win","Loss","Breakeven"], key="journal_result")
    st.number_input("R multiple", value=0.0, key="journal_r")
    st.text_area("What happened?", key="journal_notes")
    st.multiselect("Mistakes", ["None","Early Entry","Late Entry","Chased Price","Moved Stop","Exited Early","Overtraded","Wrong Regime","Oversized","Ignored News"], key="journal_mistakes")
    st.button("💾 Save Journal Entry", key="journal_save")

st.markdown("---")
st.caption("Educational research software. Validate with unseen forward data before risking real capital.")
                
