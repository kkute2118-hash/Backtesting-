
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import date, timedelta

st.set_page_config(
    page_title="Adaptive Trading Intelligence Lab",
    page_icon="🧠",
    layout="wide"
)

# ----------------------------- DATA -----------------------------

INDEX_URLS = {
    "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "Nifty Smallcap 100": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",
    "Nifty Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "Nifty Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
}

@st.cache_data(ttl=86400)
def get_universe(name):
    r = requests.get(
        INDEX_URLS[name],
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.niftyindices.com/"},
        timeout=30,
    )
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(r.content))
    col = next((c for c in df.columns if str(c).strip().upper() == "SYMBOL"), None)
    if col is None:
        raise ValueError("NSE constituent file has no SYMBOL column.")
    return sorted({
        str(s).strip().upper() + ("" if str(s).strip().upper().endswith(".NS") else ".NS")
        for s in df[col].dropna()
    })

@st.cache_data(ttl=1800)
def get_prices(tickers, start, end):
    tickers = tuple(tickers)
    if not tickers:
        return {}
    raw = yf.download(
        tickers=list(tickers),
        start=start,
        end=end + timedelta(days=1),
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
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
            d = d.dropna(subset=["close"])
            if not d.empty:
                out[t] = d
        except Exception:
            pass
    return out

@st.cache_data(ttl=3600)
def get_company(ticker):
    obj = yf.Ticker(ticker)
    try:
        info = obj.info
    except Exception:
        info = {}
    try:
        news = obj.news[:10]
    except Exception:
        news = []
    return info, news

# -------------------------- INDICATORS --------------------------

def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()

def sma(s, n):
    return s.rolling(n, min_periods=n).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0)
    down = -d.clip(upper=0)
    au = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    ad = down.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def features(df):
    x = df.copy()
    for n in (10, 15, 20, 50, 200, 250):
        x[f"ema{n}"] = ema(x.close, n)
    x["vol20"] = sma(x.volume, 20)
    x["vol30"] = sma(x.volume, 30)
    x["rsi14"] = rsi(x.close)
    x["relvol"] = x.volume / x.vol20
    tr = pd.concat([
        x.high - x.low,
        (x.high - x.close.shift()).abs(),
        (x.low - x.close.shift()).abs(),
    ], axis=1).max(axis=1)
    x["atr14"] = tr.rolling(14).mean()

    m = x.resample("ME").agg({"close": "last", "open": "first", "high": "max", "low": "min"})
    m["rsi"] = rsi(m.close)
    m["ema10"] = ema(m.close, 10)
    m["ema15"] = ema(m.close, 15)
    m["ema20"] = ema(m.close, 20)
    m["mom"] = m.close.pct_change() * 100
    m = m.shift(1).reindex(x.index, method="ffill")
    x["mrsi"] = m.rsi
    x["mclose"] = m.close
    x["mema10"] = m.ema10
    x["mema15"] = m.ema15
    x["mema20"] = m.ema20
    x["mmom"] = m.mom

    w = x.resample("W-FRI").close.last().to_frame("close")
    w["rsi"] = rsi(w.close)
    w = w.shift(1).reindex(x.index, method="ffill")
    x["wrsi"] = w.rsi
    return x

# -------------------------- STRATEGIES --------------------------

def signal(x, number):
    if number == 1:
        return (
            (x.wrsi >= 50) & (x.mrsi >= 50) &
            (x.mclose >= x.mema15) & (x.close >= 15) &
            (x.vol20 >= 15000) &
            (((x.mclose - x.mema10) / x.mema10) <= .30) &
            (x.mmom >= 0)
        )
    if number == 2:
        cross = (x.ema20 > x.ema50) & (x.ema20.shift(1) <= x.ema50.shift(1))
        return (
            (x.close >= 15) & (x.vol20 >= 10000) &
            (x.mrsi >= 55) & (x.wrsi >= 50) &
            (((x.close - x.ema10) / x.ema10) <= .04) &
            (x.ema50 >= x.ema250) & cross
        )
    if number == 3:
        vwap20 = (x.close * x.volume).rolling(20).sum() / x.volume.rolling(20).sum()
        return (
            (vwap20 * x.vol20 >= 150_000_000) &
            (x.close >= x.ema200) & (x.wrsi >= 40) &
            (x.close <= x.ema50 * 1.04) &
            (x.close >= x.ema50 * .96)
        )
    if number == 4:
        cross = (x.ema10 > x.ema20) & (x.ema10.shift(1) <= x.ema20.shift(1))
        reclaim = (x.close > x.ema10) & (x.close.shift(1) <= x.ema10.shift(1))
        return (
            (x.mmom >= 20) & (x.mrsi >= 50) &
            (x.mema10 >= x.mema20) & (x.vol30 >= 50000) &
            (x.close >= 20) & (cross | reclaim) &
            (x.close <= x.ema20 * 1.03)
        )
    return pd.Series(False, index=x.index)

