import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import sqlite3
import time
import threading
import queue
import json
from datetime import date, timedelta, datetime

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


# ========================= DHAN PERSISTENT DATA ENGINE =========================
DHAN_BASE_URL="https://api.dhan.co/v2"
DATA_DB="market_data.sqlite3"

def dhan_configured():
    try:
        return bool(st.secrets["DHAN_CLIENT_ID"]) and bool(st.secrets["DHAN_ACCESS_TOKEN"])
    except Exception:
        return False

def _dhan_headers():
    return {
        "access-token":str(st.secrets["DHAN_ACCESS_TOKEN"]),
        "client-id":str(st.secrets["DHAN_CLIENT_ID"]),
        "Content-Type":"application/json","Accept":"application/json"
    }

def _db():
    con=sqlite3.connect(DATA_DB,timeout=60,check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS candles(
        symbol TEXT NOT NULL, dt TEXT NOT NULL, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY(symbol,dt))""")
    con.execute("""CREATE TABLE IF NOT EXISTS forward_tests(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, symbol TEXT,
        strategy TEXT, score REAL, regime TEXT, entry REAL, sl REAL, target REAL,
        status TEXT DEFAULT 'ACTIVE', ltp REAL, mfe REAL DEFAULT 0,
        mae REAL DEFAULT 0, exit_price REAL, result_r REAL, updated_at TEXT)""")
    con.commit(); return con

@st.cache_data(ttl=86400,show_spinner=False)
def dhan_master():
    urls=["https://images.dhan.co/api-data/api-scrip-master.csv",
          "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"]
    last=""
    for u in urls:
        try:
            r=requests.get(u,timeout=45); r.raise_for_status()
            if len(r.content)>1000:return pd.read_csv(io.BytesIO(r.content),low_memory=False)
        except Exception as e:last=str(e)
    raise RuntimeError("Dhan instrument master failed: "+last)

@st.cache_data(ttl=86400,show_spinner=False)
def dhan_map():
    m=dhan_master()
    cols={str(c).strip().lower():c for c in m.columns}
    sym=next((cols[k] for k in ["sem_trading_symbol","trading_symbol","sem_custom_symbol","custom_symbol"] if k in cols),None)
    sid=next((cols[k] for k in ["sem_smst_security_id","sem_security_id","security_id"] if k in cols),None)
    ex=next((cols[k] for k in ["sem_exm_exch_id","exchange"] if k in cols),None)
    seg=next((cols[k] for k in ["sem_segment","segment"] if k in cols),None)
    if not sym or not sid:raise RuntimeError("Dhan symbol/Security ID columns not found")
    keep=[sym,sid]+([ex] if ex else [])+([seg] if seg else [])
    m=m[keep].copy()
    names=["symbol","security_id"]+((["exchange"] if ex else [])+(["segment"] if seg else []))
    m.columns=names
    m.symbol=m.symbol.astype(str).str.upper().str.strip()
    if ex:
        m=m[m.exchange.astype(str).str.upper().isin(["NSE","NSE_EQ"])]
    if seg:
        sv=m.segment.astype(str).str.upper().str.strip()
        q=sv.isin(["E","EQUITY","NSE_EQ"])
        if q.any():m=m[q]
    return dict(zip(m.symbol,m.security_id.astype(str)))

def dhan_history(symbol,start_date,end_date):
    clean=str(symbol).upper().replace(".NS","")
    sid=dhan_map().get(clean)
    if not sid:raise ValueError("Security ID not found: "+clean)
    payload={"securityId":sid,"exchangeSegment":"NSE_EQ","instrument":"EQUITY",
             "expiryCode":0,"oi":False,
             "fromDate":pd.Timestamp(start_date).strftime("%Y-%m-%d"),
             "toDate":pd.Timestamp(end_date).strftime("%Y-%m-%d")}
    r=requests.post(f"{DHAN_BASE_URL}/charts/historical",headers=_dhan_headers(),
                    json=payload,timeout=45)
    if not r.ok:raise RuntimeError(f"Dhan historical {r.status_code}: {r.text[:250]}")
    j=r.json()
    if "close" not in j:raise RuntimeError("Unexpected Dhan historical response")
    d=pd.DataFrame({k:j.get(k,[]) for k in ["open","high","low","close","volume"]})
    if j.get("timestamp"):d.index=pd.to_datetime(j["timestamp"],unit="s",errors="coerce")
    d=d.apply(pd.to_numeric,errors="coerce").dropna(subset=["close"]).sort_index()
    return d

def _bounds(con,s):
    return con.execute("SELECT MIN(dt),MAX(dt) FROM candles WHERE symbol=?",(s,)).fetchone()

def _save(con,s,d):
    if d.empty:return 0
    rows=[(s,pd.Timestamp(i).strftime("%Y-%m-%d"),float(r.open),float(r.high),
           float(r.low),float(r.close),float(r.volume)) for i,r in d.iterrows()]
    con.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?)",rows)
    con.commit();return len(rows)

def update_dhan_symbol(symbol,start_date,end_date):
    s=str(symbol).upper().replace(".NS","");con=_db()
    try:
        mn,mx=_bounds(con,s)
        if not mn:return _save(con,s,dhan_history(s,start_date,end_date))
        n=0;mn=pd.Timestamp(mn).date();mx=pd.Timestamp(mx).date()
        if pd.Timestamp(start_date).date()<mn:n+=_save(con,s,dhan_history(s,start_date,mn-timedelta(days=1)))
        if pd.Timestamp(end_date).date()>mx:n+=_save(con,s,dhan_history(s,mx+timedelta(days=1),end_date))
        return n
    finally:con.close()

def _read_cache(con,s,start_date,end_date):
    d=pd.read_sql_query("""SELECT dt,open,high,low,close,volume FROM candles
        WHERE symbol=? AND dt>=? AND dt<=? ORDER BY dt""",con,
        params=(s,pd.Timestamp(start_date).strftime("%Y-%m-%d"),pd.Timestamp(end_date).strftime("%Y-%m-%d")))
    if d.empty:return pd.DataFrame()
    d.dt=pd.to_datetime(d.dt);d=d.set_index("dt");d.index.name="date";return d

def download_prices(tickers,start,end):
    if not dhan_configured():raise RuntimeError("Dhan credentials are not configured")
    dhan_map()
    # Conservative concurrency for first-time data build; repeated scans are cache-only.
    from concurrent.futures import ThreadPoolExecutor,as_completed
    with ThreadPoolExecutor(max_workers=3) as ex:
        fs={ex.submit(update_dhan_symbol,t,start,end):t for t in tickers}
        for f in as_completed(fs):
            try:f.result()
            except Exception:pass
    con=_db();out={}
    try:
        for t in tickers:
            d=_read_cache(con,str(t).upper().replace(".NS",""),start,end)
            if not d.empty:out[t]=d
    finally:con.close()
    return out

def dhan_live_ltp(symbols):
    mp=dhan_map()
    pairs=[(mp[s.replace(".NS","").upper()],s.replace(".NS","").upper())
           for s in symbols if s.replace(".NS","").upper() in mp]
    if not pairs:return {}
    r=requests.post(f"{DHAN_BASE_URL}/marketfeed/ltp",headers=_dhan_headers(),
                    json={"NSE_EQ":[int(a) for a,b in pairs]},timeout=20)
    r.raise_for_status()
    raw=r.json().get("data",{}).get("NSE_EQ",{});rev={a:b for a,b in pairs}
    return {rev[str(k)]:float(v["last_price"]) for k,v in raw.items()
            if str(k) in rev and isinstance(v,dict) and v.get("last_price") is not None}

@st.cache_data(ttl=3600)
def _ensure_ws_tables():
    con=_db()
    con.execute("""CREATE TABLE IF NOT EXISTS live_ticks(
        symbol TEXT NOT NULL, ts TEXT NOT NULL, ltp REAL,
        ltt INTEGER, volume REAL, buy_qty REAL, sell_qty REAL,
        PRIMARY KEY(symbol,ts))""")
    con.commit(); con.close()


# ========================= PERSISTENT DHAN WEBSOCKET =========================
class DhanLiveManager:
    """
    One persistent market-hours WebSocket for the active forward-test list.
    It runs outside the Streamlit UI thread, reconnects automatically, and
    stores the latest tick in SQLite. The UI reads the stored latest prices.
    """
    def __init__(self):
        self.thread=None
        self.stop_event=threading.Event()
        self.lock=threading.Lock()
        self.symbols=()
        self.status="STOPPED"
        self.last_error=""
        self.last_tick=None

    def _set_status(self,status,error=""):
        with self.lock:
            self.status=status
            self.last_error=error

    def update_symbols(self,symbols):
        clean=tuple(sorted({str(s).upper().replace(".NS","") for s in symbols if str(s).strip()}))
        with self.lock:
            changed=clean!=self.symbols
            self.symbols=clean
        if changed and clean and (self.thread is None or not self.thread.is_alive()):
            self.start()
        return changed

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread=threading.Thread(
            target=self._run,
            name="dhan-live-feed",
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self._set_status("STOPPING")

    def _run(self):
        # The official DhanHQ-py MarketFeed handles the websocket protocol.
        from dhanhq import DhanContext, MarketFeed

        backoff=2
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    symbols=list(self.symbols)
                if not symbols:
                    self._set_status("WAITING")
                    self.stop_event.wait(2)
                    continue

                mp=dhan_map()
                instruments=[]
                reverse={}
                for s in symbols:
                    sid=mp.get(s)
                    if sid:
                        instruments.append((MarketFeed.NSE,str(sid),MarketFeed.Ticker))
                        reverse[str(sid)]=s

                if not instruments:
                    self._set_status("WAITING","No Dhan security IDs found for active candidates")
                    self.stop_event.wait(5)
                    continue

                self._set_status("CONNECTING")
                ctx=DhanContext(
                    str(st.secrets["DHAN_CLIENT_ID"]),
                    str(st.secrets["DHAN_ACCESS_TOKEN"])
                )
                feed=MarketFeed(ctx,instruments,version="v2")
                feed.run_forever()
                self._set_status("CONNECTED")
                backoff=2

                while not self.stop_event.is_set():
                    data=feed.get_data()
                    if not data:
                        time.sleep(0.05)
                        continue

                    packets=data if isinstance(data,list) else [data]
                    for pkt in packets:
                        if not isinstance(pkt,dict):
                            continue
                        sid=str(pkt.get("security_id",pkt.get("SecurityId","")))
                        symbol=reverse.get(sid)
                        ltp=pkt.get("LTP",pkt.get("last_price",pkt.get("LastTradedPrice")))
                        if not symbol or ltp is None:
                            continue
                        self._save_tick(symbol,float(ltp),pkt)

                try:
                    feed.disconnect()
                except Exception:
                    pass

            except Exception as e:
                self._set_status("RECONNECTING",str(e))
                # Automatic reconnect with capped exponential backoff.
                self.stop_event.wait(backoff)
                backoff=min(backoff*2,30)

        self._set_status("STOPPED")

    def _save_tick(self,symbol,ltp,pkt):
        now=datetime.now().isoformat(timespec="seconds")
        con=_db()
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS live_latest(
                    symbol TEXT PRIMARY KEY, ts TEXT, ltp REAL,
                    volume REAL, raw TEXT
                )
            """)
            con.execute("""
                INSERT OR REPLACE INTO live_latest(symbol,ts,ltp,volume,raw)
                VALUES(?,?,?,?,?)
            """,(
                symbol,now,ltp,
                pkt.get("volume",pkt.get("Volume")),
                str(pkt)
            ))
            con.commit()
        finally:
            con.close()
        with self.lock:
            self.last_tick=now
            self.status="LIVE"

    def snapshot(self):
        with self.lock:
            return self.status,self.last_error,self.last_tick,list(self.symbols)

