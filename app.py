import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import date, timedelta

st.set_page_config(page_title="Adaptive Trading Intelligence Lab", page_icon="🧠", layout="wide")

# ========================= DATA =========================

INDEX_URLS = {
    "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "Nifty Smallcap 100": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",
    "Nifty Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "Nifty Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
}

@st.cache_data(ttl=86400)
def index_universe(name):
    r = requests.get(INDEX_URLS[name], headers={"User-Agent":"Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(r.content))
    col = next(c for c in df.columns if str(c).strip().upper() == "SYMBOL")
    return sorted({str(s).strip().upper()+".NS" for s in df[col].dropna()})

@st.cache_data(ttl=1800)
def download_prices(tickers, start, end):
    tickers = tuple(tickers)
    if not tickers:
        return {}
    raw = yf.download(list(tickers), start=start, end=end+timedelta(days=1),
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
            d = d.dropna(subset=["close"])
            if not d.empty:
                out[t] = d
        except Exception:
            pass
    return out

@st.cache_data(ttl=3600)
def company_info(ticker):
    t = yf.Ticker(ticker)
    try: info = t.info
    except Exception: info = {}
    try: news = t.news[:10]
    except Exception: news = []
    return info, news

# ========================= INDICATORS =========================

def ema(s,n): return s.ewm(span=n,adjust=False,min_periods=n).mean()
def sma(s,n): return s.rolling(n,min_periods=n).mean()

def rsi(s,n=14):
    d=s.diff()
    up=d.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=up/dn.replace(0,np.nan)
    return 100-100/(1+rs)

def features(d):
    x=d.copy()
    for n in [10,20,50,200,250]:
        x[f"ema{n}"]=ema(x.close,n)
    x["vol20"]=sma(x.volume,20)
    x["vol30"]=sma(x.volume,30)
    x["rsi14"]=rsi(x.close)
    x["relvol"]=x.volume/x.vol20

    tr=pd.concat([x.high-x.low,(x.high-x.close.shift()).abs(),
                  (x.low-x.close.shift()).abs()],axis=1).max(axis=1)
    x["atr14"]=tr.rolling(14).mean()

    w=x.resample("W-FRI").close.last().to_frame()
    w["rsi"]=rsi(w["close"]); w["ema20"]=ema(w["close"],20); w["ema50"]=ema(w["close"],50)
    w=w.shift(1).reindex(x.index,method="ffill")
    x["wrsi14"]=w["rsi"]; x["wema20"]=w["ema20"]; x["wema50"]=w["ema50"]; x["wclose"]=w["close"]

    m=x.resample("ME").agg({"close":"last","open":"first","high":"max","low":"min"})
    m["rsi"]=rsi(m.close); m["ema10"]=ema(m.close,10); m["ema15"]=ema(m.close,15)
    m["ema20"]=ema(m.close,20); m["mom"]=m.close.pct_change()*100
    m=m.shift(1).reindex(x.index,method="ffill")
    x["mclose"]=m.close; x["mrsi14"]=m.rsi; x["mema10"]=m.ema10
    x["mema15"]=m.ema15; x["mema20"]=m.ema20; x["mmom"]=m.mom
    return x

# ========================= STRATEGIES =========================

def strategy_signal(x,s):
    if s==1:
        return ((x.wrsi14>=50)&(x.mrsi14>=50)&(x.mclose>=x.mema15)&
                (x.close>=15)&(x.vol20>=15000)&
                (((x.mclose-x.mema10)/x.mema10)<=.30))
    if s==2:
        cross=(x.ema20>x.ema50)&(x.ema20.shift(1)<=x.ema50.shift(1))
        return ((x.close>=15)&(x.vol20>=10000)&(x.mrsi14>=55)&(x.wrsi14>=50)&
                (((x.close-x.ema10)/x.ema10)<=.04)&(x.ema50>=x.ema250)&cross)
    if s==3:
        vwap=(x.close*x.volume).rolling(20).sum()/x.volume.rolling(20).sum()
        return ((vwap*x.vol20>=150_000_000)&(x.close>=x.ema200)&(x.wrsi14>=40)&
                (x.close>=x.ema50*.96)&(x.close<=x.ema50*1.04))
    if s==4:
        cross=(x.ema10>x.ema20)&(x.ema10.shift(1)<=x.ema20.shift(1))
        reclaim=(x.close>x.ema10)&(x.close.shift(1)<=x.ema10.shift(1))
        return ((x.mmom>=20)&(x.mrsi14>=50)&(x.mema10>=x.mema20)&
                (x.vol30>=50000)&(x.close>=20)&(cross|reclaim)&
                (x.close<=x.ema20*1.03))
    return pd.Series(False,index=x.index)

# ========================= MARKET REGIME =========================

def regime_from_index(d):
    x=features(d).dropna()
    if len(x)<30: return "UNKNOWN",0
    z=x.iloc[-1]
    score=0
    score += 25 if z.close>z.ema200 else 0
    score += 20 if z.ema50>z.ema200 else 0
    score += 15 if z.ema200>x.ema200.iloc[-20] else 0
    score += 15 if z.rsi14>=55 else 0
    score += 10 if z.close>z.ema20 else 0
    score += 15 if z.relvol>=1 else 0
    if score>=75: return "STRONG BULL",score
    if score>=60: return "BULL",score
    if score>=45: return "RECOVERY / SIDEWAYS",score
    if score>=30: return "EARLY BEAR",score
    return "BEAR",score

# ========================= SMALL/MICRO SAFETY =========================

def safety(info,d):
    score=100; flags=[]
    avg_value=float((d.close*d.volume).tail(20).mean()) if d is not None and not d.empty else 0
    debt=info.get("debtToEquity")
    insider=info.get("heldPercentInsiders")
    if avg_value<2_000_000: score-=30; flags.append("Low traded value")
    if avg_value<500_000: score-=20; flags.append("Very low liquidity")
    if d is not None and len(d)>=30:
        r=d.close.pct_change().tail(30)
        if (r.abs()>.15).sum()>=3: score-=15; flags.append("Abnormal volatility")
    if isinstance(debt,(int,float)) and np.isfinite(debt) and debt>200:
        score-=15; flags.append("High debt/equity")
    if isinstance(insider,(int,float)) and np.isfinite(insider) and insider<.25:
        score-=5; flags.append("Low insider holding")
    score=max(0,min(100,score))
    status="ELIGIBLE" if score>=70 else ("CAUTION" if score>=50 else "REJECT")
    return score,status,flags

# ========================= SCORE =========================

def setup_score(x,s,regime,safety_score):
    z=x.iloc[-1]
    score=0
    score += 15 if regime in ("STRONG BULL","BULL") else (8 if regime=="RECOVERY / SIDEWAYS" else 0)
    score += 8 if z.close>z.ema50 else 0
    score += 7 if z.wrsi14>=50 else 0
    score += 5 if z.mrsi14>=50 else 0
    score += 5 if z.mema10>=z.mema20 else 0
    score += 5 if z.relvol>=1.2 else 0
    score += 5 if 0 <= z.close/z.ema20-1 <= .03 else 0
    score += 5 if z.rsi14>=50 else 0
    score += 5 if z.close>=z.ema50 else 0
    score += 15 if safety_score>=85 else (10 if safety_score>=70 else 0)
    score += 15 if s==4 else 12
    return int(max(0,min(100,score)))

# ========================= FUNDAMENTAL SCORING =========================

def val(info,*keys):
    for k in keys:
        v=info.get(k)
        if isinstance(v,(int,float)) and np.isfinite(v): return float(v)
    return np.nan

def model_a(info):
    checks={
        "Market Cap > 5000Cr": val(info,"marketCap")>5000e7,
        "EPS > 15": val(info,"trailingEps")>15,
        "ROE > 15%": val(info,"returnOnEquity")>.15,
        "Debt/Equity < 0.5": val(info,"debtToEquity")<50,
        "P/FCF > 0": val(info,"priceToFreeCashFlow")>0,
        "Net margin > 10%": val(info,"profitMargins")>.10,
        "P/E < 25": val(info,"trailingPE")<25,
        "Current ratio > 1.5": val(info,"currentRatio")>1.5,
        "Dividend yield > 1%": val(info,"dividendYield")>.01,
        "Operating margin > 15%": val(info,"operatingMargins")>.15,
        "Promoter/insider > 40%": val(info,"heldPercentInsiders")>.40,
    }
    unavailable=[]
    for label,key in [
        ("P/FCF","priceToFreeCashFlow"),("Current ratio","currentRatio"),
        ("Promoter holding","heldPercentInsiders")]:
        if not np.isfinite(val(info,key)): unavailable.append(label)
    return checks,unavailable

def model_b(info):
    checks={
        "Market Cap 200-20000Cr": 200e7<val(info,"marketCap")<20000e7,
        "Quarterly sales growth >10%": val(info,"revenueGrowth")>.10,
        "Quarterly profit growth >10%": val(info,"earningsGrowth")>.10,
        "ROE >15%": val(info,"returnOnEquity")>.15,
    }
    unavailable=[]
    if not np.isfinite(val(info,"piotroskiScore")): unavailable.append("Piotroski score")
    return checks,unavailable

# ========================= BACKTEST =========================

def run_backtest(d,sig,capital,risk,sl,rr,slip=.001):
    x=features(d).dropna(); sig=sig.reindex(x.index).fillna(False)
    equity=capital; rows=[]; i=0
    while i<len(x)-1:
        if not bool(sig.iloc[i]): i+=1; continue
        ei=i+1; entry=float(x.close.iloc[ei])*(1+slip)
        stop=entry*(1-sl); one_r=entry-stop
        qty=int(equity*risk/one_r)
        if qty<1: i+=1; continue
        target=entry+rr*one_r; ex=ep=None; reason=""
        for j in range(ei,len(x)):
            lo=float(x.low.iloc[j]); hi=float(x.high.iloc[j])
            if lo<=stop: ex,ep,reason=j,stop*(1-slip),"SL"; break
            if hi>=target: ex,ep,reason=j,target*(1-slip),f"{rr}R"; break
            if hi>=entry+2*one_r:
                stop=max(stop,entry)
                if pd.notna(x.ema10.iloc[j]): stop=max(stop,float(x.ema10.iloc[j])*(1-slip))
        if ex is None: ex,ep,reason=len(x)-1,float(x.close.iloc[-1])*(1-slip),"End"
        pnl=(ep-entry)*qty; equity+=pnl
        rows.append({"Entry Date":x.index[ei].date(),"Exit Date":x.index[ex].date(),
                     "Entry":entry,"Exit":ep,"Return %":(ep/entry-1)*100,
                     "R":pnl/(one_r*qty),"PnL ₹":pnl,
                     "Holding Days":(x.index[ex]-x.index[ei]).days,"Reason":reason})
        i=ex+1
    return pd.DataFrame(rows),equity

def stats(t):
    if t.empty:return {}
    w=t[t.R>0]; l=t[t.R<0]; gp=w["PnL ₹"].sum(); gl=abs(l["PnL ₹"].sum())
    return {"Trades":len(t),"Win %":round(len(w)/len(t)*100,2),
            "Avg Win %":round(w["Return %"].mean(),2) if len(w) else 0,
            "Avg Loss %":round(l["Return %"].mean(),2) if len(l) else 0,
            "Expectancy R":round(t.R.mean(),3),"Total R":round(t.R.sum(),2),
            "Profit Factor":round(gp/gl,2) if gl else np.nan}

# ========================= UI =========================

st.title("🧠 Adaptive Trading Intelligence Lab")
st.caption("MTF swing research • 4 strategies • ≥85 forward-test gate • market-cycle learning • separate long-term investment engine")

tabs=st.tabs([
    "🏠 Dashboard","📡 Daily Scanner","📊 Backtest","🔬 Forward Testing",
    "🧠 Market Learning","💎 Long-Term Fundamentals","🏢 Small/Micro Safety","🧪 Custom Strategy"
])

with tabs[0]:
    a,b,c,d=st.columns(4)
    a.metric("Forward-test gate","≥85")
    b.metric("Strategies","4")
    c.metric("MTF","Monthly / Weekly / Daily")
    d.metric("Real orders","OFF")
    st.info("The score ranks setup quality. It is not a guaranteed probability of winning.")
    st.markdown("""
**Trading engine:** Strategies 1–4 → MTF → market regime → setup score → forward test.

**Investment engine:** Fundamental Model A / B scans the broader cash market separately.

**Safety engine:** Small/micro-cap liquidity and abnormal-volatility checks reduce risk but do not change the four strategies.
""")

with tabs[1]:
    st.subheader("📡 Daily High-Quality Scanner")
    a,b,c=st.columns(3)
    universes=a.multiselect("Trading universes",
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        ["Nifty 500","Nifty Smallcap 250"],key="scan_universes")
    min_score=b.number_input("Minimum score",value=85,min_value=85,max_value=100,key="scan_score")
    max_candidates=c.number_input("Maximum candidates",value=10,min_value=1,max_value=50,key="scan_max")
    st.caption("Only candidates scoring at least 85 enter the forward-test queue.")

    if st.button("🔄 Scan Market Now",type="primary",key="scan_button"):
        try:
            # Nifty 500 constituents are used for the market proxy calculation.
            idx_tickers=index_universe("Nifty 500")
            idx_data=download_prices(tuple(idx_tickers),date.today()-timedelta(days=450),date.today())
            regime="UNKNOWN"; regime_score=0
            if idx_data:
                proxy=max(idx_data.values(),key=len)
                regime,regime_score=regime_from_index(proxy)

            st.success(f"Market regime: {regime} | score {regime_score}/100")

            universe=set()
            for u in universes: universe.update(index_universe(u))
            tickers=sorted(universe)
            data=download_prices(tuple(tickers),date.today()-timedelta(days=450),date.today())
            rows=[]; bar=st.progress(0)

            for n,(ticker,df) in enumerate(data.items()):
                if len(df)<260:
                    bar.progress((n+1)/max(1,len(data))); continue
                f=features(df).dropna()
                if f.empty:
                    bar.progress((n+1)/max(1,len(data))); continue
                info,_=company_info(ticker)
                safe,safe_status,flags=safety(info,df)

                for s in [1,2,3,4]:
                    sig=strategy_signal(f,s)
                    if bool(sig.iloc[-1]) and safe_status!="REJECT":
                        score=setup_score(f,s,regime,safe)
                        if score>=min_score:
                            z=f.iloc[-1]; entry=float(z.close); stop=entry*.93; target=entry+3*(entry-stop)
                            rows.append({
                                "Score":score,"Ticker":ticker.replace(".NS",""),"Strategy":f"S{s}",
                                "Regime":regime,"Safety":safe_status,
                                "Entry":round(entry,2),"SL":round(stop,2),"Target 3R":round(target,2),
                                "R:R":"1:3","RSI":round(float(z.rsi14),1),
                                "RelVol":round(float(z.relvol),2),"Daily EMA20":round(float(z.ema20),2),
                                "Safety Score":safe,"Safety Flags":", ".join(flags)
                            })
                bar.progress((n+1)/max(1,len(data)))

            result=pd.DataFrame(rows)
            if result.empty:
                st.warning("No setup scored 85+ today. No trade is a valid decision.")
            else:
                result=result.sort_values(["Score","Strategy"],ascending=[False,True]).head(int(max_candidates))
                st.session_state["forward_queue"]=result
                st.dataframe(result,use_container_width=True,hide_index=True)
                st.success(f"{len(result)} high-quality setups entered the forward-test queue.")
                st.download_button("⬇️ Download scan CSV",result.to_csv(index=False).encode(),"daily_scan.csv",key="scan_download")
        except Exception as e:
            st.error(f"Scanner error: {e}")

with tabs[2]:
    st.subheader("📊 Backtest Strategies 1–4")
    a,b,c=st.columns(3)
    uni=a.selectbox("Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],key="bt_universe")
    start=b.date_input("Start",date.today()-timedelta(days=730),key="bt_start")
    end=c.date_input("End",date.today(),key="bt_end")
    a,b,c,d=st.columns(4)
    capital=a.number_input("Capital ₹",value=1_000_000,step=100_000,key="bt_capital")
    risk=b.number_input("Risk %",value=1.0,step=.25,key="bt_risk")
    sl=b.number_input("SL %",value=7.0,step=.5,key="bt_sl")
    rr=d.selectbox("Target R",[2,2.5,3,3.5,4,5],index=2,key="bt_rr")
    selected=st.multiselect("Strategies",[1,2,3,4],[1,2,3,4],key="bt_strategies")
    if st.button("🚀 Run Backtest",type="primary",key="bt_run"):
        try:
            tickers=index_universe(uni); data=download_prices(tuple(tickers),start,end)
            logs=[]; summary=[]; bar=st.progress(0)
            for n,(ticker,df) in enumerate(data.items()):
                if len(df)>=260:
                    f=features(df)
                    for s in selected:
                        try:
                            tr,_=run_backtest(df,strategy_signal(f,s),capital,risk/100,sl/100,rr)
                            if not tr.empty:
                                tr["Ticker"]=ticker; tr["Strategy"]=f"S{s}"; logs.append(tr)
                                m=stats(tr);m["Strategy"]=f"S{s}";summary.append(m)
                        except Exception: pass
                bar.progress((n+1)/max(1,len(data)))
            if summary:
                alltrades=pd.concat(logs,ignore_index=True)
                board=pd.DataFrame(summary).groupby("Strategy").mean(numeric_only=True).sort_values("Expectancy R",ascending=False)
                st.subheader("🏆 Strategy comparison");st.dataframe(board,use_container_width=True)
                st.dataframe(alltrades,use_container_width=True,hide_index=True)
                st.download_button("⬇️ Download backtest",alltrades.to_csv(index=False).encode(),"backtest.csv",key="bt_download")
            else: st.warning("No qualifying trades.")
        except Exception as e: st.error(f"Backtest error: {e}")

with tabs[3]:
    st.subheader("🔬 Forward Testing — Score ≥85")
    q=st.session_state.get("forward_queue",pd.DataFrame())
    if q.empty: st.info("Run the Daily Scanner first.")
    else:
        st.dataframe(q,use_container_width=True,hide_index=True)
        st.download_button("⬇️ Export forward queue",q.to_csv(index=False).encode(),"forward_queue.csv",key="forward_queue_download")

    st.markdown("### Record completed paper trade")
    a,b,c,d=st.columns(4)
    ticker=a.text_input("Ticker",key="ft_ticker")
    entry=b.number_input("Entry",min_value=0.0,key="ft_entry")
    exitp=c.number_input("Exit",min_value=0.0,key="ft_exit")
    rres=d.number_input("R result",value=0.0,step=.25,key="ft_r")
    reason=st.selectbox("Exit reason",["Target","Stop","Trailing stop","Time exit","Invalidated"],key="ft_reason")
    notes=st.text_area("Notes / mistake",key="ft_notes")
    if st.button("💾 Save Forward Result",key="ft_save"):
        row=pd.DataFrame([{"Date":str(date.today()),"Ticker":ticker,"Entry":entry,"Exit":exitp,"R":rres,"Reason":reason,"Notes":notes}])
        st.session_state["forward_results"]=pd.concat([st.session_state.get("forward_results",pd.DataFrame()),row],ignore_index=True)
        st.success("Forward result recorded.")
    if "forward_results" in st.session_state:
        st.dataframe(st.session_state["forward_results"],use_container_width=True,hide_index=True)

with tabs[4]:
    st.subheader("🧠 Market-Cycle Learning")
    st.warning("The learning layer records evidence and compares performance. It does not rewrite Strategy 1–4 rules.")
    r=st.session_state.get("forward_results",pd.DataFrame())
    if r.empty:
        st.info("No forward-test results yet.")
    else:
        a,b=st.columns(2)
        a.metric("Forward expectancy",f"{r.R.mean():.3f}R")
        b.metric("Total R",f"{r.R.sum():.2f}R")
        st.dataframe(r,use_container_width=True,hide_index=True)
    st.markdown("""
### Strategy × Market Cycle
After enough forward trades, the dashboard will populate:

| Market cycle | S1 | S2 | S3 | S4 |
|---|---:|---:|---:|---:|
| Strong Bull | — | — | — | — |
| Bull | — | — | — | — |
| Recovery | — | — | — | — |
| Sideways | — | — | — | — |
| Early Bear | — | — | — | — |
| Bear | — | — | — | — |

The numbers must be earned from forward/out-of-sample results.

### Score calibration
The system will also learn whether 85–89, 90–94 and 95–100 actually have different historical outcomes. A score is not called a probability until enough forward data proves it is calibrated.
""")

with tabs[5]:
    st.subheader("💎 Long-Term Fundamental Scanner")
    st.warning("Completely separate from Strategies 1–4. This is for finding long-term investment candidates in the wider Indian cash market.")
    model=st.radio("Model",["Model A — Quality / Value","Model B — Growth / Piotroski"],horizontal=True,key="fund_model")
    limit=st.number_input("Stocks to analyse this run",value=100,min_value=10,max_value=500,key="fund_limit")
    st.caption("Yahoo Finance does not reliably expose every Screener.in field. Missing fields are shown as unavailable rather than guessed.")
    if st.button("🔎 Run Fundamental Scan",type="primary",key="fund_scan"):
        st.warning("Fundamental API is intentionally paused for now. We will connect a dedicated fundamental-data API after the live trading scanner is fully validated. No Yahoo field is being substituted for your Screener.in rules.")

with tabs[6]:
    st.subheader("🏢 Small/Micro-Cap Safety")
    st.write("These are risk controls only. They do not change the four strategy rules.")
    st.markdown("""
- Minimum traded-value check
- Very-low-liquidity warning
- Abnormal-volatility warning
- Debt/equity warning where available
- Insider/promoter holding warning where available

**🟢 Eligible / 🟡 Caution / 🔴 Reject**

These checks cannot guarantee that a company is free from manipulation, governance problems or accounting risk.
""")

with tabs[7]:
    st.subheader("🧪 Custom Strategy Lab")
    st.text_area("Paste your strategy",height=220,key="custom_strategy",
                 placeholder="Example: RSI > 55, close > 200 EMA, volume > 1.5x 20-day average. SL 7%, target 3R.")
    st.selectbox("Market",["Indian Stocks","Forex","Crypto"],key="custom_market")
    st.selectbox("Style",["Intraday","Swing","Positional"],key="custom_style")
    st.selectbox("Timeframe",["5m","15m","1h","4h","Daily","Weekly"],key="custom_tf")
    if st.button("🔍 Validate Strategy",key="custom_validate"):
        st.success("Strategy received. Convert ambiguous language into explicit testable rules before backtesting.")

st.markdown("---")
st.caption("Research / paper-testing system. Real-money Dhan order execution is intentionally disabled.")