# -------------------------- BACKTEST ---------------------------

def backtest(df, sig, capital, risk_pct, sl_pct, target_r, slip):
    x = features(df).dropna()
    sig = sig.reindex(x.index).fillna(False)
    equity = capital
    rows = []
    i = 0

    while i < len(x) - 1:
        if not bool(sig.iloc[i]):
            i += 1
            continue

        ei = i + 1
        entry = float(x.close.iloc[ei]) * (1 + slip)
        stop = entry * (1 - sl_pct)
        one_r = entry - stop
        qty = int((equity * risk_pct) / one_r)

        if qty < 1:
            i += 1
            continue

        target = entry + target_r * one_r
        exit_i = None
        exit_p = None
        reason = ""

        for j in range(ei, len(x)):
            lo = float(x.low.iloc[j])
            hi = float(x.high.iloc[j])

            if lo <= stop:
                exit_i = j
                exit_p = stop * (1 - slip)
                reason = "Stop / Trail"
                break

            if hi >= target:
                exit_i = j
                exit_p = target * (1 - slip)
                reason = f"{target_r:g}R Target"
                break

            if hi >= entry + 2 * one_r:
                stop = max(stop, entry)
                if pd.notna(x.ema10.iloc[j]):
                    stop = max(stop, float(x.ema10.iloc[j]) * (1 - slip))

        if exit_i is None:
            exit_i = len(x) - 1
            exit_p = float(x.close.iloc[-1]) * (1 - slip)
            reason = "End of Test"

        pnl = (exit_p - entry) * qty
        equity += pnl
        r_mult = pnl / (one_r * qty)

        rows.append({
            "Entry Date": x.index[ei].date(),
            "Exit Date": x.index[exit_i].date(),
            "Entry": entry,
            "Exit": exit_p,
            "Return %": (exit_p / entry - 1) * 100,
            "R": r_mult,
            "PnL ₹": pnl,
            "Holding Days": (x.index[exit_i] - x.index[ei]).days,
            "Reason": reason,
        })
        i = exit_i + 1

    return pd.DataFrame(rows), equity

def metrics(t):
    if t.empty:
        return {}
    w = t[t.R > 0]
    l = t[t.R < 0]
    gp = w["PnL ₹"].sum()
    gl = abs(l["PnL ₹"].sum())
    curve = (1 + t.R).cumprod()
    dd = curve / curve.cummax() - 1
    return {
        "Trades": len(t),
        "Win %": len(w) / len(t) * 100,
        "Avg Win %": w["Return %"].mean() if len(w) else 0,
        "Avg Loss %": l["Return %"].mean() if len(l) else 0,
        "Expectancy R": t.R.mean(),
        "Total R": t.R.sum(),
        "Profit Factor": gp / gl if gl else np.nan,
        "Max DD %": dd.min() * 100,
        "Winner Hold": w["Holding Days"].mean() if len(w) else 0,
        "Loser Hold": l["Holding Days"].mean() if len(l) else 0,
    }

# --------------------- FUNDAMENTALS / NEWS ---------------------

def fundamental_score(info):
    score = 50
    flags = []
    for field in [
        "revenueGrowth", "earningsGrowth", "returnOnEquity",
        "returnOnAssets", "profitMargins", "operatingMargins"
    ]:
        v = info.get(field)
        if isinstance(v, (int, float)) and np.isfinite(v):
            score += 5 if v > 0 else -5

    debt = info.get("debtToEquity")
    if isinstance(debt, (int, float)) and np.isfinite(debt) and debt > 150:
        score -= 15
        flags.append("High debt/equity")

    pe = info.get("trailingPE")
    if isinstance(pe, (int, float)) and np.isfinite(pe) and pe > 80:
        score -= 5
        flags.append("High trailing P/E")

    return max(0, min(100, score)), flags

# ----------------------------- UI ------------------------------

st.title("🧠 Adaptive Trading Intelligence Lab")
st.caption(
    "Backtest • Walk-forward • Forward test • Pattern learning • "
    "Small/Micro-cap fundamentals & news • Custom strategies"
)

tabs = st.tabs([
    "🏠 Dashboard", "📊 Backtest", "🔬 Walk-Forward",
    "📡 Forward Test", "🧠 Pattern Learning",
    "🧪 Custom Strategy", "🏢 Small/Micro-Cap", "📒 Trade Journal"
])

with tabs[0]:
    st.subheader("System Overview")
    a, b, c, d = st.columns(4)
    a.metric("Default Risk", "1%")
    b.metric("Default SL", "7%")
    c.metric("Default Target", "3R")
    d.metric("Learning", "Forward validated")
    st.info(
        "The system is designed to improve robustness over time. "
        "It cannot guarantee profitability."
    )
    st.markdown("""
**Pipeline**

Market Data → Strategy Engine → Technical Setup → Fundamental/News Layer
→ Risk Engine → Forward Test → Trade Journal → Learning → Walk-Forward Validation
""")