@st.cache_resource
def get_dhan_live_manager():
    return DhanLiveManager()

def start_persistent_live_feed(symbols):
    mgr=get_dhan_live_manager()
    mgr.update_symbols(symbols)
    mgr.start()
    return mgr

def stop_persistent_live_feed():
    mgr=get_dhan_live_manager()
    mgr.stop()
    return mgr

def read_live_prices(symbols=None):
    con=_db()
    try:
        if symbols:
            clean=[str(s).upper().replace(".NS","") for s in symbols]
            placeholders=",".join(["?"]*len(clean))
            q=pd.read_sql_query(
                f"SELECT symbol,ts,ltp,volume FROM live_latest WHERE symbol IN ({placeholders})",
                con,params=clean
            )
        else:
            q=pd.read_sql_query("SELECT symbol,ts,ltp,volume FROM live_latest",con)
    except Exception:
        q=pd.DataFrame(columns=["symbol","ts","ltp","volume"])
    finally:
        con.close()
    return q

def live_forward_test_table():
    con=_db()
    try:
        q=pd.read_sql_query(
            "SELECT * FROM forward_tests WHERE status='ACTIVE' ORDER BY score DESC",con
        )
    finally:
        con.close()
    if q.empty:
        return q

    live=read_live_prices(q.symbol.tolist())
    if not live.empty:
        q=q.merge(live[["symbol","ts","ltp"]],on="symbol",how="left")
        q["LTP"]=q["ltp"]
        q["P/L %"]=(q["LTP"]/q["entry"]-1)*100
        q["Live Updated"]=q["ts"]
    return q

def live_forward_test_table():
    con=_db()
    try:
        q=pd.read_sql_query(
            "SELECT * FROM forward_tests WHERE status='ACTIVE' ORDER BY score DESC",con
        )
    finally: con.close()
    if q.empty:return q
    try:
        live=dhan_websocket_snapshot(q.symbol.tolist(),seconds=3,mode="Ticker")
        if not live.empty:
            q=q.merge(live[["symbol","ltp"]],on="symbol",how="left",suffixes=("","_ws"))
            q["LTP"]=q["ltp_ws"].combine_first(q["ltp"])
            q.drop(columns=["ltp_ws"],inplace=True)
            q["P/L %"]=(q["LTP"]/q["entry"]-1)*100
    except Exception as e:
        q["WebSocket Error"]=str(e)
    return q

def company_info(ticker):
    return {}, []


# ========================= FOREX + CRYPTO DATA ENGINE =========================
TWELVE_BASE="https://api.twelvedata.com"

def twelvedata_configured():
    try:
        return bool(st.secrets["TWELVEDATA_API_KEY"])
    except Exception:
        return False

def _td_headers():
    return {"Authorization":f"apikey {str(st.secrets['TWELVEDATA_API_KEY'])}"}

@st.cache_data(ttl=86400,show_spinner=False)
def td_history(symbol, interval="1day", start_date=None, end_date=None, outputsize=5000):
    """Historical OHLCV for Forex and Crypto through Twelve Data."""
    if not twelvedata_configured():
        raise RuntimeError("TWELVEDATA_API_KEY is not configured in Streamlit Secrets.")
    params={"symbol":symbol,"interval":interval,"outputsize":int(outputsize)}
    if start_date is not None: params["start_date"]=pd.Timestamp(start_date).strftime("%Y-%m-%d")
    if end_date is not None: params["end_date"]=pd.Timestamp(end_date).strftime("%Y-%m-%d")
    r=requests.get(f"{TWELVE_BASE}/time_series",headers=_td_headers(),params=params,timeout=45)
    if not r.ok: raise RuntimeError(f"Twelve Data {r.status_code}: {r.text[:300]}")
    j=r.json()
    if j.get("status")=="error": raise RuntimeError(j.get("message","Twelve Data error"))
    vals=j.get("values",[])
    if not vals: return pd.DataFrame(columns=["open","high","low","close","volume"])
    d=pd.DataFrame(vals)
    d["datetime"]=pd.to_datetime(d["datetime"],errors="coerce")
    d=d.set_index("datetime").sort_index()
    for c in ["open","high","low","close","volume"]:
        if c in d.columns:d[c]=pd.to_numeric(d[c],errors="coerce")
        else:d[c]=np.nan
    return d[["open","high","low","close","volume"]].dropna(subset=["close"])

@st.cache_data(ttl=30,show_spinner=False)
def td_price(symbol):
    if not twelvedata_configured():
        raise RuntimeError("TWELVEDATA_API_KEY is not configured in Streamlit Secrets.")
    r=requests.get(f"{TWELVE_BASE}/price",headers=_td_headers(),params={"symbol":symbol},timeout=20)
    if not r.ok: raise RuntimeError(f"Twelve Data price {r.status_code}: {r.text[:250]}")
    j=r.json()
    if j.get("status")=="error": raise RuntimeError(j.get("message","Twelve Data price error"))
    return float(j["price"])

def td_market_history(symbol, market, interval="1day", years=2):
    start=date.today()-timedelta(days=365*years)
    return td_history(symbol,interval,start,date.today(),5000)

def td_validate_symbol(symbol,market):
    try:
        d=td_history(symbol,"1day",date.today()-timedelta(days=30),date.today(),100)
        return (not d.empty),len(d),"OK" if not d.empty else "No data"
    except Exception as e:
        return False,0,str(e)

# ========================= INDICATORS =========================

def ema(s,n): return s.ewm(span=n,adjust=False,min_periods=n).mean()
def sma(s,n): return s.rolling(n,min_periods=n).mean()

def rsi(s,n=14):
    d=s.diff()
    up=d.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=up/dn.replace(0,np.nan)
    return 100-100/(1+rs)

def _monthly_asof(d):
    m=d.resample("ME").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
    # Build a current in-progress month from daily data; this is known as of each scan date.
    cur_key=d.index[-1].to_period("M")
    cur=d[d.index.to_period("M")==cur_key]
    if not cur.empty:
        m.loc[cur.index[-1].to_period("M").end_time.normalize(),["open","high","low","close","volume"]]=[
            cur.open.iloc[0],cur.high.max(),cur.low.min(),cur.close.iloc[-1],cur.volume.sum()
        ]
    return m

def _weekly_asof(d):
    return d.resample("W-FRI").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})

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

    w=_weekly_asof(x)
    w["rsi14"]=rsi(w.close,14)
    w["ema20"]=ema(w.close,20)
    w["ema50"]=ema(w.close,50)
    # As-of mapping: use the weekly bar containing today's date, not a future week.
    wkvals=[]
    for dt in x.index:
        wk=w[w.index <= dt]
        wkvals.append(wk.iloc[-1] if not wk.empty else pd.Series(dtype=float))
    x["wrsi14"]=[v.get("rsi14",np.nan) for v in wkvals]
    x["wema20"]=[v.get("ema20",np.nan) for v in wkvals]
    x["wema50"]=[v.get("ema50",np.nan) for v in wkvals]
    x["wclose"]=[v.get("close",np.nan) for v in wkvals]

    m=_monthly_asof(x)
    m["rsi14"]=rsi(m.close,14)
    m["ema10"]=ema(m.close,10)
    m["ema15"]=ema(m.close,15)
    m["ema20"]=ema(m.close,20)
    m["mom"]=m.close.pct_change()*100
    m["prev_close"]=m.close.shift(1)
    m["prev_high"]=m.high.shift(1)
    m["prev_low"]=m.low.shift(1)

    # Monthly max momentum over 20 months, as of the current month.
    m["mom20max"]=m.mom.rolling(20,min_periods=1).max()

    # Monthly EMA10/20 bullish cross on each month.
    cross=(m.ema10>m.ema20)&(m.ema10.shift(1)<=m.ema20.shift(1))
    m["cross_10_20"]=cross.astype(int)
    m["cross_count20"]=m.cross_10_20.rolling(20,min_periods=1).sum()

    # Daily rows mapped to current as-of month.
    vals=[]
    for dt in x.index:
        mm=m[m.index.to_period("M") <= dt.to_period("M")]
        vals.append(mm.iloc[-1] if not mm.empty else pd.Series(dtype=float))
    x["mclose"]=[v.get("close",np.nan) for v in vals]
    x["mopen"]=[v.get("open",np.nan) for v in vals]
    x["mhigh"]=[v.get("high",np.nan) for v in vals]
    x["mlow"]=[v.get("low",np.nan) for v in vals]
    x["mrsi14"]=[v.get("rsi14",np.nan) for v in vals]
    x["mema10"]=[v.get("ema10",np.nan) for v in vals]
    x["mema15"]=[v.get("ema15",np.nan) for v in vals]
    x["mema20"]=[v.get("ema20",np.nan) for v in vals]
    x["mmom"]=[v.get("mom",np.nan) for v in vals]
    x["mmax20"]= [v.get("mom20max",np.nan) for v in vals]
    x["mprevclose"]=[v.get("prev_close",np.nan) for v in vals]
    x["mprevhigh"]=[v.get("prev_high",np.nan) for v in vals]
    x["mprevlow"]=[v.get("prev_low",np.nan) for v in vals]
    x["m_cross_count20"]=[v.get("cross_count20",np.nan) for v in vals]
    x["m_cross_10_20"]=[v.get("cross_10_20",np.nan) for v in vals]
    return x

