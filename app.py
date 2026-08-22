
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
import yfinance as yf

st.set_page_config(page_title="Multi-Strategy Backtester", page_icon="📈", layout="wide")

st.title("📈 Multi-Strategy Trading Backtester")
st.caption("Yahoo Finance / yfinance • Nifty 500 + Nifty Smallcap 100 • Strategy comparison")

DEFAULT_START = date.today() - timedelta(days=730)

@st.cache_data(ttl=3600, show_spinner=False)
def yf_download(ticker, start, end):
    x = yf.download(ticker, start=start, end=end + timedelta(days=1),
                    auto_adjust=False, progress=False)
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = x.columns.get_level_values(0)
    x.columns = [str(c).lower() for c in x.columns]
    return x.dropna(subset=["close"])

def ema(s,n): return s.ewm(span=n, adjust=False, min_periods=n).mean()
def sma(s,n): return s.rolling(n, min_periods=n).mean()

def rsi(s,n=14):
    d=s.diff()
    gain=d.clip(lower=0)
    loss=-d.clip(upper=0)
    ag=gain.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    al=loss.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs=ag/al.replace(0,np.nan)
    return 100-(100/(1+rs))

def add_features(d):
    x=d.copy()
    for n in [10,15,20,50,200,250]:
        x[f"ema{n}"]=ema(x.close,n)
    x["vol20"]=sma(x.volume,20)
    x["vol30"]=sma(x.volume,30)
    x["rsi14"]=rsi(x.close)
    x["mom1"]=x.close.pct_change()*100
    x["max30mom"]=x.mom1.rolling(30,min_periods=1).max()
    x["pctema10"]=(x.close-x.ema10)/x.ema10
    x["vwap20"]=(x.close*x.volume).rolling(20).sum()/x.volume.rolling(20).sum()

    m=x.resample("ME").agg({"open":"first","high":"max","low":"min","close":"last"})
    m["rsi14"]=rsi(m.close)
    m["ema10"]=ema(m.close,10); m["ema15"]=ema(m.close,15); m["ema20"]=ema(m.close,20)
    m["mom1"]=m.close.pct_change()*100
    m["max20mom"]=m.mom1.rolling(20,min_periods=1).max()
    m=m.shift(1).reindex(x.index,method="ffill")
    for c in m.columns: x["m_"+c]=m[c]

    w=x.resample("W-FRI").agg({"close":"last"})
    w["rsi14"]=rsi(w.close)
    w=w.shift(1).reindex(x.index,method="ffill")
    x["w_rsi14"]=w.rsi14
    return x

def signal(x,s):
    if s==1:
        return ((x.w_rsi14>=50)&(x.m_rsi14>=50)&(x.m_close>=x.m_ema15)&
                (x.close>=15)&(x.vol20>=15000)&
                ((x.m_close-x.m_ema10)/x.m_ema10<=.30)&(x.m_max20mom>=20))
    if s==2:
        cross1=(x.ema20>x.ema50)&(x.ema20.shift(1)<=x.ema50.shift(1))
        cross2=(x.ema50>x.ema200)&(x.ema50.shift(1)<=x.ema200.shift(1))
        return ((x.max30mom>=5)&(x.close>=15)&(x.vol20>=10000)&
                (x.m_rsi14>=55)&(x.w_rsi14>=50)&(x.pctema10<=.04)&
                (x.ema50>=x.ema250)&(cross1|cross2))
    if s==3:
        return ((x.vwap20*x.vol20>=150_000_000)&(x.close>=x.ema200)&
                (x.w_rsi14>=40)&(x.close<=x.ema50*1.04)&
                (x.close>=x.ema50*.96))
    if s==4:
        cross=(x.ema10>x.ema20)&(x.ema10.shift(1)<=x.ema20.shift(1))
        reclaim=(x.close>x.ema10)&(x.close.shift(1)<=x.ema10.shift(1))
        return ((x.m_mom1>=20)&(x.m_rsi14>=50)&(x.m_ema10>=x.m_ema20)&
                (x.vol30>=50000)&(x.close>=20)&(cross|reclaim)&
                (x.close<=1.03*x.ema20))
    return pd.Series(False,index=x.index)