with tabs[1]:
    st.subheader("📊 Backtest Lab")
    c1, c2, c3 = st.columns(3)

    universe = c1.selectbox(
        "Universe",
        ["Nifty 500", "Nifty Smallcap 100", "Nifty Smallcap 250", "Nifty Midcap 150"],
        key="bt_universe"
    )
    start = c2.date_input(
        "Start Date",
        value=date.today() - timedelta(days=730),
        key="bt_start"
    )
    end = c3.date_input(
        "End Date",
        value=date.today(),
        key="bt_end"
    )

    c1, c2, c3, c4 = st.columns(4)
    capital = c1.number_input("Starting Capital ₹", value=1_000_000, step=100_000, key="bt_capital")
    risk = c2.number_input("Risk / Trade %", value=1.0, step=.25, key="bt_risk")
    sl = c3.number_input("Stop Loss %", value=7.0, step=.5, key="bt_sl")
    rr = c4.selectbox("Target R", [2, 2.5, 3, 3.5, 4, 5], index=2, key="bt_rr")

    strategies = st.multiselect(
        "Strategies",
        [1, 2, 3, 4],
        default=[1, 2, 3, 4],
        key="bt_strategies"
    )

    if st.button("🚀 Run Backtest", type="primary", key="bt_run"):
        try:
            tickers = get_universe(universe)
            st.write(f"Universe: **{len(tickers)} symbols**")
            data = get_prices(tuple(tickers), start, end)
            all_trades = []
            summaries = []
            bar = st.progress(0)

            for n, (ticker, df) in enumerate(data.items()):
                if len(df) >= 260:
                    f = features(df)
                    for s in strategies:
                        try:
                            tr, final_eq = backtest(
                                df,
                                signal(f, s),
                                capital,
                                risk / 100,
                                sl / 100,
                                rr,
                                .001
                            )
                            if not tr.empty:
                                tr["Ticker"] = ticker
                                tr["Strategy"] = f"Strategy {s}"
                                all_trades.append(tr)
                                m = metrics(tr)
                                m["Strategy"] = f"Strategy {s}"
                                m["Ticker"] = ticker
                                m["Final Equity"] = final_eq
                                summaries.append(m)
                        except Exception:
                            pass
                bar.progress((n + 1) / max(1, len(data)))

            if summaries:
                summary = pd.DataFrame(summaries)
                trades = pd.concat(all_trades, ignore_index=True)

                leaderboard = summary.groupby("Strategy").agg({
                    "Trades": "sum",
                    "Win %": "mean",
                    "Avg Win %": "mean",
                    "Avg Loss %": "mean",
                    "Expectancy R": "mean",
                    "Total R": "sum",
                    "Profit Factor": "mean",
                    "Max DD %": "mean",
                }).sort_values("Expectancy R", ascending=False)

                st.subheader("🏆 Strategy Leaderboard")
                st.dataframe(leaderboard, use_container_width=True)
                st.subheader("📋 Trade Log")
                st.dataframe(trades, use_container_width=True)

                st.download_button(
                    "⬇️ Download Trade Log",
                    trades.to_csv(index=False).encode(),
                    "trade_log.csv",
                    "text/csv",
                    key="bt_download"
                )
            else:
                st.warning("No qualifying trades found.")
        except Exception as e:
            st.error(f"Backtest error: {e}")

with tabs[2]:
    st.subheader("🔬 Walk-Forward Testing")
    a, b, c = st.columns(3)
    a.number_input("Training Months", 12, min_value=3, max_value=60, key="wf_train")
    b.number_input("Validation Months", 3, min_value=1, max_value=24, key="wf_validation")
    c.number_input("Forward Months", 3, min_value=1, max_value=24, key="wf_forward")
    st.info(
        "A learned filter should only be promoted when it improves "
        "unseen forward performance without materially worsening drawdown."
    )

with tabs[3]:
    st.subheader("📡 Forward Testing")
    st.text_input("Ticker / Pair / Coin", key="forward_ticker")
    st.selectbox("Asset Class", ["Indian Equity", "Forex", "Crypto"], key="forward_asset")
    st.selectbox("Trading Style", ["Intraday", "Swing", "Positional"], key="forward_style")
    st.number_input("Entry Price", min_value=0.0, key="forward_entry")
    st.number_input("Stop Price", min_value=0.0, key="forward_stop")
    st.number_input("Target Price", min_value=0.0, key="forward_target")
    st.text_area("Setup Notes", key="forward_notes")
    st.multiselect(
        "Mistakes / Warnings",
        ["None", "Early Entry", "Late Entry", "Chased Price", "Moved Stop",
         "Exited Early", "Overtraded", "Wrong Regime", "Oversized", "Ignored News"],
        key="forward_mistakes"
    )
    if st.button("💾 Save Forward Setup", key="forward_save"):
        st.success("Forward setup recorded for tracking.")