# ========================= STRATEGIES =========================

def _pct_change(s):
    return s.pct_change()*100

def _cross_up(a,b):
    return (a>b)&(a.shift(1)<=b.shift(1))

def _rolling_count(condition, window, offset=1):
    # Screener-style "count(window, offset where condition)": evaluate the
    # previous `window` observations, excluding the current bar.
    return condition.shift(offset).rolling(window, min_periods=1).sum()

def strategy_signal(x,s):
    if x.empty:
        return pd.Series(False,index=x.index)

    daily_ret=_pct_change(x.close)

    if s==1:
        monthly_open_in_prev = (x.mopen <= x.mprevhigh) & (x.mopen >= x.mprevlow)
        monthly_close_in_prev = (x.mclose >= x.mprevlow) & (x.mclose <= x.mprevhigh)
        near_ema10 = ((x.mclose-x.mema10)/x.mema10 <= .30)
        return (
            (x.wrsi14 >= 50) &
            (x.mrsi14 >= 50) &
            (x.mclose >= x.mema15) &
            (x.close >= 15) &
            (x.vol20 >= 15000) &
            monthly_open_in_prev &
            monthly_close_in_prev &
            near_ema10 &
            (x.mmax20 >= 20)
        )

    if s==2:
        # ================================================================
        # STRATEGY 2 — direct translation of the user's scanner formula
        # ================================================================
        #
        # "count(20, 1 where ...)" is implemented as:
        # previous 20 completed daily bars, excluding today's bar.
        #
        # Cross definitions:
        #   EMA20 < EMA50 today AND EMA20 >= EMA50 yesterday
        #   EMA10 < EMA20 today AND EMA10 >= EMA20 yesterday
        #   EMA20 > EMA50 today AND EMA20 <= EMA50 yesterday
        #   EMA50 > EMA200 today AND EMA50 <= EMA200 yesterday

        ema20_below_50_cross = (
            (x.ema20 < x.ema50) &
            (x.ema20.shift(1) >= x.ema50.shift(1))
        )
        ema10_below_20_cross = (
            (x.ema10 < x.ema20) &
            (x.ema10.shift(1) >= x.ema20.shift(1))
        )

        ema20_above_50_cross = (
            (x.ema20 > x.ema50) &
            (x.ema20.shift(1) <= x.ema50.shift(1))
        )
        ema50_above_200_cross = (
            (x.ema50 > x.ema200) &
            (x.ema50.shift(1) <= x.ema200.shift(1))
        )

        # count(20,1 where condition): 20 bars immediately before today.
        bearish_20_50_count = (
            ema20_below_50_cross.shift(1)
            .rolling(20, min_periods=20)
            .sum()
        )
        bearish_10_20_count = (
            ema10_below_20_cross.shift(1)
            .rolling(10, min_periods=10)
            .sum()
        )

        bullish_20_50_count = (
            ema20_above_50_cross.shift(1)
            .rolling(20, min_periods=20)
            .sum()
        )
        bullish_50_200_count = (
            ema50_above_200_cross.shift(1)
            .rolling(20, min_periods=20)
            .sum()
        )

        # Current candle lies within the previous day's high-low range.
        inside_previous_day = (
            (x.open <= x.high.shift(1)) &
            (x.open >= x.low.shift(1)) &
            (x.close >= x.low.shift(1)) &
            (x.close <= x.high.shift(1))
        )

        # Returns of exactly 1 day ago and 2 days ago.
        ret_1d_ago = daily_ret.shift(1)
        ret_2d_ago = daily_ret.shift(2)

        return (
            # daily max(30, % change) >= 5
            (daily_ret.rolling(30, min_periods=30).max() >= 5) &

            # daily count(20,1 where EMA20 < EMA50 cross) < 1
            (bearish_20_50_count < 1) &

            # daily count(10,1 where EMA10 < EMA20 cross) < 1
            (bearish_10_20_count < 1) &

            # EMA50 >= EMA250
            (x.ema50 >= x.ema250) &

            # 20-day average volume >= 10000
            (x.vol20 >= 10000) &

            # Daily close >= 15
            (x.close >= 15) &

            # Monthly RSI(14) >= 55
            (x.mrsi14 >= 55) &

            # Weekly RSI(14) >= 50
            (x.wrsi14 >= 50) &

            # Current candle inside previous day's range
            inside_previous_day &

            # 1 day ago return <= 5 and >= -4
            (ret_1d_ago <= 5) &
            (ret_1d_ago >= -4) &

            # 2 days ago return <= 5 and >= -4
            (ret_2d_ago <= 5) &
            (ret_2d_ago >= -4) &

            # (daily close - daily EMA10) / daily EMA10 <= 0.04
            # NOTE: this is NOT abs(); a close below EMA10 satisfies it.
            (((x.close - x.ema10) / x.ema10) <= 0.04) &

            # Exactly one recent bullish crossover of either pair.
            (
                (bullish_20_50_count == 1) |
                (bullish_50_200_count == 1)
            )
        )

    if s==3:
        vwap=(x.close*x.volume).rolling(20).sum()/x.volume.rolling(20).sum()
        # The original screener expression used EMA(daily VWAP,20) * SMA(volume,20).
        vwap_ema=ema(vwap,20)
        liquidity=vwap_ema*x.vol20 >= 150_000_000
        near50=(x.close <= x.ema50*1.04)&(x.close >= x.ema50*.96)
        return (
            liquidity &
            (x.close >= x.ema200) &
            (x.wrsi14 >= 40) &
            near50
        )

    if s==4:
        # ================================================================
        # STRATEGY 4 — direct translation of the user's original formula
        # ================================================================
        #
        # monthly return >= 20%
        # monthly RSI(14) >= 50
        # monthly EMA10 >= monthly EMA20
        # daily EMA(volume,30) >= 50000
        # daily close >= 20
        #
        # AND:
        #   monthly count(20,1 where monthly EMA10 > EMA20 and
        #                  1 month ago EMA10 <= EMA20) >= 1
        #   OR
        #   current monthly close > monthly EMA10 AND
        #       1 month ago close <= 1 month ago EMA10
        #
        # AND daily close <= 1.03 * daily EMA20
        #
        # Monthly count uses completed monthly observations immediately
        # preceding the current month, exactly like the scanner's offset=1.

        monthly_bull_cross = (
            (x.mema10 > x.mema20) &
            (x.mema10.shift(1) <= x.mema20.shift(1))
        )

        monthly_bull_cross_count = (
            monthly_bull_cross.shift(1)
            .rolling(20, min_periods=20)
            .sum()
        )

        monthly_reclaim = (
            (x.mclose > x.mema10) &
            (x.mprevclose <= x.mema10)
        )

        return (
            # monthly "close - 1 candle ago close / 1 candle ago close * 100" >= 20
            (x.mmom >= 20) &

            # monthly RSI(14) >= 50
            (x.mrsi14 >= 50) &

            # monthly EMA10 >= monthly EMA20
            (x.mema10 >= x.mema20) &

            # daily EMA(daily volume,30) >= 50000
            (x.vol30 >= 50000) &

            # daily close >= 20
            (x.close >= 20) &

            # monthly count >= 1 OR monthly reclaim
            (
                (monthly_bull_cross_count >= 1) |
                monthly_reclaim
            ) &

            # daily close <= 1.03 * daily EMA20
            (x.close <= 1.03 * x.ema20)
        )

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


# ========================= HTF DEMAND + FOOTPRINT =========================

def _zone_score(x, lookback, tolerance=0.035):
    """Approximate demand/support quality from historical swing lows.
    This is a research heuristic, not a claim of institutional order-flow data."""
    if len(x) < lookback + 10:
        return 0, {"fresh": False, "reaction": 0, "tests": 0}
    recent = x.tail(lookback).copy()
    low = float(recent.low.min())
    price = float(x.close.iloc[-1])
    distance = abs(price / low - 1)
    near = distance <= tolerance
    # Strong departure from the lowest area.
    reaction = (float(recent.close.max()) / low - 1) if low > 0 else 0
    tests = int(((recent.low <= low * (1 + tolerance)).sum()))
    fresh = tests <= 2
    points = 0
    if near: points += 5
    if reaction >= .20: points += 4
    elif reaction >= .10: points += 2
    if fresh: points += 2
    elif tests <= 4: points += 1
    return min(points, 11), {"fresh": fresh, "reaction": reaction, "tests": tests, "distance": distance}

def htf_confluence(x):
    """20-point higher-timeframe support/demand score."""
    # Quarterly approximation from rolling 63 trading days.
    q = _zone_score(x, 252, .06)[0]
    m = _zone_score(x, 126, .045)[0]
    w = _zone_score(x, 60, .035)[0]
    # Cap the combined score at 20.
    total = min(20, q * 0.75 + m * 0.75 + w * 0.5)
    return int(round(total))