def run_backtest(d,s,capital,risk,sl,rr,slip,maxpos):
    x=add_features(d).dropna()
    sig=signal(x,s).fillna(False)
    equity=capital
    trades=[]
    for i in range(1,len(x)-1):
        if not sig.iloc[i]: continue
        entry=x.index[i+1]
        ep=float(x.close.iloc[i+1])*(1+slip)
        stop=ep*(1-sl)
        rps=ep-stop
        shares=int((equity*risk)/rps)
        if shares<=0: continue
        target=ep+rr*rps
        exitd=None; exitp=None; reason=""
        for j in range(i+1,len(x)):
            lo=float(x.low.iloc[j]); hi=float(x.high.iloc[j])
            if lo<=stop:
                exitd=x.index[j]; exitp=stop*(1-slip); reason="Stop"; break
            if hi>=target:
                exitd=x.index[j]; exitp=target*(1-slip); reason=f"{rr:g}R Target"; break
            if hi>=ep+2*rps:
                stop=max(stop,ep,float(x.ema10.iloc[j])*(1-slip))
        if exitd is None:
            exitd=x.index[-1]; exitp=float(x.close.iloc[-1])*(1-slip); reason="End"
        pnl=(exitp-ep)*shares
        equity+=pnl
        trades.append({
            "Entry Date":entry.date(),"Exit Date":exitd.date(),
            "Entry":ep,"Exit":exitp,"Return %":(exitp/ep-1)*100,
            "R":pnl/(rps*shares),"PnL ₹":pnl,
            "Holding Days":(exitd-entry).days,"Reason":reason
        })
    return pd.DataFrame(trades), equity

st.sidebar.header("Settings")
start=st.sidebar.date_input("Start",DEFAULT_START)
end=st.sidebar.date_input("End",date.today())
capital=st.sidebar.number_input("Capital (₹)",1000000,step=100000)
risk=st.sidebar.number_input("Risk / trade (%)",1.0,step=.25)/100
sl=st.sidebar.number_input("Stop-loss (%)",7.0,step=.5)/100
rr=st.sidebar.selectbox("Target", [2,2.5,3,3.5,4,5], index=2)
slip=st.sidebar.number_input("Slippage / side (%)",.10,step=.05)/100
maxpos=st.sidebar.number_input("Max positions", value=5, min_value=1, max_value=50, step=1)
st.sidebar.subheader("Universe")
universe=st.sidebar.radio("Select",["Custom CSV","Nifty 500 / Smallcap 100 template"])
uploaded=st.sidebar.file_uploader("CSV with Ticker column",type="csv")

st.sidebar.subheader("Strategies")
selected=st.sidebar.multiselect("Strategies",[1,2,3,4],default=[1,2,3,4],
                                format_func=lambda n:f"Strategy {n}")

st.warning("For Nifty 500/Smallcap 100, upload historical/current constituent CSVs to avoid hard-coding a potentially stale universe. Strategy 3's Chartink exclusion IDs {33489} and {166311} are not reproduced because their definitions are unavailable.")

if uploaded:
    tickers=pd.read_csv(uploaded)["Ticker"].astype(str).str.strip().tolist()
else:
    tickers=[]

if st.button("🚀 Run Backtest",type="primary"):
    if not tickers:
        st.error("Upload a CSV containing a Ticker column first.")
    elif not selected:
        st.error("Select at least one strategy.")
    else:
        alltrades=[]; rows=[]
        progress=st.progress(0)
        for k,t in enumerate(tickers):
            try:
                d=yf_download(t,start,end)
                if len(d)<260: continue
                for s in selected:
                    tr,final=run_backtest(d,s,capital,risk,sl,rr,slip,maxpos)
                    if len(tr):
                        tr["Ticker"]=t; tr["Strategy"]=f"Strategy {s}"
                        alltrades.append(tr)
                        wins=tr[tr.R>0]; losses=tr[tr.R<0]
                        gp=wins["PnL ₹"].sum(); gl=abs(losses["PnL ₹"].sum())
                        rows.append({
                            "Strategy":f"Strategy {s}","Ticker":t,"Trades":len(tr),
                            "Win %":100*len(wins)/len(tr),
                            "Avg Win %":wins["Return %"].mean() if len(wins) else 0,
                            "Avg Loss %":losses["Return %"].mean() if len(losses) else 0,
                            "Expectancy (R)":tr.R.mean(),"Total R":tr.R.sum(),
                            "Profit Factor":gp/gl if gl else np.nan,"Final Equity":final
                        })
            except Exception:
                pass
            progress.progress((k+1)/len(tickers))
        if rows:
            r=pd.DataFrame(rows); trades=pd.concat(alltrades,ignore_index=True)
            st.subheader("Strategy comparison")
            summary=r.groupby("Strategy").agg({
                "Trades":"sum","Win %":"mean","Avg Win %":"mean",
                "Avg Loss %":"mean","Expectancy (R)":"mean",
                "Total R":"sum","Profit Factor":"mean"
            }).reset_index()
            st.dataframe(summary,use_container_width=True)
            st.subheader("Trade log")
            st.dataframe(trades.sort_values("Entry Date"),use_container_width=True)
            st.download_button("⬇️ Download trade log CSV",
                               trades.to_csv(index=False).encode(),
                               "trade_log.csv","text/csv")
        else:
            st.error("No trades found for the selected settings.")

st.markdown("---")
st.caption("Educational backtesting tool. Yahoo Finance data and historical index membership may have limitations. Validate results independently before trading.")