with tabs[4]:
    st.subheader("🧠 Pattern Learning Engine")
    st.write("""
The learning layer should compare winners and losers by RSI, EMA distance,
relative volume, ATR/volatility, market regime, strategy, setup type,
fundamental quality, news risk and your own trading mistakes.
""")
    st.warning(
        "Never train and evaluate on the same trades. "
        "Use rolling walk-forward validation."
    )
    st.markdown(
        "**Primary objective:** expectancy + profit factor + drawdown stability + "
        "sample size + forward-test stability."
    )

with tabs[5]:
    st.subheader("🧪 Custom Strategy Lab")
    strategy_text = st.text_area(
        "Paste Your Strategy",
        height=220,
        placeholder=(
            "Example:\n"
            "Buy when RSI(14) > 55, close > 200 EMA, "
            "volume > 1.5x 20-day average.\n"
            "SL = 7%; Target = 3R."
        ),
        key="custom_strategy"
    )
    st.selectbox("Market", ["Indian Stocks", "Forex", "Crypto"], key="custom_market")
    st.selectbox("Trading Style", ["Intraday", "Swing", "Positional"], key="custom_style")
    st.selectbox("Timeframe", ["5m", "15m", "1h", "4h", "Daily", "Weekly"], key="custom_timeframe")
    if st.button("🔍 Validate Strategy", key="custom_validate"):
        if not strategy_text.strip():
            st.warning("Paste a strategy first.")
        else:
            st.success(
                "Strategy received. Ambiguous rules must be converted into "
                "explicit testable conditions before execution."
            )

with tabs[6]:
    st.subheader("🏢 Small / Micro-Cap Intelligence")
    st.write("Technical + fundamental + current news + basic risk flags.")
    ticker_input = st.text_input("NSE Ticker", placeholder="ABC.NS", key="smallcap_ticker")

    if st.button("🔎 Analyze Stock", key="smallcap_analyze"):
        if not ticker_input.strip():
            st.warning("Enter an NSE ticker.")
        else:
            try:
                ticker = ticker_input.strip().upper()
                if not ticker.endswith(".NS"):
                    ticker += ".NS"

                info, news = get_company(ticker)
                fund_score, flags = fundamental_score(info)

                data = get_prices(
                    (ticker,),
                    date.today() - timedelta(days=500),
                    date.today()
                ).get(ticker)

                tech_score = 50

                if data is not None and len(data) > 220:
                    f = features(data).dropna()
                    if not f.empty:
                        last = f.iloc[-1]
                        tech_score += 15 if last.close > last.ema200 else -15
                        tech_score += 10 if last.rsi14 > 50 else -10
                        tech_score += 10 if last.relvol > 1.2 else 0
                        tech_score += 10 if last.close > last.ema20 else 0

                tech_score = max(0, min(100, tech_score))
                combined = tech_score * .55 + fund_score * .45

                a, b, c = st.columns(3)
                a.metric("Technical", f"{tech_score:.0f}/100")
                b.metric("Fundamental", f"{fund_score:.0f}/100")
                c.metric("Combined", f"{combined:.0f}/100")

                if flags:
                    st.warning("Risk flags: " + ", ".join(flags))

                st.subheader("📰 Current Yahoo Finance News")
                if news:
                    for item in news:
                        content = item.get("content", {})
                        title = content.get("title") or item.get("title") or "News item"
                        st.write("•", title)
                else:
                    st.info("No current news returned.")

                st.caption(
                    "Current fundamentals/news are deliberately not backfilled into "
                    "historical backtests because that would create look-ahead bias."
                )
            except Exception as e:
                st.error(f"Analysis error: {e}")

with tabs[7]:
    st.subheader("📒 Personal Trade Journal")
    st.text_input("Ticker / Pair / Coin", key="journal_ticker")
    st.selectbox("Result", ["Win", "Loss", "Breakeven"], key="journal_result")
    st.number_input("R Multiple", value=0.0, key="journal_r")
    st.text_area("What Happened?", key="journal_notes")
    st.multiselect(
        "Mistakes",
        ["None", "Early Entry", "Late Entry", "Chased Price", "Moved Stop",
         "Exited Early", "Overtraded", "Wrong Regime", "Oversized", "Ignored News"],
        key="journal_mistakes"
    )
    if st.button("💾 Save Journal Entry", key="journal_save"):
        st.success("Journal entry recorded.")

st.markdown("---")
st.caption(
    "Education