def footprint_score(x):
    """20-point price/volume footprint heuristic using only information known at the scan date."""
    if len(x) < 60:
        return 0
    z = x.iloc[-1]
    score = 0

    # Base/compression: lower recent range than earlier range.
    recent_range = ((x.high - x.low) / x.close).tail(10).mean()
    prior_range = ((x.high - x.low) / x.close).tail(40).head(30).mean()
    if pd.notna(recent_range) and pd.notna(prior_range) and recent_range < prior_range * .8:
        score += 4

    # Volume contraction in the base.
    v_recent = x.volume.tail(10).mean()
    v_prior = x.volume.tail(40).head(30).mean()
    if pd.notna(v_recent) and pd.notna(v_prior) and v_recent < v_prior * .9:
        score += 3

    # Expansion on the current move.
    if pd.notna(z.relvol) and z.relvol >= 1.5:
        score += 4
    elif pd.notna(z.relvol) and z.relvol >= 1.2:
        score += 2

    # Close near the high of the day.
    day_range = float(z.high - z.low)
    if day_range > 0:
        close_location = (float(z.close) - float(z.low)) / day_range
        if close_location >= .75:
            score += 3
        elif close_location >= .60:
            score += 1

    # Controlled distance from EMA20, avoiding extreme extension.
    extension = float(z.close / z.ema20 - 1) if pd.notna(z.ema20) else np.nan
    if np.isfinite(extension) and 0 <= extension <= .04:
        score += 3

    # Relative-strength proxy versus own 50-day trend.
    if pd.notna(z.ema50) and z.close > z.ema50:
        score += 3

    return int(min(20, score))

def strategy_quality_score(x, s):
    """30-point strategy-specific quality score. Does not apply other strategies."""
    z = x.iloc[-1]
    p = 0
    if s == 1:
        p += 10 if z.wrsi14 >= 60 else 7 if z.wrsi14 >= 55 else 4 if z.wrsi14 >= 50 else 0
        p += 10 if z.mrsi14 >= 60 else 7 if z.mrsi14 >= 55 else 4 if z.mrsi14 >= 50 else 0
        p += 10 if z.mclose >= z.mema15 else 0
    elif s == 2:
        p += 10 if z.ema20 > z.ema50 else 0
        p += 10 if z.ema50 > z.ema200 else 0
        p += 10 if z.relvol >= 1.2 else 5 if z.relvol >= 1 else 0
    elif s == 3:
        dist = abs(z.close / z.ema50 - 1)
        p += 10 if dist <= .015 else 7 if dist <= .025 else 4 if dist <= .04 else 0
        p += 10 if z.close > z.ema200 else 0
        p += 10 if z.wrsi14 >= 55 else 6 if z.wrsi14 >= 45 else 0
    elif s == 4:
        p += 10 if z.mmom >= 30 else 7 if z.mmom >= 25 else 4 if z.mmom >= 20 else 0
        p += 10 if z.mema10 > z.mema20 else 0
        p += 10 if z.close <= z.ema20 * 1.02 else 5 if z.close <= z.ema20 * 1.03 else 0
    return int(min(30, p))

def final_setup_score(x, s, regime, safety_score):
    """100-point ranking score. Most components rank quality rather than hard-reject."""
    z = x.iloc[-1]
    strategy = strategy_quality_score(x, s)       # 30
    htf = htf_confluence(x)                       # 20
    footprint = footprint_score(x)                # 20

    trend = 0
    trend += 4 if z.close > z.ema50 else 0
    trend += 3 if z.close > z.ema200 else 0
    trend += 3 if z.rsi14 >= 50 else 0             # 10

    entry = 0
    ext = z.close / z.ema20 - 1 if pd.notna(z.ema20) else np.nan
    if np.isfinite(ext):
        entry = 10 if 0 <= ext <= .025 else 7 if ext <= .04 else 3 if ext <= .07 else 0

    rel = 5 if (pd.notna(z.ema50) and z.close > z.ema50) else 0

    market = 5 if regime == "STRONG BULL" else 4 if regime == "BULL" else 2 if regime == "RECOVERY / SIDEWAYS" else 0
    safety_points = 5 if safety_score >= 90 else 4 if safety_score >= 80 else 3 if safety_score >= 70 else 0

    total = strategy + htf + footprint + trend + entry + rel + market + safety_points
    return int(max(0, min(100, total))), {
        "Strategy": strategy,
        "HTF Demand": htf,
        "Footprint": footprint,
        "Trend": trend,
        "Entry Quality": entry,
        "Relative Strength": rel,
        "Market Regime": market,
        "Safety": safety_points
    }

# ========================= SCORE =========================

def setup_score(x, s, regime, safety_score):
    """Strategy-specific quality score. This does NOT add other strategy rules."""
    z = x.iloc[-1]
    score = 0

    # Market regime support: 15
    score += 15 if regime == "STRONG BULL" else 12 if regime == "BULL" else 7 if regime == "RECOVERY / SIDEWAYS" else 2

    # MTF alignment: 25
    score += 5 if z.close > z.ema50 else 0
    score += 5 if z.close > z.ema200 else 0
    score += 5 if z.wrsi14 >= 50 else 0
    score += 5 if z.mrsi14 >= 50 else 0
    score += 5 if z.mema10 >= z.mema20 else 0

    # Technical quality: 25
    score += 5 if z.rsi14 >= 50 else 0
    score += 5 if z.relvol >= 1.0 else 0
    score += 5 if z.relvol >= 1.5 else 0
    score += 5 if z.close >= z.ema20 else 0
    score += 5 if z.close >= z.ema50 else 0

    # Safety: 15
    score += 15 if safety_score >= 90 else 12 if safety_score >= 80 else 8 if safety_score >= 70 else 0

    # Strategy-specific signal quality: 20.
    # These are conditions belonging to the selected strategy only.
    if s == 1:
        score += 10 if z.wrsi14 >= 55 else 5 if z.wrsi14 >= 50 else 0
        score += 10 if z.mrsi14 >= 55 else 5 if z.mrsi14 >= 50 else 0
    elif s == 2:
        score += 10 if z.ema20 > z.ema50 else 0
        score += 10 if z.ema50 > z.ema200 else 0
    elif s == 3:
        dist = abs(z.close / z.ema50 - 1)
        score += 10 if dist <= .02 else 5 if dist <= .04 else 0
        score += 10 if z.close > z.ema200 else 0
    elif s == 4:
        score += 10 if z.mmom >= 25 else 5 if z.mmom >= 20 else 0
        score += 10 if z.mema10 > z.mema20 else 0

    return int(max(0, min(100, score)))

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


# ========================= V21 FAST EXECUTION + LEARNING =========================
# V21 principle:
#   - Build expensive features once per symbol.
#   - Keep historical scans vectorized.
#   - Use WebSocket only for live 1-minute updates.
#   - Persist learning observations so the model improves from completed trades.
#
# The strategy rules themselves are intentionally unchanged.

FEATURE_CACHE_VERSION = "v21"

def _feature_cache_key(symbol, df):
    if df is None or df.empty:
        return None
    last = pd.Timestamp(df.index[-1])
    return f"{FEATURE_CACHE_VERSION}:{str(symbol).upper()}:{last.isoformat()}:{len(df)}"

@st.cache_data(ttl=86400, show_spinner=False)
def features_cached(symbol, df):
    """Expensive feature calculation is cached by symbol + last candle + length."""
    return features(df)

def ensure_learning_tables():
    con = _db()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS learning_observations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                market TEXT,
                symbol TEXT,
                strategy TEXT,
                signal_time TEXT,
                score REAL,
                regime TEXT,
                htf REAL,
                footprint REAL,
                strategy_score REAL,
                entry_quality REAL,
                relative_strength REAL,
                safety_score REAL,
                entry REAL,
                exit_price REAL,
                result_r REAL,
                outcome TEXT,
                holding_minutes REAL,
                source TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS model_weights(
                market TEXT NOT NULL,
                strategy TEXT NOT NULL,
                component TEXT NOT NULL,
                weight REAL NOT NULL,
                samples INTEGER NOT NULL DEFAULT 0,
                avg_r REAL,
                win_rate REAL,
                updated_at TEXT,
                PRIMARY KEY(market,strategy,component)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS scan_state(
                market TEXT PRIMARY KEY,
                last_scan TEXT,
                universe_size INTEGER DEFAULT 0,
                elapsed_seconds REAL DEFAULT 0
            )
        """)
        con.commit()
    finally:
        con.close()

ensure_learning_tables()

def _record_learning_trade(market, row, source="forward"):
    """Persist one completed trade without changing the trading rules."""
    try:
        con = _db()
        con.execute("""
            INSERT INTO learning_observations(
                created_at,market,symbol,strategy,signal_time,score,regime,
                htf,footprint,strategy_score,entry_quality,relative_strength,
                safety_score,entry,exit_price,result_r,outcome,holding_minutes,source
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(timespec="seconds"),
            market,
            str(row.get("symbol", row.get("Ticker", ""))),
            str(row.get("strategy", row.get("Strategy", ""))),
            str(row.get("signal_time", row.get("Entry Date", ""))),
            float(row.get("score", row.get("Score", np.nan))),
            str(row.get("regime", row.get("Regime", ""))),
            float(row.get("htf", row.get("HTF", row.get("HTF Demand", np.nan)))),
            float(row.get("footprint", row.get("Footprint", np.nan))),
            float(row.get("strategy_score", row.get("Strategy Score", np.nan))),
            float(row.get("entry_quality", row.get("Entry Quality", np.nan))),
            float(row.get("relative_strength", row.get("Relative Strength", np.nan))),
            float(row.get("safety_score", row.get("Safety", row.get("Safety Score", np.nan)))),
            float(row.get("entry", row.get("Entry", np.nan))),
            float(row.get("exit_price", row.get("Exit", np.nan))),
            float(row.get("result_r", row.get("R", np.nan))),
            str(row.get("outcome", row.get("Outcome", ""))),
            float(row.get("holding_minutes", np.nan)),
            source
        ))
        con.commit()
    except Exception:
        # Learning must never break scanning/forward monitoring.
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass

def learning_snapshot(market="INDIA"):
    ensure_learning_tables()
    con = _db()
    try:
        q = pd.read_sql_query("""
            SELECT * FROM learning_observations
            WHERE market=?
            ORDER BY id DESC
        """, con, params=(market,))
    finally:
        con.close()
    return q

def adaptive_component_weights(market="INDIA", strategy=None):
    """
    Data-driven weights from completed observations.
    This does not alter raw strategy qualification.
    Components with insufficient evidence retain neutral weights.
    """
    q = learning_snapshot(market)
    if q.empty:
        return pd.DataFrame(columns=["Strategy","Component","Weight","Samples","Avg R","Win %"])

    if strategy is not None:
        q = q[q.strategy == f"S{strategy}"]
    if q.empty:
        return pd.DataFrame(columns=["Strategy","Component","Weight","Samples","Avg R","Win %"])

    components = [
        ("score", "Score"), ("htf", "HTF"), ("footprint", "Footprint"),
        ("strategy_score", "Strategy Score"), ("entry_quality", "Entry Quality"),
        ("relative_strength", "Relative Strength"), ("safety_score", "Safety")
    ]
    rows = []
    for s, sg in q.groupby("strategy"):
        base = sg.result_r.mean()
        for col, label in components:
            if col not in sg:
                continue
            med = sg[col].median()
            hi = sg[sg[col] >= med]
            lo = sg[sg[col] < med]
            if len(hi) < 5 or len(lo) < 5:
                weight = 1.0
            else:
                edge = float(hi.result_r.mean() - lo.result_r.mean())
                weight = float(np.clip(1.0 + edge * 0.25, 0.70, 1.35))
            rows.append({
                "Strategy": s, "Component": label, "Weight": round(weight, 3),
                "Samples": len(sg), "Avg R": round(float(base), 3),
                "Win %": round(float((sg.result_r > 0).mean() * 100), 1)
            })
    return pd.DataFrame(rows)

def adaptive_candidate_score(base_score, market="INDIA", strategy="S1", parts=None):
    """
    Learning overlay only. Raw strategy rules remain authoritative.
    With <20 observations, return the original score.
    """
    q = learning_snapshot(market)
    if q.empty or len(q) < 20 or parts is None:
        return float(base_score)

    q = q[q.strategy == strategy]
    if len(q) < 20:
        return float(base_score)

    weights = adaptive_component_weights(market, int(strategy[-1]))
    if weights.empty:
        return float(base_score)

    vals = {
        "Score": float(base_score),
        "HTF": float(parts.get("HTF Demand", 0)),
        "Footprint": float(parts.get("Footprint", 0)),
        "Strategy Score": float(parts.get("Strategy", 0)),
        "Entry Quality": float(parts.get("Entry Quality", 0)),
        "Relative Strength": float(parts.get("Relative Strength", 0)),
        "Safety": float(parts.get("Safety", 0)),
    }
    total = 0.0
    wsum = 0.0
    for _, r in weights.iterrows():
        comp = r["Component"]
        if comp in vals:
            w = float(r["Weight"])
            total += vals[comp] * w
            wsum += w
    if not wsum:
        return float(base_score)
    # Blend gently so the learned overlay cannot overpower the deterministic score.
    learned = total / wsum
    return float(np.clip(base_score * 0.70 + learned * 0.30, 0, 100))

def _fast_historical_candidates(data, strategies):
    """Vectorized candidate discovery: features once, then boolean signals."""
    rows = []
    for ticker, df in data.items():
        if df is None or len(df) < 260:
            continue
        try:
            f = features_cached(str(ticker), df.sort_index())
            f = f.replace([np.inf, -np.inf], np.nan)
            for s in strategies:
                sig = strategy_signal(f, s)
                idx = np.flatnonzero(sig.fillna(False).to_numpy())
                for i in idx:
                    rows.append((ticker, s, i))
        except Exception:
            continue
    return rows

def run_fast_backtest(data, strategies, capital=1000000, risk=0.01, sl=0.07, rr=3.0):
    """
    Faster research backtest:
      * features are calculated once per symbol;
      * signal dates are discovered vectorially;
      * only actual candidate dates enter the trade loop.
    """
    rows = []
    for ticker, df in data.items():
        if df is None or len(df) < 300:
            continue
        try:
            df = df.sort_index()
            x = features_cached(str(ticker), df).replace([np.inf, -np.inf], np.nan)
            for s in strategies:
                sig = strategy_signal(x, s).fillna(False).to_numpy()
                signal_idx = np.flatnonzero(sig)
                for i in signal_idx:
                    if i >= len(x) - 2:
                        continue
                    ei = i + 1
                    entry = float(x.close.iloc[ei])
                    stop = entry * (1 - sl)
                    one_r = entry - stop
                    qty = max(1, int(capital * risk / one_r))
                    target = entry + rr * one_r
                    ex = None
                    ep = None
                    reason = "End"
                    for j in range(ei, len(x)):
                        lo = float(x.low.iloc[j]); hi = float(x.high.iloc[j])
                        if lo <= stop:
                            ex, ep, reason = j, stop, "SL"
                            break
                        if hi >= target:
                            ex, ep, reason = j, target, f"{rr}R"
                            break
                    if ex is None:
                        ex = len(x) - 1
                        ep = float(x.close.iloc[-1])
                    pnl = (ep - entry) * qty
                    rows.append({
                        "Entry Date": x.index[ei].date(),
                        "Exit Date": x.index[ex].date(),
                        "Ticker": str(ticker).replace(".NS",""),
                        "Strategy": f"S{s}",
                        "Entry": entry,
                        "Exit": ep,
                        "Return %": (ep / entry - 1) * 100,
                        "R": pnl / (one_r * qty),
                        "PnL ₹": pnl,
                        "Holding Days": (x.index[ex] - x.index[ei]).days,
                        "Reason": reason
                    })
        except Exception:
            continue
    return pd.DataFrame(rows)

def save_scan_state(market, universe_size, elapsed):
    con = _db()
    try:
        con.execute("""
            INSERT OR REPLACE INTO scan_state(market,last_scan,universe_size,elapsed_seconds)
            VALUES(?,?,?,?)
        """, (market, datetime.now().isoformat(timespec="seconds"),
              int(universe_size), float(elapsed)))
        con.commit()
    finally:
        con.close()


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
st.caption("V21 • Fast cached scanner • 1-minute live layer • 4 deterministic strategies • adaptive historical + forward learning • crypto research engine")

tabs=st.tabs([
    "🏠 Dashboard","📡 Daily Scanner","📊 Backtest","🔬 Forward Testing",
    "🧠 Market Learning","💎 Long-Term Fundamentals","🏢 Small/Micro Safety",
    "⚡ Live Monitor","💾 Dhan Data Manager","🧪 Custom Strategy"
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
    st.subheader("📡 Daily Live Scanner")
    st.caption("First audit the raw strategy signals. Then turn on the score gate. Each strategy is scanned independently.")

    a,b,c = st.columns(3)
    universes = a.multiselect(
        "Trading universes",
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        key="scan_universes"
    )
    scan_mode = b.selectbox(
        "Scan mode",
        ["All qualifying setups + scores", "Exact raw signals (audit)"],
        key="scan_mode_v4"
    )
    min_score = c.number_input(
        "Minimum score",
        value=85,
        min_value=0,
        max_value=100,
        key="scan_score_v4"
    )

    d,e = st.columns(2)
    selected_strategies = d.multiselect(
        "Strategies to scan independently",
        [1,2,3,4],
        [1,2,3,4],
        key="scan_strategies_v4"
    )
    result_mode = e.selectbox(
        "Results",
        ["ALL qualifying setups","Top 10","Top 25","Top 50"],
        key="scan_result_mode_v4"
    )

    st.info(
        "Every selected stock is tested independently against every selected strategy. "
        "A stock appears under a strategy only when ALL rules of that strategy pass. "
        "Scores rank qualifying setups; the ≥85 gate is used only for forward testing."
    )

    best_top_placeholder = st.empty()

    if st.button("🔄 Scan Market Now", type="primary", key="scan_button_v4"):
        try:
            if not dhan_configured():
                st.error("Dhan is not configured. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to Streamlit Secrets.")
                st.stop()
            if not selected_strategies:
                st.warning("Select at least one strategy.")
                st.stop()
            if not universes:
                st.warning("Select at least one universe.")
                st.stop()

            idx_tickers = index_universe("Nifty 500")
            idx_data = download_prices(
                tuple(idx_tickers),
                date.today()-timedelta(days=1000),
                date.today()
            )

            if not idx_data:
                st.error("No Nifty 500 price data returned by Yahoo Finance. This is a data-source problem.")
                st.stop()

            proxy = max(idx_data.values(), key=len)
            regime, regime_score = regime_from_index(proxy)

            universe = set()
            for u in universes:
                universe.update(index_universe(u))
            tickers = sorted(universe)

            data = download_prices(
                tuple(tickers),
                date.today()-timedelta(days=1000),
                date.today()
            )

            if not data:
                st.error(
                    "Yahoo Finance returned no price data for the selected universe. "
                    "The scanner cannot generate signals until price data is available."
                )
                st.stop()

            rows = []
            bar = st.progress(0)
            stats = {
                "downloaded": len(data),
                "usable": 0,
                "too_short": 0,
                "signals": {1:0,2:0,3:0,4:0},
                "qualified": {1:0,2:0,3:0,4:0},
                "safety_reject": 0
            }

            for n,(ticker,df) in enumerate(data.items()):
                if len(df) < 260:
                    stats["too_short"] += 1
                    bar.progress((n+1)/max(1,len(data)))
                    continue

                f = features(df)
                # Keep the latest row even when some long-term indicators are unavailable.
                # Individual strategy conditions will evaluate NaNs as False.
                f = f.replace([np.inf, -np.inf], np.nan)
                if len(f) < 260:
                    bar.progress((n+1)/max(1,len(data)))
                    continue

                stats["usable"] += 1
                info,_ = company_info(ticker)
                safe,safe_status,flags = safety(info,df)

                for s in selected_strategies:
                    sig = strategy_signal(f,s)
                    signal = bool(sig.iloc[-1])

                    if signal:
                        stats["signals"][s] += 1

                    if not signal:
                        continue

                    score, parts = final_setup_score(f,s,regime,safe)

                    # RAW mode is deliberately not blocked by score or safety.
                    # IMPORTANT: a setup is created only when ALL rules of this
                    # individual strategy pass. Score/safety never suppress a
                    # strategy-qualified setup; they are used for ranking and
                    # the >=85 forward-test gate only.
                    stats["qualified"][s] += 1

                    z = f.iloc[-1]
                    entry = float(z.close)
                    stop = entry * .93
                    target = entry + 3*(entry-stop)

                    rows.append({
                        "Score": score,
                        "Ticker": ticker.replace(".NS",""),
                        "Strategy": f"S{s}",
                        "Signal": "ALL RULES PASS",
                        "Regime": regime,
                        "Safety": safe_status,
                        "Entry": round(entry,2),
                        "SL 7%": round(stop,2),
                        "Target 3R": round(target,2),
                        "R:R": "1:3",
                        "RSI": round(float(z.rsi14),1),
                        "RelVol": round(float(z.relvol),2),
                        "HTF Score": parts["HTF Demand"],
                        "Footprint Score": parts["Footprint"],
                        "Strategy Score": parts["Strategy"],
                        "Entry Quality": parts["Entry Quality"],
                        "Relative Strength": parts["Relative Strength"],
                        "Safety Score": safe,
                        "Safety Flags": ", ".join(flags)
                    })

                bar.progress((n+1)/max(1,len(data)))

            result = pd.DataFrame(rows)

            with best_top_placeholder.container():
                st.subheader("🏆 BEST SETUPS — Score Highest First")
                if result.empty:
                    st.warning("No complete-rule setups found in this scan.")
                else:
                    _top=result.sort_values(["Score","Strategy","Ticker"],ascending=[False,True,True])
                    _best=_top[_top["Score"]>=min_score]
                    if _best.empty:
                        st.info(f"No complete-rule setup currently meets the ≥{min_score} forward-test gate.")
                    else:
                        st.dataframe(_best,use_container_width=True,hide_index=True)
                    st.caption("Every displayed setup has already passed ALL rules of its own strategy. Score only ranks valid setups.")


            with st.expander("🔧 Advanced Diagnostics — S2/S4 audits", expanded=False):
                # Strategy 4 condition audit — shown only when S4 is selected.
                if 4 in selected_strategies and stats["usable"] > 0:
                    s4_audit_rows = []
                    for ticker, df in data.items():
                        if len(df) < 260:
                            continue
                        f = features(df)
                        if f.empty:
                            continue
                        z = f.iloc[-1]
                        monthly_cross = (
                            (f.mema10 > f.mema20) &
                            (f.mema10.shift(1) <= f.mema20.shift(1))
                        )
                        monthly_cross_count = (
                            monthly_cross.shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        reclaim = bool(
                            pd.notna(z.mprevclose) and pd.notna(z.mema10) and
                            z.mclose > z.mema10 and z.mprevclose <= z.mema10
                        )
                        conditions = {
                            "Monthly return >=20%": bool(pd.notna(z.mmom) and z.mmom >= 20),
                            "Monthly RSI >=50": bool(pd.notna(z.mrsi14) and z.mrsi14 >= 50),
                            "Monthly EMA10 >= EMA20": bool(pd.notna(z.mema10) and pd.notna(z.mema20) and z.mema10 >= z.mema20),
                            "Daily EMA volume30 >=50000": bool(pd.notna(z.vol30) and z.vol30 >= 50000),
                            "Daily close >=20": bool(z.close >= 20),
                            "Monthly cross count >=1 OR reclaim": bool((pd.notna(monthly_cross_count) and monthly_cross_count >= 1) or reclaim),
                            "Daily close <=1.03 EMA20": bool(pd.notna(z.ema20) and z.close <= 1.03*z.ema20)
                        }
                        s4_audit_rows.append({
                            "Ticker": ticker.replace(".NS",""),
                            **conditions,
                            "S4 EXACT": all(conditions.values())
                        })

                    if s4_audit_rows:
                        s4df = pd.DataFrame(s4_audit_rows)
                        st.subheader("🧪 Strategy 4 Condition Audit")
                        s4counts = pd.DataFrame({
                            "Condition": list(s4df.columns[1:-1]),
                            "Passing stocks": [int(s4df[c].sum()) for c in s4df.columns[1:-1]]
                        })
                        st.dataframe(s4counts, use_container_width=True, hide_index=True)
                        with st.expander("View S4 stock-by-stock audit"):
                            st.dataframe(s4df, use_container_width=True, hide_index=True)

                # Strategy 2 condition audit — shown only when S2 is selected.
                if 2 in selected_strategies and stats["usable"] > 0:
                    audit_rows = []
                    for ticker, df in data.items():
                        if len(df) < 260:
                            continue
                        f = features(df)
                        if f.empty:
                            continue
                        z = f.iloc[-1]
                        dr = f.close.pct_change() * 100

                        c_30max = bool(dr.rolling(30, min_periods=30).max().iloc[-1] >= 5) if len(f) >= 30 else False
                        c_ema50_250 = bool(z.ema50 >= z.ema250)
                        c_vol = bool(z.vol20 >= 10000)
                        c_price = bool(z.close >= 15)
                        c_mrsi = bool(z.mrsi14 >= 55)
                        c_wrsi = bool(z.wrsi14 >= 50)

                        c_inside = bool(
                            (z.open <= f.high.shift(1).iloc[-1]) and
                            (z.open >= f.low.shift(1).iloc[-1]) and
                            (z.close >= f.low.shift(1).iloc[-1]) and
                            (z.close <= f.high.shift(1).iloc[-1])
                        )

                        r1 = dr.shift(1).iloc[-1]
                        r2 = dr.shift(2).iloc[-1]
                        c_r1 = bool(pd.notna(r1) and -4 <= r1 <= 5)
                        c_r2 = bool(pd.notna(r2) and -4 <= r2 <= 5)

                        c_ema10 = bool(pd.notna(z.ema10) and ((z.close-z.ema10)/z.ema10 <= .04))

                        cross20 = (
                            ((f.ema20 > f.ema50) & (f.ema20.shift(1) <= f.ema50.shift(1)))
                            .shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        cross50 = (
                            ((f.ema50 > f.ema200) & (f.ema50.shift(1) <= f.ema200.shift(1)))
                            .shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        c_bull = bool((cross20 == 1) or (cross50 == 1))

                        bear20 = (
                            ((f.ema20 < f.ema50) & (f.ema20.shift(1) >= f.ema50.shift(1)))
                            .shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        bear10 = (
                            ((f.ema10 < f.ema20) & (f.ema10.shift(1) >= f.ema20.shift(1)))
                            .shift(1).rolling(10, min_periods=10).sum().iloc[-1]
                        )
                        c_bear20 = bool(bear20 < 1)
                        c_bear10 = bool(bear10 < 1)

                        audit_rows.append({
                            "Ticker": ticker.replace(".NS",""),
                            "30D Max ≥5": c_30max,
                            "Bearish EMA20/50 count <1": c_bear20,
                            "Bearish EMA10/20 count <1": c_bear10,
                            "EMA50 ≥ EMA250": c_ema50_250,
                            "Vol20 ≥10000": c_vol,
                            "Price ≥15": c_price,
                            "Monthly RSI ≥55": c_mrsi,
                            "Weekly RSI ≥50": c_wrsi,
                            "Inside previous day": c_inside,
                            "Prev day return -4..5": c_r1,
                            "2D ago return -4..5": c_r2,
                            "Close ≤4% above EMA10": c_ema10,
                            "Bullish cross count =1": c_bull,
                            "S2 EXACT": all([c_30max,c_bear20,c_bear10,c_ema50_250,c_vol,c_price,c_mrsi,c_wrsi,c_inside,c_r1,c_r2,c_ema10,c_bull])
                        })

                    if audit_rows:
                        audit_df = pd.DataFrame(audit_rows)
                        st.subheader("🧪 Strategy 2 Condition Audit")
                        counts = pd.DataFrame({
                            "Condition": list(audit_df.columns[1:]),
                            "Passing stocks": [int(audit_df[c].sum()) for c in audit_df.columns[1:]]
                        })
                        st.dataframe(counts, use_container_width=True, hide_index=True)
                        with st.expander("View S2 stock-by-stock audit"):
                            st.dataframe(audit_df, use_container_width=True, hide_index=True)


            st.subheader("🔎 Scanner Diagnostics")
            c1,c2,c3,c4,c5,c6 = st.columns(6)
            c1.metric("Universe stocks", len(tickers))
            c2.metric("Price datasets", stats["downloaded"])
            c3.metric("Usable datasets", stats["usable"])
            c4.metric("S1/S2 signals", stats["signals"][1]+stats["signals"][2])
            c5.metric("S3/S4 signals", stats["signals"][3]+stats["signals"][4])
            c6.metric("Safety rejects", stats["safety_reject"])
            st.caption(
                "Warm-up history: 1000 calendar days. This is required for EMA250 and monthly EMA20; "
                "the previous 450-day window could leave the feature table with zero valid rows."
            )

            diag = pd.DataFrame({
                "Strategy":["S1","S2","S3","S4"],
                "Raw signals":[stats["signals"][1],stats["signals"][2],stats["signals"][3],stats["signals"][4]],
                "Displayed/qualified":[stats["qualified"][1],stats["qualified"][2],stats["qualified"][3],stats["qualified"][4]]
            })
            st.dataframe(diag,use_container_width=True,hide_index=True)

            if result.empty:
                st.error(
                    "ZERO RESULTS. If RAW mode also shows zero signals, the problem is in the "
                    "strategy/data layer—not the scoring filters."
                )
                st.stop()

            result = result.sort_values(
                ["Score","Strategy","Ticker"],
                ascending=[False,True,True]
            )
            full_result = result.copy()

            st.subheader("📊 Strategy Coverage")
            cov=[]
            for s in selected_strategies:
                sr=full_result[full_result["Strategy"]==f"S{s}"] if not full_result.empty else pd.DataFrame()
                cov.append({
                    "Strategy":f"S{s}",
                    "ALL rules pass":len(sr),
                    f"≥{min_score}":int((sr["Score"]>=min_score).sum()) if not sr.empty else 0,
                    "Best":int(sr["Score"].max()) if not sr.empty else 0,
                    "Average":round(float(sr["Score"].mean()),1) if not sr.empty else 0
                })
            st.dataframe(pd.DataFrame(cov),use_container_width=True,hide_index=True)

            if full_result.empty:
                st.warning("No stock passed ALL rules of the selected strategies.")
            else:
                # Four-column board: one independent column per strategy.
                st.subheader("🏆 Strategy Board — Best to Average")
                cols=st.columns(4)
                for idx,s in enumerate([1,2,3,4]):
                    with cols[idx]:
                        sr=full_result[full_result["Strategy"]==f"S{s}"].copy()
                        sr=sr.sort_values("Score",ascending=False)
                        st.markdown(f"### S{s}")
                        if sr.empty:
                            st.caption("No complete-rule setups")
                        else:
                            for rank,(_,r) in enumerate(sr.iterrows(),1):
                                score=float(r["Score"])
                                if score>=85:
                                    st.success(f"**{rank}. {r['Ticker']} — {score:.0f}**")
                                elif score>=75:
                                    st.warning(f"**{rank}. {r['Ticker']} — {score:.0f}**")
                                else:
                                    st.info(f"**{rank}. {r['Ticker']} — {score:.0f}**")
                                st.caption(
                                    f"HTF {r.get('HTF Demand','-')} | "
                                    f"Footprint {r.get('Footprint','-')} | "
                                    f"Safety {r.get('Safety','-')} | {r.get('Regime','-')}"
                                )

                # Same stock in 2+ strategies = confluence, but only from
                # complete independent strategy passes.
                st.subheader("⭐ Multi-Strategy Confluence")
                pivot=full_result.pivot_table(
                    index="Ticker",columns="Strategy",values="Score",aggfunc="max"
                )
                for sname in ["S1","S2","S3","S4"]:
                    if sname not in pivot.columns:
                        pivot[sname]=np.nan
                pivot=pivot[["S1","S2","S3","S4"]]
                pivot["Strategies Passed"]=pivot.notna().sum(axis=1)
                pivot["Best Score"]=pivot[["S1","S2","S3","S4"]].max(axis=1)
                conf=pivot[pivot["Strategies Passed"]>=2].sort_values(
                    ["Strategies Passed","Best Score"],ascending=[False,False]
                ).reset_index()
                if conf.empty:
                    st.info("No stock currently passes the complete rules of 2 or more strategies.")
                else:
                    st.dataframe(conf,use_container_width=True,hide_index=True)

                st.subheader("📋 All Qualifying Setups")
                st.dataframe(full_result,use_container_width=True,hide_index=True)

                forward=full_result[
                    (full_result["Score"]>=min_score) &
                    (full_result["Safety"]!="REJECT")
                ].copy()
                st.subheader(f"🚀 Forward-Test Queue — Score ≥ {min_score}")
                if forward.empty:
                    st.info("No complete-rule setup currently meets the forward-test gate.")
                else:
                    st.dataframe(forward,use_container_width=True,hide_index=True)
                    st.session_state["forward_queue"]=forward
                    added=add_forward_candidates(forward)
                    st.success(
                        f"{len(forward)} setups qualify for forward testing; "
                        f"{added} added to active monitoring."
                    )

                st.subheader("🔎 Individual Strategy Results")
                stabs=st.tabs(["S1","S2","S3","S4"])
                for tab,s in zip(stabs,[1,2,3,4]):
                    with tab:
                        sr=full_result[full_result["Strategy"]==f"S{s}"]
                        if sr.empty:
                            st.warning(f"S{s}: no stock passed ALL S{s} rules.")
                        else:
                            st.dataframe(
                                sr.sort_values("Score",ascending=False),
                                use_container_width=True,
                                hide_index=True
                            )

        except Exception as e:
            st.error(f"Scanner error: {e}")

# ========================= RESEARCH MODULES =========================
def _two_year_backtest(data, strategies, threshold=85):
    """
    V21 fast backtest.
    Signal discovery is vectorized after a single feature build per stock.
    The threshold is applied after the deterministic signal is found.
    """
    rows = []
    end = pd.Timestamp.today().normalize()
    start_date = end - pd.DateOffset(years=2)

    for ticker, df in data.items():
        if df is None or len(df) < 300:
            continue
        try:
            df = df.sort_index()
            f = features_cached(str(ticker), df).replace([np.inf, -np.inf], np.nan)
            if f.empty:
                continue

            # Historical signal indices are generated once.
            for s in strategies:
                sig = strategy_signal(f, s).fillna(False).to_numpy()
                indices = np.flatnonzero(sig)
                for i in indices:
                    dt = f.index[i]
                    if dt < start_date or dt > end:
                        continue
                    if i >= len(f) - 1:
                        continue

                    # Score is evaluated only on an actual historical signal.
                    hist = f.iloc[:i+1]
                    try:
                        regime, _ = regime_from_index(hist)
                    except Exception:
                        regime = "UNKNOWN"
                    safe, _, _ = safety({}, df.iloc[:i+1])
                    score, parts = final_setup_score(hist, s, regime, safe)
                    if score < threshold:
                        continue

                    entry_i = i + 1
                    entry = float(f.close.iloc[entry_i])
                    sl = entry * 0.93
                    target = entry + 3 * (entry - sl)
                    future = df.iloc[entry_i+1:]

                    outcome = "OPEN"
                    exit_price = float(future.close.iloc[-1]) if not future.empty else entry
                    exit_idx = future.index[-1] if not future.empty else f.index[entry_i]

                    for future_dt, bar in future.iterrows():
                        if float(bar.low) <= sl:
                            outcome = "LOSS"
                            exit_price = sl
                            exit_idx = future_dt
                            break
                        if float(bar.high) >= target:
                            outcome = "WIN"
                            exit_price = target
                            exit_idx = future_dt
                            break

                    r = (exit_price - entry) / (entry - sl)
                    rows.append({
                        "Date": dt.date(),
                        "Ticker": str(ticker).replace(".NS",""),
                        "Strategy": f"S{s}",
                        "Score": score,
                        "Entry": round(entry,2),
                        "SL": round(sl,2),
                        "Target": round(target,2),
                        "Outcome": outcome,
                        "R": round(r,2),
                        "Strategy Score": parts["Strategy"],
                        "HTF": parts["HTF Demand"],
                        "Footprint": parts["Footprint"],
                        "Entry Quality": parts["Entry Quality"],
                        "Relative Strength": parts["Relative Strength"],
                        "Regime": regime,
                        "Safety": safe,
                        "Exit Date": exit_idx.date() if hasattr(exit_idx, "date") else exit_idx
                    })
        except Exception:
            continue
    return pd.DataFrame(rows)

def _learning_summary(bt):
    if bt.empty:return pd.DataFrame()
    x=bt.copy();x["Win"]=(x.Outcome=="WIN").astype(int)
    y=x.groupby("Strategy").agg(Signals=("Ticker","count"),Wins=("Win","sum"),
        WinRate=("Win","mean"),AvgR=("R","mean"),BestScore=("Score","max")).reset_index()
    y["WinRate"]=(y.WinRate*100).round(1); y["AvgR"]=y.AvgR.round(2)
    return y

with tabs[2]:
    st.subheader("📊 V21 Fast Backtest + Adaptive Learning")
    threshold=st.number_input("Score threshold",0,100,85,1,key="bt_threshold_v21")
    st.caption("Features are cached once per symbol; historical signal discovery is vectorized.")
    if st.button("⚡ Run FAST 2-Year Backtest",key="run_bt_v21"):
        if not dhan_configured(): st.error("Dhan credentials are not configured.")
        else:
            try:
                tickers=sorted(set(sum([index_universe(u) for u in ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"]],[])))
                t0=time.perf_counter()
                with st.spinner("Loading cached Dhan history + running vectorized backtest..."):
                    bd=download_prices(tickers,date.today()-timedelta(days=365*3),date.today())
                    st.session_state["backtest_v21"]=_two_year_backtest(bd,[1,2,3,4],int(threshold))
                elapsed=time.perf_counter()-t0
                save_scan_state("INDIA-BACKTEST",len(tickers),elapsed)
                st.success(f"Completed in {elapsed:.1f} seconds.")
            except Exception as e: st.error(f"Backtest error: {e}")
    bt=st.session_state.get("backtest_v21",pd.DataFrame())
    if bt.empty: st.info("Run the 2-Year Backtest to generate results.")
    else:
        st.subheader(f"🏆 Score ≥{int(threshold)} — Best Historical Setups")
        st.dataframe(bt.sort_values(["Score","Date"],ascending=[False,False]).head(100),use_container_width=True,hide_index=True)
        st.subheader("📈 Strategy Performance")
        st.dataframe(_learning_summary(bt),use_container_width=True,hide_index=True)
        st.subheader("🧠 Marking / Score-Band Learning")
        bands=pd.cut(bt.Score,[84,89,94,100],labels=["85–89","90–94","95–100"],include_lowest=True)
        bx=bt.assign(Band=bands,Win=(bt.Outcome=="WIN").astype(int))
        learn=bx.groupby("Band",observed=True).agg(Signals=("Ticker","count"),Wins=("Win","sum"),WinRate=("Win","mean"),AvgR=("R","mean")).reset_index()
        learn["WinRate"]=(learn.WinRate*100).round(1); learn["AvgR"]=learn.AvgR.round(2)
        st.dataframe(learn,use_container_width=True,hide_index=True)
        stabs=st.tabs(["S1","S2","S3","S4"])
        for tab,s in zip(stabs,[1,2,3,4]):
            with tab:
                sr=bt[bt.Strategy==f"S{s}"].sort_values(["Score","Date"],ascending=[False,False])
                if sr.empty: st.info(f"S{s}: no ≥{int(threshold)} historical setups.")
                else: st.dataframe(sr,use_container_width=True,hide_index=True)

with tabs[3]:
    st.subheader("🔬 Forward Testing")
    con=_db()
    try: ft=pd.read_sql_query("SELECT * FROM forward_tests ORDER BY created_at DESC",con)
    finally: con.close()
    if ft.empty: st.info("No forward-test records yet. Complete-rule ≥85 setups will appear here.")
    else:
        a,b,c,d=st.columns(4); a.metric("Total",len(ft)); b.metric("Active",int((ft.status=="ACTIVE").sum()))
        c.metric("Positive R",int((ft.result_r>0).sum())); d.metric("Average R",round(float(ft.result_r.dropna().mean()),2) if ft.result_r.notna().any() else 0)
        st.dataframe(ft.sort_values("score",ascending=False),use_container_width=True,hide_index=True)

with tabs[4]:
    st.subheader("🧠 V21 Adaptive Market Learning")
    bt=st.session_state.get("backtest_v21",pd.DataFrame())
    if bt.empty: st.info("Run the 2-Year Backtest first.")
    else:
        st.dataframe(_learning_summary(bt),use_container_width=True,hide_index=True)
        rows=[]
        for c in ["HTF","Footprint","Strategy Score","Safety"]:
            if c in bt:
                med=bt[c].median(); hi=bt[bt[c]>=med]; lo=bt[bt[c]<med]
                rows.append({"Component":c,"High Avg R":round(float(hi.R.mean()),2) if len(hi) else 0,"Low Avg R":round(float(lo.R.mean()),2) if len(lo) else 0,"High Win %":round(float((hi.Outcome=="WIN").mean()*100),1) if len(hi) else 0})
        st.subheader("Marking Component Learning"); st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

        st.divider()
        st.subheader("🔁 Adaptive Learning Database")
        learn_db = learning_snapshot("INDIA")
        if learn_db.empty:
            st.info("No completed learning observations yet. Forward-test results will automatically feed the learning engine.")
        else:
            st.metric("Completed learning observations", len(learn_db))
            st.dataframe(
                adaptive_component_weights("INDIA"),
                use_container_width=True,
                hide_index=True
            )
            st.caption("Learning adjusts candidate ranking only after sufficient evidence; it never changes the deterministic S1–S4 rules.")

with tabs[5]:
    st.subheader("💎 Long-Term Fundamentals")
    st.warning("Fundamental API is not connected yet. Dhan price/volume data is intentionally kept separate from fundamentals.")
    st.write("This tab is ready for the future fundamental API: quality filters, growth, ROE/ROCE, debt, cash flow and valuation.")

with tabs[6]:
    st.subheader("🏢 Small/Micro Safety")
    st.caption("Independent risk layer; it never changes S1–S4 qualification.")
    con=_db()
    try: syms=pd.read_sql_query("SELECT DISTINCT symbol FROM forward_tests WHERE status='ACTIVE'",con)
    finally: con.close()
    if syms.empty: st.info("No active forward-test stocks yet.")
    else:
        rows=[]
        for sym in syms.symbol:
            d=download_prices([sym],date.today()-timedelta(days=90),date.today()).get(sym,pd.DataFrame())
            sc,status,flags=safety({},d); rows.append({"Stock":sym,"Safety Score":sc,"Status":status,"Flags":", ".join(flags)})
        st.dataframe(pd.DataFrame(rows).sort_values("Safety Score",ascending=False),use_container_width=True,hide_index=True)


with tabs[7]:
    st.subheader("⚡ Live Forward-Test Monitor — Persistent Dhan WebSocket")
    st.caption(
        "The WebSocket stays connected in the Streamlit process, automatically reconnects "
        "after disconnects, and monitors only active ≥85 forward-test candidates."
    )

    con=_db()
    try:
        active=pd.read_sql_query(
            "SELECT symbol,strategy,score,entry,sl,target,status "
            "FROM forward_tests WHERE status='ACTIVE' ORDER BY score DESC",con
        )
    finally:
        con.close()

    if active.empty:
        st.info("No active ≥85 forward-test candidates yet.")
        mgr=get_dhan_live_manager()
        mgr.stop()
    else:
        mgr=start_persistent_live_feed(active.symbol.tolist())
        status,error,last_tick,subscribed=mgr.snapshot()

        a,b,c,d=st.columns(4)
        a.metric("WebSocket",status)
        b.metric("Active setups",len(active))
        c.metric("Subscribed",len(subscribed))
        d.metric("Last tick",last_tick or "—")

        if error:
            st.warning(f"Last WebSocket error: {error}")

        q=live_forward_test_table()
        if q.empty:
            st.info("Waiting for the first Dhan WebSocket ticks...")
        else:
            st.dataframe(q,use_container_width=True,hide_index=True)

        st.caption(
            "The feed is persistent only while this Streamlit application process is running. "
            "If the app sleeps/restarts, the manager reconnects automatically when the app resumes."
        )

with tabs[8]:
    st.subheader("💾 Dhan Data Manager")
    st.caption("First run builds history. Later scans request only missing candles.")
    con=_db()
    try:
        ns=con.execute("SELECT COUNT(DISTINCT symbol) FROM candles").fetchone()[0]
        nc=con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        latest=con.execute("SELECT MAX(dt) FROM candles").fetchone()[0]
    finally:con.close()
    a,b,c=st.columns(3)
    a.metric("Cached stocks",ns);b.metric("Cached candles",f"{nc:,}");c.metric("Latest candle",latest or "—")
    st.info(
        "Daily Scanner updates missing historical candles. Repeated scans use the persistent cache. "
        "Live Forward Testing uses a persistent Dhan WebSocket for the active candidate list."
    )
    if st.button("⛔ Stop Live WebSocket",key="stop_ws"):
        stop_persistent_live_feed()
        st.success("Dhan WebSocket stop requested.")

with tabs[9]:
    st.subheader("🧪 Custom Strategy Lab")
    st.caption("Indian Stocks use Dhan. Forex and Crypto use Twelve Data for historical OHLCV and live price.")

    market=st.selectbox("Market",["Indian Stocks","Forex","Crypto"],key="custom_market")
    if market=="Indian Stocks":
        st.info("Indian Stocks → Dhan historical API + Dhan WebSocket.")
        symbol=st.text_input("Dhan symbol","RELIANCE",key="custom_symbol_stock")
    elif market=="Forex":
        st.info("Forex → Twelve Data composite FX feed. Example: EUR/USD, GBP/USD, USD/JPY.")
        symbol=st.text_input("Forex pair","EUR/USD",key="custom_symbol_fx")
    else:
        st.info("Crypto → Twelve Data digital-asset market data. Example: BTC/USD, ETH/USD.")
        symbol=st.text_input("Crypto pair","BTC/USD",key="custom_symbol_crypto")

    style=st.selectbox("Style",["Intraday","Swing","Positional"],key="custom_style")
    tf=st.selectbox("Timeframe",["5min","15min","1h","4h","1day","1week","1month"],index=4,key="custom_tf")

    if market!="Indian Stocks":
        if not twelvedata_configured():
            st.warning("Add TWELVEDATA_API_KEY to Streamlit Secrets to activate Forex/Crypto data.")
            st.markdown("Twelve Data provides historical OHLC/time-series data and real-time WebSocket quotes for Forex and Crypto.")
        else:
            c1,c2,c3=st.columns(3)
            if st.button("📥 Fetch Historical Data",key="td_fetch"):
                try:
                    years=2 if style!="Intraday" else 1
                    with st.spinner(f"Fetching {symbol} from Twelve Data..."):
                        d=td_market_history(symbol,market,tf,years)
                    st.session_state["td_custom_data"]=d
                    st.success(f"Fetched {len(d):,} candles.")
                except Exception as e:
                    st.error(str(e))
            if st.button("⚡ Get Live Price",key="td_live_price"):
                try:
                    px=td_price(symbol)
                    st.session_state["td_live_px"]=px
                except Exception as e:
                    st.error(str(e))
            if st.button("🧪 Test Symbol",key="td_test_symbol"):
                ok,n,msg=td_validate_symbol(symbol,market)
                if ok: st.success(f"Working: {symbol} — {n} recent daily candles available.")
                else: st.error(f"Symbol test failed: {msg}")

            if "td_live_px" in st.session_state:
                st.metric("Live Price",st.session_state["td_live_px"])
            d=st.session_state.get("td_custom_data",pd.DataFrame())
            if not d.empty:
                st.dataframe(d.tail(200),use_container_width=True)
                st.caption(f"Data source: Twelve Data | {market} | {symbol} | {tf}")

    st.divider()
    st.subheader("Strategy Rules")
    st.text_area("Paste your strategy",height=180,key="custom_strategy",
                 placeholder="Example: RSI > 55, close > 200 EMA, volume > 1.5x 20-day average. SL 7%, target 3R.")
    if st.button("🔍 Validate Strategy",key="custom_validate"):
        st.success("Strategy received. Convert ambiguous language into explicit testable rules before backtesting.")

st.markdown("---")
st.caption("Research / paper-testing system. Real-money Dhan order execution is intentionally disabled.")
