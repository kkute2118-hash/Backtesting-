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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime
from pathlib import Path
import math

st.set_page_config(page_title="Adaptive Trading Intelligence Lab — Professional Final", page_icon="🧠", layout="wide")

APP_VERSION = "GTF PROFESSIONAL CORE v2 — Single Dataset / Local Research"
ARCHITECTURE_STANDARD = "Deterministic rules • no-lookahead • persistent data • adaptive ranking • human approval"

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
DHAN_MIN_INTERVAL=0.205  # stay below the documented 5 data-API requests/sec
_DHAN_RATE_LOCK=threading.Lock()
_DHAN_LAST_REQUEST=0.0
_DHAN_LAST_DATA_ERRORS=[]

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
        mae REAL DEFAULT 0, exit_price REAL, result_r REAL, updated_at TEXT,
        signal_date TEXT, signal_json TEXT)""")
    existing_cols={r[1] for r in con.execute("PRAGMA table_info(forward_tests)").fetchall()}
    for col,typ in [("signal_date","TEXT"),("signal_json","TEXT")]:
        if col not in existing_cols:
            con.execute(f"ALTER TABLE forward_tests ADD COLUMN {col} {typ}")
    con.execute("""CREATE TABLE IF NOT EXISTS scanner_signals(
        signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_key TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        score REAL,
        learned_rank REAL,
        historical_edge_r REAL,
        learning_confidence TEXT,
        regime TEXT,
        safety_status TEXT,
        safety_score REAL,
        entry REAL,
        stop REAL,
        target REAL,
        rr REAL,
        rsi REAL,
        relvol REAL,
        htf_score REAL,
        footprint_score REAL,
        strategy_score REAL,
        entry_quality REAL,
        relative_strength REAL,
        safety_flags TEXT,
        selected_for_forward INTEGER DEFAULT 0
    )""")
    con.execute("""CREATE INDEX IF NOT EXISTS idx_scanner_signals_date
                   ON scanner_signals(signal_date)""")
    con.execute("""CREATE INDEX IF NOT EXISTS idx_scanner_signals_forward
                   ON scanner_signals(selected_for_forward,status)""") if False else None
    con.execute("""CREATE TABLE IF NOT EXISTS forward_observations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forward_id INTEGER NOT NULL,
        observed_at TEXT NOT NULL,
        dt TEXT NOT NULL,
        ltp REAL,
        high REAL,
        low REAL,
        unrealized_return_pct REAL,
        mfe_pct REAL,
        mae_pct REAL,
        status TEXT,
        UNIQUE(forward_id,dt)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS forward_results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forward_id INTEGER NOT NULL UNIQUE,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        entry REAL,
        exit_price REAL,
        result_r REAL,
        return_pct REAL,
        outcome TEXT,
        holding_bars INTEGER,
        mfe_pct REAL,
        mae_pct REAL,
        regime TEXT,
        score REAL,
        closed_at TEXT
    )""")
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

def last_expected_nse_session(day=None):
    """Return the most recent weekday NSE cash-market session date.

    This intentionally does not invent a candle for Saturday/Sunday.  The
    current request (e.g. Saturday 29-Aug-2026) therefore targets Friday
    28-Aug-2026, which is the latest expected equity trading session.
    """
    d = pd.Timestamp(day or date.today()).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def dhan_history(symbol,start_date,end_date):
    clean=str(symbol).upper().replace(".NS","")
    sid=dhan_map().get(clean)
    if not sid:raise ValueError("Security ID not found: "+clean)
    payload={"securityId":sid,"exchangeSegment":"NSE_EQ","instrument":"EQUITY",
             "expiryCode":0,"oi":False,
             "fromDate":pd.Timestamp(start_date).strftime("%Y-%m-%d"),
             "toDate":(pd.Timestamp(end_date)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")}
    global _DHAN_LAST_REQUEST
    last_error=None
    for attempt in range(5):
        with _DHAN_RATE_LOCK:
            wait=DHAN_MIN_INTERVAL-(time.monotonic()-_DHAN_LAST_REQUEST)
            if wait>0: time.sleep(wait)
            _DHAN_LAST_REQUEST=time.monotonic()
        r=requests.post(f"{DHAN_BASE_URL}/charts/historical",headers=_dhan_headers(),
                        json=payload,timeout=45)
        if r.ok: break
        last_error=f"Dhan historical {r.status_code}: {r.text[:250]}"
        if r.status_code in (429,500,502,503,504) or "DH-904" in r.text:
            time.sleep(min(8,2**attempt)); continue
        raise RuntimeError(last_error)
    else:
        raise RuntimeError(last_error or "Dhan historical request failed")
    j=r.json()
    if "close" not in j:raise RuntimeError("Unexpected Dhan historical response")
    d=pd.DataFrame({k:j.get(k,[]) for k in ["open","high","low","close","volume"]})
    if j.get("timestamp"):d.index=pd.to_datetime(j["timestamp"],unit="s",errors="coerce")
    d=d.apply(pd.to_numeric,errors="coerce").dropna(subset=["close"]).sort_index()
    return d

def dhan_historical_smoke_test(symbol="RELIANCE", days=30):
    """One-symbol end-to-end test: Dhan -> parser -> SQLite.

    This is intentionally separate from the 500-stock sync so a broken data
    request or database write can be diagnosed without wasting time.
    """
    symbol=str(symbol).upper().replace(".NS","").strip()
    before_con=_db()
    try:
        before=int(before_con.execute("SELECT COUNT(*) FROM candles WHERE symbol=?",(symbol,)).fetchone()[0])
    finally:
        before_con.close()

    end=last_expected_nse_session()
    start=end-timedelta(days=int(days))
    started=time.perf_counter()
    d=dhan_history(symbol,start,end)
    request_seconds=time.perf_counter()-started
    if d is None or d.empty:
        raise RuntimeError(f"Dhan returned zero candles for {symbol} ({start} to {end}).")

    d=d.copy().sort_index()
    required=["open","high","low","close","volume"]
    missing=[x for x in required if x not in d.columns]
    if missing:
        raise RuntimeError("Parsed historical data is missing columns: "+", ".join(missing))

    con=_db()
    try:
        saved=_save(con,symbol,d)
        after=int(con.execute("SELECT COUNT(*) FROM candles WHERE symbol=?",(symbol,)).fetchone()[0])
        bounds=con.execute("SELECT MIN(dt),MAX(dt) FROM candles WHERE symbol=?",(symbol,)).fetchone()
    finally:
        con.close()

    return {
        "symbol":symbol,"security_id":str(dhan_map().get(symbol,"")),
        "requested_start":str(start),"requested_end":str(end),
        "http/parser_candles":int(len(d)),"saved_rows":int(saved),
        "db_rows_before":before,"db_rows_after":after,
        "db_min":bounds[0] if bounds else None,"db_max":bounds[1] if bounds else None,
        "request_seconds":round(request_seconds,2),
        "sample_first":d.index[0].strftime("%Y-%m-%d"),
        "sample_last":d.index[-1].strftime("%Y-%m-%d"),
        "sample_close":float(d.close.iloc[-1]),
    }


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

def download_prices(tickers,start,end,max_workers=4):
    """
    Dhan historical loader with bounded concurrency and transparent failures.

    Dhan data requests are globally rate-limited by dhan_history(). The worker
    count therefore controls concurrency, not API request rate. Existing local
    candles are reused and only missing ranges are requested.
    """
    if not dhan_configured():
        raise RuntimeError(
            "Dhan credentials are not configured. Add DHAN_CLIENT_ID and "
            "DHAN_ACCESS_TOKEN to Streamlit Secrets."
        )

    dhan_map()
    tickers=list(dict.fromkeys(tickers))
    errors=[]
    workers=max(1,min(int(max_workers),5))

    def worker(symbol):
        try:
            saved=update_dhan_symbol(symbol,start,end)
            return symbol,saved,None
        except Exception as exc:
            return symbol,0,str(exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(worker,s):s for s in tickers}
        for fut in as_completed(futures):
            symbol,saved,err=fut.result()
            if err:
                errors.append(f"{symbol}: {err}")

    con=_db()
    out={}
    try:
        for symbol in tickers:
            clean=str(symbol).upper().replace(".NS","")
            d=_read_cache(con,clean,start,end)
            if not d.empty:
                out[symbol]=d
    finally:
        con.close()

    # Keep the last build errors available to the Data Manager instead of
    # silently converting API failures into "0 cached stocks".
    global _DHAN_LAST_DATA_ERRORS
    _DHAN_LAST_DATA_ERRORS=errors[-100:]

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

def dhan_connection_diagnostic():
    """
    Safe, read-only Dhan connectivity test.

    Checks:
      1. Secrets are present.
      2. Dhan instrument master can be downloaded.
      3. RELIANCE has an NSE equity security ID.
      4. Authenticated Dhan LTP endpoint responds.
      5. Authenticated Dhan historical endpoint returns candles.

    No order endpoint is called.
    """
    result={
        "credentials":False,
        "instrument_master":False,
        "reliance_mapping":False,
        "ltp_api":False,
        "historical_api":False,
        "details":[]
    }

    if not dhan_configured():
        result["details"].append("Dhan secrets missing: DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN")
        return result

    result["credentials"]=True

    try:
        mp=dhan_map()
        result["instrument_master"]=True
    except Exception as exc:
        result["details"].append(f"Instrument master failed: {exc}")
        return result

    sid=mp.get("RELIANCE")
    if not sid:
        result["details"].append("RELIANCE NSE security ID was not found in Dhan instrument master.")
        return result

    result["reliance_mapping"]=True
    result["details"].append(f"RELIANCE security ID: {sid}")

    try:
        ltp=dhan_live_ltp(["RELIANCE"])
        if ltp:
            result["ltp_api"]=True
            result["details"].append(f"RELIANCE LTP: ₹{ltp.get('RELIANCE', 0):,.2f}")
        else:
            result["details"].append("LTP endpoint responded but returned no RELIANCE price.")
    except Exception as exc:
        result["details"].append(f"LTP API failed: {exc}")

    try:
        d=dhan_history("RELIANCE",date.today()-timedelta(days=7),date.today())
        if d is not None and not d.empty:
            result["historical_api"]=True
            result["details"].append(f"Historical API returned {len(d)} candles.")
        else:
            result["details"].append("Historical API returned no candles.")
    except Exception as exc:
        result["details"].append(f"Historical API failed: {exc}")

    return result


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
        self.last_persist={}

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
        # Persist at most once per second per symbol. Dhan remains tick-by-tick,
        # but the database does not need every tick for a research dashboard.
        now_dt=datetime.now()
        last=self.last_persist.get(symbol)
        if last is not None and (now_dt-last).total_seconds()<1.0:
            with self.lock:
                self.last_tick=now_dt.isoformat(timespec="seconds")
                self.status="LIVE"
            return
        self.last_persist[symbol]=now_dt
        now=now_dt.isoformat(timespec="seconds")
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
    con = _db()
    try:
        q = pd.read_sql_query(
            "SELECT * FROM forward_tests WHERE status='ACTIVE' ORDER BY score DESC",
            con
        )
    finally:
        con.close()

    if q.empty:
        return q

    live = read_live_prices(q.symbol.tolist())
    if not live.empty:
        q = q.merge(live[["symbol", "ts", "ltp"]], on="symbol", how="left")
        q["LTP"] = q["ltp"]
        q["P/L %"] = (q["LTP"] / q["entry"] - 1) * 100
        q["Live Updated"] = q["ts"]
    return q


FUNDAMENTAL_CACHE_TTL_HOURS = 24
NEWS_CACHE_TTL_HOURS = 6

def _ensure_research_tables():
    con=_db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS fundamentals_cache(
            symbol TEXT PRIMARY KEY, fetched_at TEXT, payload TEXT, score REAL, status TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS news_cache(
            symbol TEXT PRIMARY KEY, fetched_at TEXT, payload TEXT, sentiment REAL, risk REAL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS research_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, market TEXT, symbol TEXT,
            study TEXT, score REAL, outcome TEXT, r_multiple REAL, regime TEXT, features TEXT)""")
        con.commit()
    finally: con.close()

def _td_get(endpoint, params, timeout=30):
    if not twelvedata_configured(): return {}
    r=requests.get(f"{TWELVE_BASE}/{endpoint}",headers=_td_headers(),params=params,timeout=timeout)
    if not r.ok: return {"_error":f"HTTP {r.status_code}"}
    try:j=r.json()
    except Exception:return {"_error":"Invalid JSON"}
    if isinstance(j,dict) and j.get("status")=="error": return {"_error":j.get("message","API error")}
    return j

def _fresh(ts, hours):
    try:return (datetime.now()-pd.Timestamp(ts).to_pydatetime()).total_seconds()<hours*3600
    except Exception:return False

def _fundamental_score(payload):
    if not payload:return 0,"NO_DATA",[]
    vals=[]; flags=[]
    stats=payload.get("statistics",{}) if isinstance(payload.get("statistics"),dict) else {}
    prof=payload.get("profile",{}) if isinstance(payload.get("profile"),dict) else {}
    def num(*keys):
        for k in keys:
            v=stats.get(k,prof.get(k))
            try:
                if v is not None:return float(v)
            except:pass
        return np.nan
    roe=num("return_on_equity","roe"); margin=num("profit_margin","net_profit_margin"); debt=num("debt_to_equity","debt_equity"); pe=num("pe_ratio","trailing_pe"); pb=num("price_to_book","pb_ratio")
    score=50
    if np.isfinite(roe): score += 10 if roe>=15 else 5 if roe>=10 else -5 if roe<5 else 0
    if np.isfinite(margin): score += 10 if margin>=10 else 5 if margin>=5 else -5 if margin<0 else 0
    if np.isfinite(debt): score += 10 if debt<=0.5 else 5 if debt<=1 else -10 if debt>2 else 0
    if np.isfinite(pe): score += 5 if 5<=pe<=35 else -5 if pe>60 else 0
    if np.isfinite(pb): score += 5 if pb<=6 else -3 if pb>10 else 0
    if np.isfinite(roe) and roe<0: flags.append("Negative ROE")
    if np.isfinite(margin) and margin<0: flags.append("Negative margin")
    if np.isfinite(debt) and debt>2: flags.append("High leverage")
    return int(np.clip(score,0,100)),("STRONG" if score>=75 else "WATCH" if score>=55 else "WEAK"),flags

def company_info(ticker):
    _ensure_research_tables(); sym=str(ticker).upper().replace(".NS","")
    con=_db()
    try:
        row=con.execute("SELECT fetched_at,payload,score,status FROM fundamentals_cache WHERE symbol=?",(sym,)).fetchone()
    finally:con.close()
    if row and _fresh(row[0],FUNDAMENTAL_CACHE_TTL_HOURS):
        try:return json.loads(row[1]),[]
        except:return {},[]
    if not twelvedata_configured(): return {},["Twelve Data key not configured"]
    payload={}
    for ep in ["profile","statistics"]:
        j=_td_get(ep,{"symbol":sym,"exchange":"XNSE"})
        if j and "_error" not in j: payload[ep]=j
    score,status,flags=_fundamental_score(payload)
    con=_db()
    try:
        con.execute("INSERT OR REPLACE INTO fundamentals_cache VALUES(?,?,?,?,?)",(sym,datetime.now().isoformat(timespec="seconds"),json.dumps(payload,default=str),score,status));con.commit()
    finally:con.close()
    return payload,flags

def news_snapshot(ticker,days=30):
    _ensure_research_tables(); sym=str(ticker).upper().replace(".NS","")
    con=_db()
    try:row=con.execute("SELECT fetched_at,payload,sentiment,risk FROM news_cache WHERE symbol=?",(sym,)).fetchone()
    finally:con.close()
    if row and _fresh(row[0],NEWS_CACHE_TTL_HOURS):
        try:return json.loads(row[1]),float(row[2]),float(row[3])
        except:return [],0,0
    if not twelvedata_configured():return [],0,0
    j=_td_get("press_releases",{"symbol":sym,"exchange":"XNSE","start_date":(date.today()-timedelta(days=days)).isoformat(),"end_date":date.today().isoformat(),"outputsize":10})
    items=j.get("press_releases",[]) if isinstance(j,dict) else []
    pos=["order","contract","growth","profit","approval","launch","partnership","expansion","acquisition","award"]
    neg=["fraud","default","resign","resignation","penalty","investigation","notice","downgrade","loss","pledge","insolvency","regulatory"]
    sentiment=0; risk=0
    for it in items:
        text=(str(it.get("title",""))+" "+str(it.get("body",""))).lower()
        sentiment += sum(text.count(w) for w in pos)-sum(text.count(w) for w in neg)
        risk += sum(text.count(w) for w in neg)
    sentiment=float(np.clip(sentiment*5,-100,100)); risk=float(np.clip(risk*15,0,100))
    con=_db()
    try:con.execute("INSERT OR REPLACE INTO news_cache VALUES(?,?,?,?,?)",(sym,datetime.now().isoformat(timespec="seconds"),json.dumps(items,default=str),sentiment,risk));con.commit()
    finally:con.close()
    return items,sentiment,risk

def advanced_small_micro_safety(info,d,news_risk=0):
    score,status,flags=safety(info,d)
    extra=0
    if d is not None and len(d)>=60:
        traded=(d.close*d.volume).tail(20).mean(); gap=(d.open/d.close.shift(1)-1).abs().tail(60)
        circuit=(d.close.pct_change().abs().tail(120)>=0.095).sum()
        if traded<1_000_000: extra-=10; flags.append("Thin traded value")
        elif traded<5_000_000: extra-=5; flags.append("Moderate liquidity")
        if gap.mean()>0.05: extra-=10; flags.append("Frequent large gaps")
        if circuit>=3: extra-=15; flags.append("Frequent circuit-like moves")
    if news_risk>=30: extra-=10; flags.append("News/event risk")
    score=int(np.clip(score+extra,0,100)); status="ELIGIBLE" if score>=70 else "CAUTION" if score>=50 else "REJECT"
    return score,status,flags


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

# ========================= STRATEGY 4 RECOVERY STUDY =========================
def strategy4_recovery_features(d):
    """Research-only pattern detector for the S4 problem described by the user.

    It does NOT modify Strategy 4. It studies a different entry structure:
    impulse -> consolidation/retracement -> reclaim -> higher-high confirmation.
    Every calculation is strictly as-of the current bar.
    """
    if d is None or len(d) < 120:
        return pd.DataFrame(index=getattr(d, "index", []))
    x=d.copy().sort_index()
    x["ema20_r"]=ema(x.close,20)
    x["ema50_r"]=ema(x.close,50)
    x["atr14_r"]=(pd.concat([
        x.high-x.low,
        (x.high-x.close.shift()).abs(),
        (x.low-x.close.shift()).abs()
    ],axis=1).max(axis=1)).rolling(14,min_periods=14).mean()
    x["vol20_r"]=sma(x.volume,20)
    x["relvol_r"]=x.volume/x.vol20_r.replace(0,np.nan)

    # Prior impulse: use only completed bars before the current consolidation.
    x["prior_high_60"]=x.high.shift(10).rolling(50,min_periods=30).max()
    x["prior_low_60"]=x.low.shift(10).rolling(50,min_periods=30).min()
    x["impulse_return"]=(x.prior_high_60/x.prior_low_60-1)

    # Consolidation range: prior 15 bars, excluding today's bar.
    x["base_high"]=x.high.shift(1).rolling(15,min_periods=10).max()
    x["base_low"]=x.low.shift(1).rolling(15,min_periods=10).min()
    x["base_range"]=(x.base_high/x.base_low-1)
    x["base_atr"]=(x.high-x.low).shift(1).rolling(15,min_periods=10).mean()
    x["prior_atr"]=(x.high-x.low).shift(16).rolling(30,min_periods=20).mean()
    x["range_compression"]=x.base_atr/x.prior_atr.replace(0,np.nan)
    x["base_vol"] = x.volume.shift(1).rolling(15,min_periods=10).mean()
    x["impulse_vol"] = x.volume.shift(16).rolling(30,min_periods=20).mean()
    x["volume_contraction"]=x.base_vol/x.impulse_vol.replace(0,np.nan)

    # Retracement depth from prior impulse high into the base.
    x["retracement"]=(x.prior_high_60-x.base_low)/(x.prior_high_60-x.prior_low_60).replace(0,np.nan)

    # Current confirmation: reclaim EMA20 + break above the base high / recent swing high.
    x["reclaim_ema20"]=(x.close>x.ema20_r)&(x.close.shift(1)<=x.ema20_r.shift(1))
    x["higher_high"] = x.high > x.high.shift(1).rolling(10,min_periods=5).max()
    x["base_breakout"] = x.close > x.base_high
    x["close_location"]=(x.close-x.low)/(x.high-x.low).replace(0,np.nan)
    return x

def strategy4_recovery_signal(d, min_impulse=0.20, max_base_range=0.18,
                              max_retracement=0.65, max_range_ratio=0.80,
                              max_volume_ratio=0.90, min_relvol=1.20):
    """Return a boolean series for the research-only S4 recovery pattern.

    Core idea: a meaningful prior move, controlled retracement/consolidation,
    volatility/volume contraction, then a reclaim + higher-high confirmation.
    This is deliberately separate from the exact S4 rule set.
    """
    x=strategy4_recovery_features(d)
    if x.empty: return pd.Series(False,index=getattr(d,"index",[]))
    monthly=_monthly_asof(d)
    monthly["rsi14"]=rsi(monthly.close,14)
    monthly["ema10"]=ema(monthly.close,10)
    monthly["ema20"]=ema(monthly.close,20)
    monthly["mom"]=monthly.close.pct_change()*100
    vals=[]
    for dt in d.index:
        mm=monthly[monthly.index.to_period("M")<=dt.to_period("M")]
        vals.append(mm.iloc[-1] if not mm.empty else pd.Series(dtype=float))
    x["mrsi4"]=[v.get("rsi14",np.nan) for v in vals]
    x["mema10_4"]=[v.get("ema10",np.nan) for v in vals]
    x["mema20_4"]=[v.get("ema20",np.nan) for v in vals]
    x["mmom4"]=[v.get("mom",np.nan) for v in vals]

    return (
        (x.impulse_return>=min_impulse) &
        (x.base_range<=max_base_range) &
        (x.retracement<=max_retracement) &
        (x.range_compression<=max_range_ratio) &
        (x.volume_contraction<=max_volume_ratio) &
        (x.close>=x.ema50_r) &
        (x.mrsi4>=50) &
        (x.mema10_4>=x.mema20_4) &
        (x.reclaim_ema20 | x.base_breakout) &
        x.higher_high &
        (x.close_location>=0.60) &
        (x.relvol_r>=min_relvol)
    )

def _s4_recovery_quality(d):
    x=strategy4_recovery_features(d)
    if x.empty: return 0,{}
    z=x.iloc[-1]
    pts=0
    pts += 20 if pd.notna(z.impulse_return) and z.impulse_return>=0.40 else 15 if pd.notna(z.impulse_return) and z.impulse_return>=0.30 else 10 if pd.notna(z.impulse_return) and z.impulse_return>=0.20 else 0
    pts += 20 if pd.notna(z.base_range) and z.base_range<=0.10 else 15 if pd.notna(z.base_range) and z.base_range<=0.14 else 10 if pd.notna(z.base_range) and z.base_range<=0.18 else 0
    pts += 15 if pd.notna(z.retracement) and z.retracement<=0.40 else 10 if pd.notna(z.retracement) and z.retracement<=0.55 else 5 if pd.notna(z.retracement) and z.retracement<=0.65 else 0
    pts += 15 if pd.notna(z.range_compression) and z.range_compression<=0.60 else 10 if pd.notna(z.range_compression) and z.range_compression<=0.80 else 5 if pd.notna(z.range_compression) and z.range_compression<=1 else 0
    pts += 10 if pd.notna(z.volume_contraction) and z.volume_contraction<=0.70 else 7 if pd.notna(z.volume_contraction) and z.volume_contraction<=0.90 else 0
    pts += 10 if pd.notna(z.relvol_r) and z.relvol_r>=1.50 else 7 if pd.notna(z.relvol_r) and z.relvol_r>=1.20 else 0
    pts += 10 if bool(z.higher_high) and bool(z.base_breakout) else 6 if bool(z.higher_high) or bool(z.reclaim_ema20) else 0
    return int(min(100,pts)), {
        "Impulse %": round(float(z.impulse_return*100),1) if pd.notna(z.impulse_return) else np.nan,
        "Base Range %": round(float(z.base_range*100),1) if pd.notna(z.base_range) else np.nan,
        "Retracement %": round(float(z.retracement*100),1) if pd.notna(z.retracement) else np.nan,
        "Range Compression": round(float(z.range_compression),2) if pd.notna(z.range_compression) else np.nan,
        "Volume Contraction": round(float(z.volume_contraction),2) if pd.notna(z.volume_contraction) else np.nan,
        "RelVol": round(float(z.relvol_r),2) if pd.notna(z.relvol_r) else np.nan,
        "Higher High": bool(z.higher_high),
        "EMA20 Reclaim": bool(z.reclaim_ema20),
        "Base Breakout": bool(z.base_breakout)
    }

def study_s4_recovery(data, min_score=70, max_stocks=None):
    """Fast cross-sectional study. Does not alter exact S4 results."""
    rows=[]
    items=list(data.items())
    if max_stocks: items=items[:int(max_stocks)]
    for ticker,d in items:
        if d is None or len(d)<160: continue
        sig=strategy4_recovery_signal(d).iloc[-1]
        score,parts=_s4_recovery_quality(d)
        if not bool(sig) or score<min_score: continue
        z=d.iloc[-1]
        rows.append({"Ticker":str(ticker).replace(".NS",""),"Study Score":score,
                     "Entry":round(float(z.close),2),"Signal":"RECOVERY → HIGHER HIGH",
                     **parts})
    return pd.DataFrame(rows).sort_values(["Study Score","RelVol"],ascending=[False,False]) if rows else pd.DataFrame()


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


# ========================= FINAL FAST EXECUTION + LEARNING =========================
# Final architecture principle:
#   - Build expensive features once per symbol.
#   - Keep historical scans vectorized.
#   - Use WebSocket only for live 1-minute updates.
#   - Persist learning observations so the model improves from completed trades.
#
# The strategy rules themselves are intentionally unchanged.

FEATURE_CACHE_VERSION = "FINAL_ASOF_1"

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
        # Backward-compatible migration: older deployments created a narrower
        # learning_observations table. Never require a destructive DB reset.
        cols={r[1] for r in con.execute("PRAGMA table_info(learning_observations)").fetchall()}
        for col,typ in {
            "learned_score":"REAL", "holding_bars":"INTEGER",
            "entry":"REAL", "exit_price":"REAL", "result_r":"REAL",
            "source":"TEXT"
        }.items():
            if col not in cols:
                con.execute(f"ALTER TABLE learning_observations ADD COLUMN {col} {typ}")

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



# ========================= LONG-LIVED FAST ENGINE =========================
ENGINE_VERSION = "FINAL-2_ASOF_CACHE"

def ensure_engine_tables():
    con = _db()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS feature_snapshots(
                symbol TEXT PRIMARY KEY,
                last_dt TEXT NOT NULL,
                n_rows INTEGER NOT NULL,
                payload BLOB NOT NULL,
                engine_version TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS signal_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal_dt TEXT NOT NULL,
                score REAL,
                learned_score REAL,
                status TEXT DEFAULT 'CANDIDATE',
                created_at TEXT NOT NULL,
                UNIQUE(market,symbol,strategy,signal_dt)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS learning_observations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal_dt TEXT NOT NULL,
                score REAL,
                learned_score REAL,
                result_r REAL,
                outcome TEXT,
                holding_bars INTEGER,
                regime TEXT,
                htf REAL,
                footprint REAL,
                strategy_score REAL,
                entry_quality REAL,
                relative_strength REAL,
                safety_score REAL,
                source TEXT
            )
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_market_strategy
            ON learning_observations(market,strategy)
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS system_metrics(
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        con.commit()
    finally:
        con.close()

ensure_engine_tables()

def _metric_set(key, value):
    con = _db()
    try:
        con.execute(
            "INSERT OR REPLACE INTO system_metrics(key,value,updated_at) VALUES(?,?,?)",
            (key, json.dumps(value), datetime.now().isoformat(timespec="seconds"))
        )
        con.commit()
    finally:
        con.close()

def _metric_get(key, default=None):
    con = _db()
    try:
        row = con.execute("SELECT value FROM system_metrics WHERE key=?", (key,)).fetchone()
    finally:
        con.close()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return row[0]

def _save_feature_snapshot(symbol, df):
    # Keep the feature store compact: one DataFrame per symbol.
    if df is None or df.empty:
        return
    con = _db()
    try:
        # pd.to_pickle does not support bytes in all versions, so use a bytes buffer.
        buf = io.BytesIO()
        df.to_pickle(buf)
        con.execute("""
            INSERT OR REPLACE INTO feature_snapshots
            (symbol,last_dt,n_rows,payload,engine_version)
            VALUES(?,?,?,?,?)
        """, (
            str(symbol).upper().replace(".NS",""),
            pd.Timestamp(df.index[-1]).isoformat(),
            len(df),
            sqlite3.Binary(buf.getvalue()),
            ENGINE_VERSION
        ))
        con.commit()
    finally:
        con.close()

def _load_feature_snapshot(symbol):
    con = _db()
    try:
        row = con.execute(
            "SELECT payload FROM feature_snapshots WHERE symbol=? AND engine_version=?",
            (str(symbol).upper().replace(".NS",""), ENGINE_VERSION)
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    try:
        return pd.read_pickle(io.BytesIO(row[0]))
    except Exception:
        return None

@st.cache_data(ttl=86400,show_spinner=False)
def features_fast(symbol, df):
    """Strict as-of feature engine. Historical rows never see future days inside
    their current week/month. This is the core anti-lookahead safeguard."""
    key=_load_feature_snapshot(symbol)
    last_dt=pd.Timestamp(df.index[-1]).isoformat() if df is not None and not df.empty else ""
    if key is not None and not key.empty and pd.Timestamp(key.index[-1]).isoformat()==last_dt:
        return key
    d=df.sort_index().copy()
    x=d.copy()
    for n in [10,20,50,200,250]:
        x[f"ema{n}"]=ema(x.close,n)
    x["vol20"]=sma(x.volume,20); x["vol30"]=sma(x.volume,30); x["rsi14"]=rsi(x.close); x["relvol"]=x.volume/x.vol20
    tr=pd.concat([x.high-x.low,(x.high-x.close.shift()).abs(),(x.low-x.close.shift()).abs()],axis=1).max(axis=1)
    x["atr14"]=tr.rolling(14).mean()

    # Weekly as-of state: one cheap loop per week, not one loop per day.
    wk_key=x.index.to_period("W-FRI")
    wk_rows=[]
    for period, g in x.groupby(wk_key, sort=True):
        g=g.sort_index(); close=g.close.iloc[-1]
        wk_rows.append((period, g.open.iloc[0], g.high.max(), g.low.min(), close, g.volume.sum()))
    wk=pd.DataFrame(wk_rows, columns=["period","open","high","low","close","volume"]).set_index("period")
    wk["rsi14"]=rsi(wk.close,14); wk["ema20"]=ema(wk.close,20); wk["ema50"]=ema(wk.close,50)
    wk_map={p:row for p,row in wk.iterrows()}
    x["wrsi14"]=[wk_map.get(p,{}).get("rsi14",np.nan) for p in wk_key]
    x["wema20"]=[wk_map.get(p,{}).get("ema20",np.nan) for p in wk_key]
    x["wema50"]=[wk_map.get(p,{}).get("ema50",np.nan) for p in wk_key]
    x["wclose"]=[wk_map.get(p,{}).get("close",np.nan) for p in wk_key]

    # Monthly as-of state. Each daily row uses the current month's partial OHLCV.
    mo_key=x.index.to_period("M")
    mo_rows=[]
    for period,g in x.groupby(mo_key,sort=True):
        g=g.sort_index(); mo_rows.append((period,g.open.iloc[0],g.high.max(),g.low.min(),g.close.iloc[-1],g.volume.sum()))
    mo=pd.DataFrame(mo_rows,columns=["period","open","high","low","close","volume"]).set_index("period")
    mo["rsi14"]=rsi(mo.close,14); mo["ema10"]=ema(mo.close,10); mo["ema15"]=ema(mo.close,15); mo["ema20"]=ema(mo.close,20)
    mo["mom"]=mo.close.pct_change()*100; mo["prev_close"]=mo.close.shift(1); mo["prev_high"]=mo.high.shift(1); mo["prev_low"]=mo.low.shift(1)
    mo["mom20max"]=mo.mom.rolling(20,min_periods=1).max()
    cross=(mo.ema10>mo.ema20)&(mo.ema10.shift(1)<=mo.ema20.shift(1)); mo["cross_10_20"]=cross.astype(int); mo["cross_count20"]=mo.cross_10_20.rolling(20,min_periods=1).sum()
    mo_map={p:row for p,row in mo.iterrows()}
    fields={"mclose":"close","mopen":"open","mhigh":"high","mlow":"low","mrsi14":"rsi14","mema10":"ema10","mema15":"ema15","mema20":"ema20","mmom":"mom","mmax20":"mom20max","mprevclose":"prev_close","mprevhigh":"prev_high","mprevlow":"prev_low","m_cross_count20":"cross_count20","m_cross_10_20":"cross_10_20"}
    for out,src in fields.items():
        x[out]=[mo_map.get(p,{}).get(src,np.nan) for p in mo_key]
    x=x.replace([np.inf,-np.inf],np.nan)
    try:_save_feature_snapshot(symbol,x)
    except Exception:pass
    return x

def build_fast_data_cache(tickers, start, end, max_workers=5):
    """
    First run: populate Dhan history.
    Later runs: fetch only missing ranges and read locally.
    Concurrency is bounded to respect Dhan Data API limits while avoiding
    serial per-symbol waits. Dhan documents Data APIs at 5 req/sec and
    100,000/day; this engine uses a conservative worker pool. 
    """
    if not dhan_configured():
        raise RuntimeError("Dhan credentials are not configured")
    tickers = list(dict.fromkeys(tickers))
    results, errors = {}, []

    def worker(symbol):
        try:
            update_dhan_symbol(symbol, start, end)
            con = _db()
            try:
                d = _read_cache(
                    con, str(symbol).upper().replace(".NS",""), start, end
                )
            finally:
                con.close()
            return symbol, d, None
        except Exception as e:
            return symbol, pd.DataFrame(), str(e)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, s): s for s in tickers}
        for fut in as_completed(futures):
            symbol, d, err = fut.result()
            if err:
                errors.append(f"{symbol}: {err}")
            elif not d.empty:
                results[symbol] = d

    if errors:
        _metric_set("last_dhan_errors", errors[:50])
    _metric_set("last_cache_symbols", len(results))
    return results

def _row_score(f, i, strategy, regime, safety_score):
    """
    Fast historical score from the precomputed feature matrix.
    Used by the learning/backtest engine so it doesn't rebuild features
    for every historical date.
    """
    if i < 0 or i >= len(f):
        return 0, {}
    hist = f.iloc[:i+1]
    return final_setup_score(hist, strategy, regime, safety_score)

def _fast_trade_outcome(df, entry_i, stop, target, max_bars=250):
    future = df.iloc[entry_i+1:entry_i+1+max_bars]
    if future.empty:
        return "OPEN", float(df.close.iloc[entry_i]), len(future)

    for n, (_, bar) in enumerate(future.iterrows(), start=1):
        # Conservative: if both stop and target are touched in one bar,
        # count the stop first.
        if float(bar.low) <= stop:
            return "LOSS", float(stop), n
        if float(bar.high) >= target:
            return "WIN", float(target), n
    return "OPEN", float(future.close.iloc[-1]), len(future)


# ================= PROFESSIONAL LOCAL WALK-FORWARD BACKTEST =================
# Backtesting is deliberately separated from Dhan. The backtest engine never
# calls an API. Dhan is used only by the explicit dataset-builder stage.
BT_CACHE_DIR=Path("backtest_cache")
BT_CACHE_DIR.mkdir(exist_ok=True)
BT_WARMUP_DAYS=900  # enough history for EMA250 + weekly/monthly features
BT_COST_PCT=0.23   # conservative round-trip cost assumption (%)

def _bt_required_data_start(start_date):
    return pd.Timestamp(start_date).date() - timedelta(days=BT_WARMUP_DAYS)

def _ensure_backtest_tables():
    con=_db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS backtest_runs(
            run_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, market TEXT,
            period TEXT, start_date TEXT, end_date TEXT, threshold REAL,
            universe_size INTEGER, trades INTEGER, elapsed_seconds REAL, status TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS backtest_trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, created_at TEXT,
            ticker TEXT, strategy TEXT, signal_date TEXT, entry_date TEXT, exit_date TEXT,
            score REAL, gate85 INTEGER, outcome TEXT, entry REAL, stop REAL, target REAL,
            exit_price REAL, return_pct REAL, r_multiple REAL, pnl_pct REAL, holding_bars INTEGER,
            mfe_pct REAL, mae_pct REAL, strategy_score REAL, htf REAL, footprint REAL,
            trend REAL, entry_quality REAL, relative_strength REAL, market_regime TEXT, safety REAL,
            source TEXT
        )""")
        con.commit()
    finally:
        con.close()

_ensure_backtest_tables()

def _persist_backtest(bt, period, start_date, end_date, threshold, universe_size, elapsed, status="COMPLETED"):
    _ensure_backtest_tables()
    con=_db()
    try:
        cur=con.execute("""INSERT INTO backtest_runs(created_at,market,period,start_date,end_date,threshold,universe_size,trades,elapsed_seconds,status)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (datetime.now().isoformat(timespec="seconds"),"INDIA",period,str(start_date),str(end_date),float(threshold),int(universe_size),int(len(bt) if bt is not None else 0),float(elapsed),status))
        run_id=cur.lastrowid
        if bt is not None and not bt.empty:
            rows=[]
            for _,r in bt.iterrows():
                rows.append((run_id,datetime.now().isoformat(timespec="seconds"),str(r.get("Ticker","")),str(r.get("Strategy","")),str(r.get("Date","")),str(r.get("Entry Date",r.get("Date",""))),str(r.get("Exit Date","")),
                    float(r.get("Score",0)),int(float(r.get("Score",0))>=85),str(r.get("Outcome","")),float(r.get("Entry",np.nan)),float(r.get("SL",np.nan)),float(r.get("Target",np.nan)),float(r.get("Exit",np.nan)),float(r.get("Return %",np.nan)),float(r.get("R",np.nan)),float(r.get("Return %",np.nan)),int(r.get("Holding Bars",0)),float(r.get("MFE %",np.nan)),float(r.get("MAE %",np.nan)),float(r.get("Strategy Score",np.nan)),float(r.get("HTF",np.nan)),float(r.get("Footprint",np.nan)),float(r.get("Trend",np.nan)),float(r.get("Entry Quality",np.nan)),float(r.get("Relative Strength",np.nan)),str(r.get("Regime","")),float(r.get("Safety",np.nan)),"backtest"))
            con.executemany("""INSERT INTO backtest_trades(run_id,created_at,ticker,strategy,signal_date,entry_date,exit_date,score,gate85,outcome,entry,stop,target,exit_price,return_pct,r_multiple,pnl_pct,holding_bars,mfe_pct,mae_pct,strategy_score,htf,footprint,trend,entry_quality,relative_strength,market_regime,safety,source)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",rows)
        con.commit()
        return run_id
    finally:
        con.close()

def _load_latest_backtest():
    _ensure_backtest_tables()
    con=_db()
    try:
        run=con.execute("SELECT * FROM backtest_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        if not run:return pd.DataFrame(),None
        rid=run[0]
        bt=pd.read_sql_query("SELECT ticker AS Ticker,strategy AS Strategy,signal_date AS Date,entry_date AS \"Entry Date\",exit_date AS \"Exit Date\",score AS Score,gate85 AS \"≥85 Gate\",outcome AS Outcome,entry AS Entry,stop AS SL,target AS Target,exit_price AS Exit,return_pct AS \"Return %\",r_multiple AS R,holding_bars AS \"Holding Bars\",mfe_pct AS \"MFE %\",mae_pct AS \"MAE %\",strategy_score AS \"Strategy Score\",htf AS HTF,footprint AS Footprint,trend AS Trend,entry_quality AS \"Entry Quality\",relative_strength AS \"Relative Strength\",market_regime AS Regime,safety AS Safety FROM backtest_trades WHERE run_id=? ORDER BY score DESC",con,params=(rid,))
        return bt,run
    finally:
        con.close()

def _bt_file(symbol):
    return BT_CACHE_DIR/(str(symbol).upper().replace('.NS','').replace('/','_')+'.pkl')

def load_local_market_dataset(tickers,start_date,end_date,min_bars=160):
    """LOCAL-ONLY reader for scanner/research. Never calls Dhan."""
    out={}
    con=_db()
    try:
        for t in tickers:
            s=str(t).upper().replace(".NS","")
            d=_read_cache(con,s,start_date,end_date)
            if d is not None and len(d)>=min_bars: out[t]=d
    finally:
        con.close()
    return out


def build_local_backtest_dataset(tickers,start_date,end_date):
    """Compatibility wrapper. Never creates a second market-data cache."""
    data=load_local_market_dataset(tickers,start_date,end_date,min_bars=260)
    return len(data), [str(t).replace(".NS","") for t in tickers if t not in data]

def sync_missing_backtest_data(tickers,start_date,end_date,max_workers=5):
    """Explicit acquisition stage only. Backtest itself never calls this."""
    data_start=_bt_required_data_start(start_date)
    return download_prices(tuple(tickers),data_start,end_date,max_workers=max_workers)

def local_backtest_status(tickers,start_date,end_date):
    """Single-batch readiness query against the persistent SQLite candle store."""
    data_start=_bt_required_data_start(start_date)
    symbols=[str(t).upper().replace(".NS","") for t in tickers]
    if not symbols:
        return pd.DataFrame(columns=["Ticker","Bars","Ready","Start","End"])
    con=_db()
    try:
        qmarks=",".join(["?"]*len(symbols))
        params=symbols+[pd.Timestamp(data_start).strftime("%Y-%m-%d"),
                        pd.Timestamp(end_date).strftime("%Y-%m-%d")]
        q=pd.read_sql_query(
            f"""SELECT symbol,COUNT(*) AS Bars,MIN(dt) AS Start,MAX(dt) AS End
                FROM candles
                WHERE symbol IN ({qmarks}) AND dt>=? AND dt<=?
                GROUP BY symbol""",
            con,params=params
        )
    finally:
        con.close()
    by={str(r.symbol).upper():r for r in q.itertuples()}
    rows=[]
    for t,s in zip(tickers,symbols):
        r=by.get(s)
        n=int(r.Bars) if r is not None else 0
        rows.append({
            "Ticker":str(t).replace(".NS",""),
            "Bars":n,
            "Ready":bool(n>=260),
            "Start":pd.to_datetime(r.Start).date() if r is not None else None,
            "End":pd.to_datetime(r.End).date() if r is not None else None
        })
    return pd.DataFrame(rows)

def load_local_backtest_data(tickers,start_date,end_date):
    """Direct, batch SQLite read. Backtest never uses a second market-data cache."""
    data_start=_bt_required_data_start(start_date)
    symbols=[str(t).upper().replace(".NS","") for t in tickers]
    if not symbols:return {}
    con=_db()
    try:
        qmarks=",".join(["?"]*len(symbols))
        q=pd.read_sql_query(
            f"""SELECT symbol,dt,open,high,low,close,volume FROM candles
                WHERE symbol IN ({qmarks}) AND dt>=? AND dt<=?
                ORDER BY symbol,dt""",
            con,params=symbols+[pd.Timestamp(data_start).strftime("%Y-%m-%d"),
                                pd.Timestamp(end_date).strftime("%Y-%m-%d")]
        )
    finally:con.close()
    out={}
    if q.empty:return out
    for s,g in q.groupby("symbol",sort=False):
        d=g.drop(columns=["symbol"]).copy(); d.dt=pd.to_datetime(d.dt); d=d.set_index("dt"); d.index.name="date"
        if len(d)>=260:
            original=next((t for t in tickers if str(t).upper().replace(".NS","")==str(s).upper()),s)
            out[original]=d
    return out

def _professional_bt(data,strategies,threshold,start_date,end_date):
    """Local-only walk-forward replay with rich learning fields."""
    rows=[];start=pd.Timestamp(start_date);end=pd.Timestamp(end_date)
    for ticker,df in data.items():
        if len(df)<260:continue
        try:
            df=df.sort_index();f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
            if f.empty:continue
            for s in strategies:
                sig=strategy_signal(f,s).fillna(False).to_numpy()
                for i in np.flatnonzero(sig):
                    dt=pd.Timestamp(f.index[i])
                    if dt<start or dt>end or i>=len(df)-1:continue
                    hist=df.iloc[:i+1]
                    regime,_=regime_from_index(hist)
                    safe,_,_=safety({},hist)
                    score,parts=_row_score(f,i,s,regime,safe)
                    if score<int(threshold):continue
                    entry_i=i+1; entry=float(df.close.iloc[entry_i])
                    if not np.isfinite(entry) or entry<=0:continue
                    stop=entry*.93;target=entry+3*(entry-stop);risk=entry-stop
                    last=min(len(df)-1,entry_i+60);outcome='TIMEOUT';exit_price=float(df.close.iloc[last]);held=last-entry_i
                    max_high=entry;min_low=entry
                    for j in range(entry_i,last+1):
                        bar=df.iloc[j];max_high=max(max_high,float(bar.high));min_low=min(min_low,float(bar.low))
                        if bar.low<=stop:
                            outcome='LOSS';exit_price=stop;held=j-entry_i;break
                        if bar.high>=target:
                            outcome='WIN';exit_price=target;held=j-entry_i;break
                    gross_pct=(exit_price/entry-1)*100
                    return_pct=gross_pct-BT_COST_PCT
                    r_mult=return_pct/((risk/entry)*100) if risk>0 else 0
                    mfe=(max_high/entry-1)*100;mae=(min_low/entry-1)*100
                    rows.append({
                        'Date':dt.date(),'Ticker':str(ticker).replace('.NS',''),'Strategy':f'S{s}',
                        'Entry Date':df.index[entry_i].date(),'Exit Date':df.index[entry_i+held].date(),
                        'Score':int(score),'≥85 Gate':bool(score>=85),'Entry':round(entry,2),'SL':round(stop,2),'Target':round(target,2),
                        'Exit':round(exit_price,2),'Outcome':outcome,'Return %':round(return_pct,2),'R':round(float(r_mult),2),
                        'Holding Bars':int(held),'MFE %':round(mfe,2),'MAE %':round(mae,2),
                        'Strategy Score':parts.get('Strategy',0),'HTF':parts.get('HTF Demand',0),'Footprint':parts.get('Footprint',0),
                        'Trend':parts.get('Trend',0),'Entry Quality':parts.get('Entry Quality',0),'Relative Strength':parts.get('Relative Strength',0),
                        'Regime':regime,'Safety':safe
                    })
        except Exception:
            continue
    return pd.DataFrame(rows)

def run_local_backtest(tickers,start_date,end_date,threshold=85):
    # HARD GUARANTEE: this function contains no Dhan/data-download call.
    # It runs on whatever LOCAL historical data is currently available.
    # Missing symbols are reported by the UI and never trigger a Dhan request.
    status=local_backtest_status(tickers,start_date,end_date)
    if status.empty:
        raise RuntimeError('NO_LOCAL_DATA')
    data=load_local_backtest_data(tickers,start_date,end_date)
    if not data:
        raise RuntimeError('NO_LOCAL_DATA')
    return _professional_bt(data,[1,2,3,4],threshold,start_date,end_date)

def _bt_period(period):
    days={'6 Months':183,'1 Year':365,'2 Years':730,'3 Years':1095}
    end=last_expected_nse_session(); return end-timedelta(days=days[period]),end

def _fast_score_learning_backtest(data, strategies, threshold=85):
    rows = []
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=2)

    for ticker, df in data.items():
        if df is None or len(df) < 320:
            continue
        try:
            df = df.sort_index()
            f = features_fast(str(ticker), df)
            if f.empty:
                continue

            # Market regime is evaluated once at each candidate using only data
            # known up to the candidate date. To keep execution sharp, use the
            # precomputed daily regime columns where possible.
            for s in strategies:
                sig = strategy_signal(f, s).fillna(False).to_numpy()
                idxs = np.flatnonzero(sig)

                for i in idxs:
                    dt = pd.Timestamp(f.index[i])
                    if dt < start or i >= len(f)-1:
                        continue

                    hist = f.iloc[:i+1]
                    regime, _ = regime_from_index(hist)
                    safe, _, _ = safety({}, df.iloc[:i+1])
                    score, parts = _row_score(f, i, s, regime, safe)

                    # IMPORTANT: keep every complete-rule historical signal for learning.
                    # The threshold is a forward-test gate/ranking filter, not a historical
                    # data filter. This prevents survivorship-by-score in our research set.
                    entry_i = i + 1
                    entry = float(df.close.iloc[entry_i])
                    stop = entry * 0.93
                    target = entry + 3 * (entry-stop)

                    outcome, exit_price, holding = _fast_trade_outcome(
                        df, entry_i, stop, target
                    )
                    result_r = (exit_price-entry) / (entry-stop)

                    rows.append({
                        "Date": dt.date(),
                        "Ticker": str(ticker).replace(".NS",""),
                        "Strategy": f"S{s}",
                        "Score": score,
                        "≥85 Gate": bool(score >= threshold),
                        "Entry": round(entry,2),
                        "SL": round(stop,2),
                        "Target": round(target,2),
                        "Outcome": outcome,
                        "R": round(float(result_r),2),
                        "Holding Bars": holding,
                        "Strategy Score": parts["Strategy"],
                        "HTF": parts["HTF Demand"],
                        "Footprint": parts["Footprint"],
                        "Entry Quality": parts["Entry Quality"],
                        "Relative Strength": parts["Relative Strength"],
                        "Regime": regime,
                        "Safety": safe
                    })
        except Exception:
            continue

    return pd.DataFrame(rows)

def _learn_from_backtest(bt):
    """Persist completed backtest observations for long-term learning."""
    if bt is None or bt.empty:return 0
    ensure_learning_tables();n=0;con=_db()
    try:
        for _,r in bt.iterrows():
            try:
                before=con.total_changes
                con.execute("""INSERT INTO learning_observations(
                    created_at,market,symbol,strategy,signal_time,score,regime,htf,footprint,
                    strategy_score,entry_quality,relative_strength,safety_score,entry,exit_price,
                    result_r,outcome,holding_minutes,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    datetime.now().isoformat(timespec='seconds'),'INDIA',str(r.get('Ticker','')),str(r.get('Strategy','')),
                    str(r.get('Date','')),float(r.get('Score',np.nan)),str(r.get('Regime','')),float(r.get('HTF',np.nan)),
                    float(r.get('Footprint',np.nan)),float(r.get('Strategy Score',np.nan)),float(r.get('Entry Quality',np.nan)),
                    float(r.get('Relative Strength',np.nan)),float(r.get('Safety',np.nan)),float(r.get('Entry',np.nan)),
                    float(r.get('Exit',np.nan)),float(r.get('R',np.nan)),str(r.get('Outcome','')),
                    float(r.get('Holding Bars',0))*390.0,'backtest'))
                n += 1 if con.total_changes>before else 0
            except Exception:continue
        con.commit()
    finally:con.close()
    return n

def adaptive_edge_table(market="INDIA"):
    q = learning_snapshot(market)
    if q.empty:
        return pd.DataFrame()

    # Empirical-Bayes style shrinkage toward 50% / 0R for small samples.
    rows = []
    for (strategy, band), g in q.assign(
        ScoreBand=pd.cut(
            q.score, bins=[-np.inf,84,89,94,np.inf],
            labels=["<85","85-89","90-94","95-100"]
        )
    ).groupby(["strategy","ScoreBand"], observed=True):
        n = len(g)
        wins = int((g.result_r > 0).sum())
        alpha, beta = 2.0, 2.0
        shrunk_win = (wins + alpha) / (n + alpha + beta)
        shrink_r = (g.result_r.mean() * n) / max(n + 10, 1)
        rows.append({
            "Strategy": strategy,
            "Score Band": str(band),
            "Samples": n,
            "Win % (shrunk)": round(shrunk_win*100,1),
            "Avg R (shrunk)": round(shrink_r,3)
        })
    return pd.DataFrame(rows).sort_values(
        ["Strategy","Score Band"]
    )

def current_candidate_edge(market, strategy, score):
    q = adaptive_edge_table(market)
    if q.empty:
        return 0.0, "NO LEARNING DATA"

    band = "85-89" if 85 <= score <= 89 else "90-94" if score <= 94 else "95-100" if score >= 95 else "<85"
    row = q[(q.Strategy == strategy) & (q["Score Band"] == band)]
    if row.empty or int(row.iloc[0]["Samples"]) < 20:
        return 0.0, "INSUFFICIENT SAMPLE"
    r = float(row.iloc[0]["Avg R (shrunk)"])
    conf = "HIGH" if int(row.iloc[0]["Samples"]) >= 100 else "MEDIUM"
    return r, conf


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

# ========================= FINAL RESEARCH ENGINES =========================
def s4_entry_plan(d,i):
    """Research-only S4 timing plan; uses only bars up to i."""
    if d is None or len(d)<80 or i<40 or i>=len(d):
        return {"State":"INSUFFICIENT DATA"}
    x=d.iloc[:i+1].copy()
    e20=float(ema(x.close,20).iloc[-1]); e50=float(ema(x.close,50).iloc[-1]); e200=float(ema(x.close,200).iloc[-1])
    swing_high=float(x.high.iloc[-60:].max())
    impulse_low=float(x.low.iloc[-60:-20].min()) if len(x)>=60 else float(x.low.iloc[:-20].min())
    close=float(x.close.iloc[-1]); high=float(x.high.iloc[-1]); low=float(x.low.iloc[-1])
    impulse=max(swing_high-impulse_low,1e-9)
    retr=(swing_high-close)/impulse
    vol20=float(sma(x.volume,20).iloc[-1]) if pd.notna(sma(x.volume,20).iloc[-1]) else np.nan
    relvol=float(x.volume.iloc[-1]/vol20) if np.isfinite(vol20) and vol20>0 else 0
    prior_high=float(x.high.iloc[-2])
    prior_low=float(x.low.iloc[-20:-1].min())
    reclaim=close>e20 and float(x.close.iloc[-2])<=float(ema(x.close,20).iloc[-2])
    higher_high=close>prior_high
    trend=(close>e50>e200)
    in_zone=(0.382<=retr<=0.618)
    pullback_low=float(x.low.iloc[-10:].min())
    stop=min(pullback_low,e20*0.98)
    # Prefer prior swing as first target; require at least 2.5R before a new high.
    risk=max(close-stop,1e-9)
    target1=swing_high
    rr1=(target1-close)/risk
    target3=close+3*risk
    confirmation=(trend and in_zone and (reclaim or higher_high) and relvol>=1.2)
    state="BUY-TRIGGER" if confirmation and rr1>=2.5 else "WATCH" if trend and in_zone else "WAIT"
    return {
        "State":state,"Retracement %":round(retr*100,1),"Entry":round(close,2),
        "Stop":round(stop,2),"Swing Target":round(target1,2),"3R Target":round(target3,2),
        "RR to Swing":round(rr1,2),"RelVol":round(relvol,2),
        "Trend OK":trend,"Reclaim":bool(reclaim),"Higher High":bool(higher_high),
    }

def _s4_recovery_event(d,i):
    if i<80 or i>=len(d)-2:return None
    close=d.close; high=d.high; low=d.low; vol=d.volume
    p0=max(0,i-80); p1=max(p0,i-30)
    prior_low=float(low.iloc[p0:p1].min()); prior_high=float(high.iloc[p0:p1].max())
    base=d.iloc[max(0,i-20):i+1]
    if base.empty or prior_low<=0:return None
    impulse=prior_high/prior_low-1
    base_range=(float(base.high.max())/float(base.low.min())-1) if float(base.low.min())>0 else 9
    peak=float(d.high.iloc[max(0,i-40):i].max())
    trough=float(d.low.iloc[max(0,i-20):i].min())
    retr=(peak-trough)/max(peak-float(d.low.iloc[max(0,i-60):i].min()),1e-9) if peak>0 else 1
    vol_base=float(base.volume.mean()); vol_prior=float(d.volume.iloc[max(0,i-60):max(0,i-20)].mean())
    compression=vol_base/vol_prior if vol_prior>0 else 1
    ema20v=float(ema(close,20).iloc[i])
    reclaim=close.iloc[i]>ema20v and close.iloc[i-1]<=ema20v if i>0 else False
    hh=close.iloc[i]>float(high.iloc[max(0,i-20):i].max()) if i>=20 else False
    relvol=float(vol.iloc[i]/sma(vol,20).iloc[i]) if pd.notna(sma(vol,20).iloc[i]) else 0
    score=0
    score+=20 if impulse>=0.40 else 15 if impulse>=0.30 else 10 if impulse>=0.20 else 0
    score+=20 if base_range<=0.12 else 14 if base_range<=0.18 else 7 if base_range<=0.25 else 0
    score+=15 if 0.20<=retr<=0.60 else 8 if retr<=0.75 else 0
    score+=15 if compression<=0.65 else 8 if compression<=0.85 else 0
    score+=15 if reclaim else 0
    score+=10 if hh else 0
    score+=5 if relvol>=1.5 else 3 if relvol>=1.2 else 0
    return {"Score":int(score),"Impulse %":round(impulse*100,1),"Base Range %":round(base_range*100,1),"Retracement %":round(retr*100,1),"Base Vol Ratio":round(compression,2),"RelVol":round(relvol,2),"Reclaim":bool(reclaim),"Higher High":bool(hh)}

def study_s4_recovery_walkforward(data,start_date,end_date,min_score=70):
    rows=[]; start=pd.Timestamp(start_date); end=pd.Timestamp(end_date)
    for ticker,d in data.items():
        if d is None or len(d)<180:continue
        d=d.sort_index(); f=features_fast(str(ticker),d)
        # Candidate event is evaluated at close i; entry is next bar open/close proxy.
        for i in range(80,len(d)-30):
            dt=d.index[i]
            if dt<start or dt>end:continue
            ev=_s4_recovery_event(d,i)
            if not ev or ev["Score"]<min_score or not ev["Reclaim"] or not ev["Higher High"]:continue
            entry=float(d.close.iloc[i]); risk=entry*0.07; stop=entry-risk; target=entry+3*risk
            exit_idx=min(len(d)-1,i+60); outcome="TIMEOUT"; exitp=float(d.close.iloc[exit_idx]); held=exit_idx-i
            for j in range(i+1,exit_idx+1):
                bar=d.iloc[j]
                if bar.low<=stop: outcome="LOSS"; exitp=stop; held=j-i; break
                if bar.high>=target: outcome="WIN"; exitp=target; held=j-i; break
            r=(exitp-entry)/risk
            rows.append({"Date":dt.date(),"Ticker":str(ticker).replace('.NS',''),"Study":"S4 Recovery","Score":ev["Score"],**ev,"Outcome":outcome,"R":round(r,2),"Holding Bars":held})
    return pd.DataFrame(rows)

def research_metrics(df):
    if df.empty:return {"trades":0,"win_rate":0,"avg_r":0,"profit_factor":0}
    wins=df[df.R>0].R; losses=df[df.R<=0].R
    gp=float(wins.sum()); gl=abs(float(losses.sum()))
    return {"trades":len(df),"win_rate":float((df.R>0).mean()*100),"avg_r":float(df.R.mean()),"profit_factor":gp/gl if gl>0 else (99.99 if gp>0 else 0)}

def portfolio_from_backtest(bt,capital,risk_pct,slots):
    x=bt.copy()
    if x.empty:return {"Starting Capital":capital,"Final Capital":capital,"ROI %":0,"Max DD %":0,"Trades":0}
    x=x.sort_values("Date"); equity=float(capital); peak=equity; maxdd=0; taken=0
    # Conservative fixed-fraction compounding using realized R; no overlapping-capital optimism.
    for r in x.itertuples():
        risk_cash=equity*float(risk_pct)/100
        equity += risk_cash*float(r.R)
        taken+=1; peak=max(peak,equity); maxdd=max(maxdd,(peak-equity)/peak*100 if peak else 0)
        if equity<=0:equity=0;break
    return {"Starting Capital":round(capital,2),"Final Capital":round(equity,2),"Profit ₹":round(equity-capital,2),"ROI %":round((equity/capital-1)*100,2),"Max DD %":round(maxdd,2),"Trades":taken,"Risk/Trade %":risk_pct,"Slots (display)":slots}

# ========================= UI =========================

st.title("🧠 Adaptive Trading Intelligence Lab — Professional Final")
st.caption("Dhan-first • persistent local data • exact S1–S4 • no-lookahead walk-forward • adaptive learning • S4 recovery research • fundamentals/news enrichment")

tabs=st.tabs([
    "🏠 Dashboard",
    "📡 Daily Scanner",
    "📊 Backtest",
    "🔬 Forward Testing",
    "🧠 Market Learning",
    "💎 Long-Term Fundamentals",
    "🏢 Small/Micro Safety",
    "🧪 Custom Strategy",
    "💾 Dhan Data Manager",
    "🧪 S4 Recovery Study",
    "🧬 Research & Risk Control",
    "⚙️ System Diagnostics"
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

    st.subheader("⚡ Continuous Scan Mode")
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Historical cache", "ON")
    cc2.metric("Feature cache", "ON")
    cc3.metric("Live layer", "Dhan WebSocket")
    st.caption(
        "Daily/weekly/monthly strategy state is cached. The live layer tracks only candidates and "
        "re-ranks them from the Dhan feed instead of rebuilding the entire market every minute."
    )


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

            universe = set()
            for u in universes:
                universe.update(index_universe(u))
            tickers = sorted(universe)

            # Scanner is LOCAL-ONLY. Data acquisition belongs exclusively to the
            # Data Manager / explicit sync action. This prevents every scan from
            # becoming another Dhan historical download.
            t0 = time.perf_counter()
            data = {}
            con=_db()
            try:
                for ticker in tickers:
                    clean=str(ticker).upper().replace(".NS","")
                    d=_read_cache(con,clean,date.today()-timedelta(days=1000),date.today())
                    if d is not None and len(d)>=260:
                        data[ticker]=d
            finally:
                con.close()
            scan_load_seconds = time.perf_counter() - t0

            if not data:
                st.error("Local dataset is empty/incomplete. Use Data Manager → SYNC ONLY MISSING DATA once, then scan again. Scanner itself never downloads historical data.")
                st.stop()

            proxy = max(data.values(), key=len)
            regime, regime_score = regime_from_index(proxy)

            if not data:
                st.error(
                    "Dhan returned no price data for the selected universe. "
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

                f = features_fast(str(ticker), df)
                # Keep the latest row even when some long-term indicators are unavailable.
                # Individual strategy conditions will evaluate NaNs as False.
                f = f.replace([np.inf, -np.inf], np.nan)
                if len(f) < 260:
                    bar.progress((n+1)/max(1,len(data)))
                    continue

                stats["usable"] += 1
                # Do NOT fetch fundamentals for the whole universe. Price/volume safety is
                # computed locally; fundamental/news enrichment is candidate-only.
                info={}
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

                    edge_r, learn_conf = current_candidate_edge(
                        "INDIA", f"S{s}", float(score)
                    )
                    learned_rank = float(np.clip(score + edge_r * 2.0, 0, 100))
                    rows.append({
                        "Score": score,
                        "Learned Rank": round(learned_rank, 2),
                        "Historical Edge R": round(edge_r, 3),
                        "Learning Confidence": learn_conf,
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

            # Persist every scanner-qualified signal; mark only the configured
            # forward-test gate as selected. This survives Streamlit reruns.
            if not result.empty:
                con=_db()
                try:
                    now=datetime.now().isoformat(timespec="seconds")
                    for _,r in result.iterrows():
                        sym=str(r.get("Ticker","")).upper().replace(".NS","")
                        strat=str(r.get("Strategy","")).upper()
                        signal_date=str(date.today())
                        signal_key=f"{signal_date}|{sym}|{strat}"
                        con.execute("""INSERT OR REPLACE INTO scanner_signals(
                            signal_key,created_at,signal_date,symbol,strategy,score,learned_rank,
                            historical_edge_r,learning_confidence,regime,safety_status,safety_score,
                            entry,stop,target,rr,rsi,relvol,htf_score,footprint_score,
                            strategy_score,entry_quality,relative_strength,safety_flags,selected_for_forward
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                            signal_key,now,signal_date,sym,strat,
                            float(r.get("Score",0)),float(r.get("Learned Rank",0)),
                            float(r.get("Historical Edge R",0)),str(r.get("Learning Confidence","")),
                            str(r.get("Regime","")),str(r.get("Safety","")),
                            float(r.get("Safety Score",0)),float(r.get("Entry",np.nan)),
                            float(r.get("SL 7%",r.get("SL",np.nan))),
                            float(r.get("Target 3R",r.get("Target",np.nan))),
                            3.0,float(r.get("RSI",np.nan)),float(r.get("RelVol",np.nan)),
                            float(r.get("HTF Score",r.get("HTF Demand",0))),
                            float(r.get("Footprint Score",r.get("Footprint",0))),
                            float(r.get("Strategy Score",0)),float(r.get("Entry Quality",0)),
                            float(r.get("Relative Strength",0)),str(r.get("Safety Flags","")),
                            int(float(r.get("Score",0))>=min_score)
                        ))
                    con.commit()
                finally:
                    con.close()

                # Convert selected signals into durable forward-test records.
                added=add_forward_candidates(
                    result[result["Score"]>=min_score].copy()
                )
                st.session_state["forward_last_added"]=int(added)

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
                        f = features_fast(str(ticker), df)
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
                        f = features_fast(str(ticker), df)
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

def add_forward_candidates(candidates):
    """Persist scanner-selected candidates into SQLite so refresh/restart does not erase them."""
    if candidates is None or len(candidates)==0:
        return 0
    con=_db(); added=0
    try:
        today=str(date.today())
        for _,r in candidates.iterrows():
            symbol=str(r.get("Ticker","")).upper().replace(".NS","")
            strategy=str(r.get("Strategy","")).upper()
            score=float(r.get("Score",0))
            if not symbol or strategy not in {"S1","S2","S3","S4"}:
                continue
            entry=float(r.get("Entry",np.nan)); sl=float(r.get("SL",r.get("SL 7%",np.nan)))
            target=float(r.get("Target",r.get("Target 3R",np.nan)))
            if not np.isfinite(entry) or entry<=0 or not np.isfinite(sl) or not np.isfinite(target):
                continue
            exists=con.execute(
                """SELECT id FROM forward_tests
                   WHERE symbol=? AND strategy=? AND signal_date=? LIMIT 1""",
                (symbol,strategy,today)
            ).fetchone()
            if exists:
                continue
            now=datetime.now().isoformat(timespec="seconds")
            snapshot={k:r.get(k,None) for k in r.index}
            cur=con.execute("""INSERT INTO forward_tests(
                created_at,symbol,strategy,score,regime,entry,sl,target,status,ltp,mfe,mae,
                exit_price,result_r,updated_at,signal_date,signal_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                now,symbol,strategy,score,str(r.get("Regime","")).strip(),
                entry,sl,target,"ACTIVE",entry,0.0,0.0,None,None,now,
                today,json.dumps(snapshot,default=str,allow_nan=True)
            ))
            fid=int(cur.lastrowid); added+=1
            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",(
                fid,now,today,entry,entry,entry,0.0,0.0,0.0,"ACTIVE"
            ))
        con.commit()
    finally:
        con.close()
    return added

def refresh_forward_positions():
    """Update active forward records using only locally stored daily candles."""
    con=_db()
    try:
        active=pd.read_sql_query(
            """SELECT id,created_at,signal_date,symbol,strategy,score,regime,entry,sl,target
               FROM forward_tests WHERE status='ACTIVE' ORDER BY created_at DESC""",con
        )
    finally: con.close()
    if active.empty:return 0

    today=last_expected_nse_session(); updates=0
    con=_db()
    try:
        for r in active.itertuples():
            s=str(r.symbol).upper().replace(".NS","")
            signal_date=pd.to_datetime(r.signal_date or r.created_at).date()
            d=_read_cache(con,s,signal_date,today)
            if d is None or d.empty: continue

            entry=float(r.entry);stop=float(r.sl);target=float(r.target)
            last_dt=pd.Timestamp(d.index[-1]).date(); close=float(d.close.iloc[-1])
            mfe=max(0.0,(float(d.high.max())/entry-1)*100)
            mae=min(0.0,(float(d.low.min())/entry-1)*100)
            ret=(close/entry-1)*100; held=max(0,len(d)-1)
            status="ACTIVE";exitp=None;result_r=None;closed_at=None

            for _,bar in d.iterrows():
                if float(bar.low)<=stop:
                    status="STOP";exitp=stop;result_r=(exitp-entry)/(entry-stop);closed_at=datetime.now().isoformat(timespec="seconds");break
                if float(bar.high)>=target:
                    status="TARGET";exitp=target;result_r=(exitp-entry)/(entry-stop);closed_at=datetime.now().isoformat(timespec="seconds");break

            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",(
                int(r.id),datetime.now().isoformat(timespec="seconds"),str(last_dt),
                close,float(d.high.iloc[-1]),float(d.low.iloc[-1]),ret,mfe,mae,status
            ))

            if status!="ACTIVE":
                con.execute("""UPDATE forward_tests
                    SET status=?,ltp=?,mfe=?,mae=?,exit_price=?,result_r=?,updated_at=?
                    WHERE id=?""",
                    (status,exitp,mfe,mae,exitp,result_r,closed_at,int(r.id)))
                con.execute("""INSERT OR IGNORE INTO forward_results(
                    forward_id,symbol,strategy,signal_date,entry,exit_price,result_r,
                    return_pct,outcome,holding_bars,mfe_pct,mae_pct,regime,score,closed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    int(r.id),s,str(r.strategy),str(signal_date),entry,exitp,result_r,
                    (exitp/entry-1)*100,status,held,mfe,mae,str(r.regime),float(r.score),closed_at
                ))
            else:
                con.execute("""UPDATE forward_tests SET ltp=?,mfe=?,mae=?,updated_at=? WHERE id=?""",
                            (close,mfe,mae,datetime.now().isoformat(timespec="seconds"),int(r.id)))
            updates+=1
        con.commit()
    finally: con.close()
    return updates

def forward_summary_table():
    """Persistent strategy scorecard from forward-test records."""
    con=_db()
    try:
        q=pd.read_sql_query(
            """SELECT strategy AS Strategy,
                      COUNT(*) AS Records,
                      SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) AS Open,
                      SUM(CASE WHEN status IN ('TARGET','STOP','EXIT','EXPIRED') THEN 1 ELSE 0 END) AS Closed,
                      SUM(CASE WHEN result_r>0 THEN 1 ELSE 0 END) AS Wins,
                      SUM(CASE WHEN result_r<=0 AND result_r IS NOT NULL THEN 1 ELSE 0 END) AS Losses,
                      AVG(result_r) AS AvgR,
                      SUM(result_r) AS TotalR,
                      AVG(CASE WHEN result_r IS NOT NULL THEN (result_r*100.0/3.0) END) AS AvgROIProxy,
                      AVG(mfe) AS AvgMFE,
                      AVG(mae) AS AvgMAE
               FROM forward_tests GROUP BY strategy ORDER BY AvgR DESC""",con
        )
    finally:
        con.close()
    if q.empty:return q
    q["Win %"]=np.where((q["Wins"]+q["Losses"])>0,q["Wins"]/(q["Wins"]+q["Losses"])*100,np.nan)
    q["Status"]=np.where(q["Closed"]<3,"BUILDING SAMPLE",
                         np.where(q["AvgR"]>0.75,"STRONG",
                                  np.where(q["AvgR"]>0.2,"POSITIVE",
                                           np.where(q["AvgR"]>-0.1,"NEUTRAL","WEAK"))))
    q["AvgR"]=q["AvgR"].round(3);q["TotalR"]=q["TotalR"].round(2)
    q["Win %"]=q["Win %"].round(1);q["AvgMFE"]=q["AvgMFE"].round(2);q["AvgMAE"]=q["AvgMAE"].round(2)
    return q


def crypto_learning_summary(symbol=None):
    """Summarise persisted crypto research observations; safe when empty."""
    _ensure_research_tables()
    con=_db()
    try:
        if symbol:
            q=pd.read_sql_query(
                "SELECT * FROM research_events WHERE market='CRYPTO' AND symbol=? ORDER BY created_at DESC",
                con,params=(str(symbol).upper(),)
            )
        else:
            q=pd.read_sql_query(
                "SELECT * FROM research_events WHERE market='CRYPTO' ORDER BY created_at DESC",
                con
            )
    finally:
        con.close()
    if q.empty:
        return pd.DataFrame()
    q["Win"]=(q["r_multiple"]>0).astype(int)
    return (q.groupby(["symbol","study"],dropna=False)
              .agg(Observations=("id","count"),WinRate=("Win","mean"),AvgR=("r_multiple","mean"),BestR=("r_multiple","max"))
              .reset_index()
              .assign(WinRate=lambda x:(x.WinRate*100).round(1),AvgR=lambda x:x.AvgR.round(3),BestR=lambda x:x.BestR.round(3)))

def _two_year_backtest(data, strategies, threshold=85):
    return _fast_score_learning_backtest(data, strategies, threshold)

def _learning_summary(bt):
    if bt.empty:return pd.DataFrame()
    x=bt.copy();x["Win"]=(x.Outcome=="WIN").astype(int)
    y=x.groupby("Strategy").agg(Signals=("Ticker","count"),Wins=("Win","sum"),
        WinRate=("Win","mean"),AvgR=("R","mean"),BestScore=("Score","max")).reset_index()
    y["WinRate"]=(y.WinRate*100).round(1); y["AvgR"]=y.AvgR.round(2)
    return y

with tabs[2]:
    st.subheader("📊 Professional Walk-Forward Backtest")
    st.caption("Dhan is used ONLY by the explicit Data Manager sync. Backtest reads the same SQLite candle store and makes ZERO Dhan/API calls.")
    c1,c2,c3=st.columns(3)
    period=c1.selectbox("Time Span",["6 Months","1 Year","2 Years","3 Years"],index=0,key="bt_period_final")
    threshold=c2.number_input("Score threshold",0,100,85,1,key="bt_threshold_final")
    universes=c3.multiselect("Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],default=["Nifty 500"],key="bt_universes_final")
    start_date,end_date=_bt_period(period);data_start=_bt_required_data_start(start_date)
    tickers=sorted(set(sum([index_universe(u) for u in universes],[]))) if universes else []
    st.info(f"{period} | Signal window {start_date} → {end_date} | Warm-up {data_start} → {start_date} | {len(tickers):,} stocks | S1–S4 | local SQLite only | forward gate ≥{threshold}")

    st.markdown("### 1️⃣ Local Dataset")
    status=local_backtest_status(tickers,start_date,end_date) if tickers else pd.DataFrame()
    ready=int(status.Ready.sum()) if not status.empty else 0
    total=len(status)
    a,b,c,d=st.columns(4)
    a.metric("Stocks ready",f"{ready:,}")
    b.metric("Missing",f"{total-ready:,}")
    a.caption("Only locally cached candles are counted.")
    c.metric("Local bars",f"{int(status.Bars.sum()):,}" if not status.empty else "0")
    d.metric("Warm-up",f"{BT_WARMUP_DAYS} days")

    if total and ready==total:
        st.success("✅ Local SQLite dataset ready. Backtest will make ZERO Dhan/API calls.")
    elif total:
        st.warning(
            f"⚠️ {total-ready:,} stocks are missing required local history. "
            f"The backtest button remains available and will run ONLY on the {ready:,} stocks already cached."
        )
    else:
        st.error("No local universe data is available.")

    st.markdown("### 2️⃣ Run Backtest")
    st.caption(
        "🔒 HARD RULE: this button never synchronizes data and never calls Dhan. "
        "Use Data Manager → SYNC ONLY MISSING DATA when you deliberately want to acquire history."
    )

    # ALWAYS visible. Missing stocks must never hide the backtest.
    if st.button("⚡ RUN LOCAL S1–S4 BACKTEST",type="primary",key="run_local_bt"):
        t0=time.perf_counter()
        try:
            with st.spinner(f"Replaying local data for {ready:,}/{total:,} available stocks..."):
                bt=run_local_backtest(tickers,start_date,end_date,int(threshold))
            elapsed=time.perf_counter()-t0
            _persist_backtest(bt,period,start_date,end_date,int(threshold),len(tickers),elapsed)
            learned=_learn_from_backtest(bt)
            st.session_state["backtest_final"]=bt
            st.session_state["backtest_learning_added"]=learned
            st.success(
                f"Completed locally in {elapsed:.2f}s — {len(bt):,} qualifying trades; "
                f"{learned:,} learning observations saved. Dhan/API calls: 0."
            )
        except Exception as ex:
            st.error(f"Local backtest error: {ex}")

    bt=st.session_state.get("backtest_final",pd.DataFrame())
    if bt.empty:
        bt,_run=_load_latest_backtest()
        if not bt.empty:st.session_state["backtest_final"]=bt
    if bt.empty:
        st.info("No completed backtest is stored yet. Build the dataset and run the backtest once.")
    else:
        st.subheader("🏆 Historical Learning Dataset")
        a,b,c,d,e=st.columns(5)
        a.metric("Trades",len(bt));b.metric("S1",int((bt.Strategy=='S1').sum()));c.metric("S2",int((bt.Strategy=='S2').sum()));d.metric("S3",int((bt.Strategy=='S3').sum()));e.metric("S4",int((bt.Strategy=='S4').sum()))
        st.dataframe(bt.sort_values(["Score","Date"],ascending=[False,False]),use_container_width=True,hide_index=True)

        st.subheader("📈 Strategy Performance / ROI / Risk")
        perf=[]
        for strat,g in bt.groupby('Strategy'):
            wins=g[g['R']>0];loss=g[g['R']<=0];grossw=float(wins['R'].sum());grossl=abs(float(loss['R'].sum()))
            pf=grossw/grossl if grossl>0 else (99.99 if grossw>0 else 0)
            perf.append({'Strategy':strat,'Trades':len(g),'Win %':round((g.R>0).mean()*100,1),'Avg R':round(g.R.mean(),3),'Total R':round(g.R.sum(),2),'Profit Factor':round(pf,2),'Avg Return %':round(g['Return %'].mean(),2),'Avg MFE %':round(g['MFE %'].mean(),2),'Avg MAE %':round(g['MAE %'].mean(),2),'Best Score':int(g.Score.max())})
        st.dataframe(pd.DataFrame(perf).sort_values('Avg R',ascending=False),use_container_width=True,hide_index=True)

        st.subheader("💰 Capital / ROI Simulation")
        pc1,pc2,pc3=st.columns(3);capital=pc1.number_input("Starting capital ₹",10000,100000000,100000,10000,key='bt_capital');risk_pct=pc2.number_input("Risk per trade %",0.1,5.0,1.0,0.1,key='bt_risk');slots=pc3.number_input("Capital slots",1,50,5,1,key='bt_slots')
        roi=portfolio_from_backtest(bt,float(capital),float(risk_pct),int(slots));st.dataframe(pd.DataFrame([roi]),use_container_width=True,hide_index=True)

        st.subheader("🎯 Score Learning")
        bands=pd.cut(bt.Score,[84,89,94,100],labels=["85–89","90–94","95–100"],include_lowest=True);bx=bt.assign(Band=bands,Win=(bt.Outcome.str.upper()=='WIN').astype(int))
        learn=bx.groupby('Band',observed=True).agg(Signals=('Ticker','count'),Wins=('Win','sum'),WinRate=('Win','mean'),AvgR=('R','mean'),TotalR=('R','sum'),AvgReturn=('Return %','mean'),AvgMFE=('MFE %','mean'),AvgMAE=('MAE %','mean')).reset_index();learn['WinRate']=(learn.WinRate*100).round(1);learn[['AvgR','TotalR','AvgReturn','AvgMFE','AvgMAE']]=learn[['AvgR','TotalR','AvgReturn','AvgMFE','AvgMAE']].round(2);st.dataframe(learn,use_container_width=True,hide_index=True)

        st.subheader("🧠 Marking Conditions Used")
        st.info("A row exists only when ALL mandatory rules of its strategy passed. The columns below preserve the score components used to rank the historical setup; the strategy itself is independently re-evaluated from the full rule set.")
        st.dataframe(bt[['Ticker','Date','Strategy','Score','Strategy Score','HTF','Footprint','Trend','Entry Quality','Relative Strength','Safety','Regime','Outcome','R','Return %','MFE %','MAE %','Holding Bars']].sort_values('Score',ascending=False),use_container_width=True,hide_index=True)

        st.subheader("🔎 Individual Strategy Results")
        stabs=st.tabs(['S1','S2','S3','S4'])
        for tab,ss in zip(stabs,[1,2,3,4]):
            with tab:
                sr=bt[bt.Strategy==f'S{ss}'].sort_values(['Score','Date'],ascending=[False,False])
                st.dataframe(sr,use_container_width=True,hide_index=True) if not sr.empty else st.info(f'S{ss}: no qualifying historical setups in this window.')

with tabs[3]:
    st.subheader('🔬 Forward Testing — Persistent Strategy Outcome Tracker')
    changed=refresh_forward_positions()
    st.caption("Every scanner-selected ≥gate signal is stored in SQLite with its original conditions. Refreshing the page does not clear it.")
    con=_db()
    try:
        ft=pd.read_sql_query("""SELECT id,signal_date AS Signal_Date,symbol AS Ticker,strategy AS Strategy,
            score AS Score,regime AS Regime,entry AS Entry,sl AS Stop,target AS Target,status AS Status,
            ltp AS Current_Price,mfe AS MFE_pct,mae AS MAE_pct,exit_price AS Exit,result_r AS R,
            updated_at AS Updated FROM forward_tests ORDER BY signal_date DESC,score DESC""",con)
        signals=pd.read_sql_query("""SELECT signal_date AS Date,symbol AS Ticker,strategy AS Strategy,
            score AS Score,entry AS Entry,stop AS Stop,target AS Target,rr AS RR,regime AS Regime,
            safety_status AS Safety,historical_edge_r AS Historical_Edge_R
            FROM scanner_signals WHERE selected_for_forward=1
            ORDER BY signal_date DESC,score DESC""",con)
    finally:con.close()

    if ft.empty:
        st.info("No persistent forward-test records yet. Run Daily Scanner and let the ≥85 gate create them.")
    else:
        closed=ft[ft.Status!="ACTIVE"]; wins=int((closed.R>0).sum()); losses=int((closed.R<=0).sum())
        avg_r=float(closed.R.mean()) if not closed.empty else np.nan
        a,b,c,d,e=st.columns(5)
        a.metric("Persistent signals",len(ft)); b.metric("Open",int((ft.Status=="ACTIVE").sum()))
        c.metric("Wins",wins); d.metric("Losses",losses); e.metric("Avg R",f"{avg_r:.2f}" if np.isfinite(avg_r) else "—")
        st.subheader("📋 Forward Positions")
        st.dataframe(ft,use_container_width=True,hide_index=True)
        st.subheader("🏆 Strategy Performance Scorecard")
        fs=forward_summary_table()
        if not fs.empty: st.dataframe(fs,use_container_width=True,hide_index=True)
        else: st.info("Waiting for completed forward-test outcomes.")
        st.subheader("🧠 What is being learned")
        st.write("The system tracks strategy, score, regime, entry/stop/target, MFE/MAE, R and final outcome. This is the permanent evidence base for future strategy ranking.")

    st.subheader("🗃️ Persisted Scanner Signals")
    if signals.empty: st.info("No scanner signals saved for the forward-test gate yet.")
    else:
        st.dataframe(signals.head(500),use_container_width=True,hide_index=True)
        st.download_button("⬇️ Download forward signal history",signals.to_csv(index=False).encode(),"forward_signal_history.csv","text/csv",key="download_forward_history")

with tabs[4]:
    st.subheader("🧠 Adaptive Market Learning")
    fwd=forward_summary_table()
    if not fwd.empty:
        st.subheader("🏆 Forward Strategy Leaderboard")
        st.dataframe(fwd,use_container_width=True,hide_index=True)

    bt=st.session_state.get('backtest_final',pd.DataFrame())
    if bt.empty:
        bt,_run=_load_latest_backtest()
        if not bt.empty:st.session_state['backtest_final']=bt
    learn_db=learning_snapshot('INDIA')
    if bt.empty and learn_db.empty:
        st.info('No learning observations yet. Run a backtest or complete forward-test trades first.')
    else:
        if not bt.empty:
            st.subheader('📊 Historical Evidence')
            st.dataframe(_learning_summary(bt),use_container_width=True,hide_index=True)
            rows=[]
            for c in ['HTF','Footprint','Strategy Score','Safety','Entry Quality','Relative Strength']:
                if c in bt.columns:
                    med=bt[c].median();hi=bt[bt[c]>=med];lo=bt[bt[c]<med]
                    rows.append({'Component':c,'High Samples':len(hi),'High Avg R':round(float(hi.R.mean()),3) if len(hi) else 0,'Low Samples':len(lo),'Low Avg R':round(float(lo.R.mean()),3) if len(lo) else 0,'High Win %':round(float((hi.Outcome.str.upper()=='WIN').mean()*100),1) if len(hi) else 0})
            st.subheader('🔬 Marking Component Learning');st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
        st.subheader('🎯 Adaptive Score Edge')
        edge=adaptive_edge_table('INDIA')
        st.dataframe(edge,use_container_width=True,hide_index=True) if not edge.empty else st.info('Not enough completed observations for adaptive edge estimates.')
        st.subheader('🗄️ Persistent Learning Database')
        st.metric('Completed observations',len(learn_db))
        if not learn_db.empty:
            st.dataframe(adaptive_component_weights('INDIA'),use_container_width=True,hide_index=True)
            st.dataframe(learn_db.head(500),use_container_width=True,hide_index=True)
        st.caption('Learning ranks candidates using evidence; it never changes the deterministic S1–S4 qualification rules.')

with tabs[5]:
    st.subheader("💎 Long-Term Fundamentals + News")
    st.caption("Dhan remains the primary Indian market-price source. Fundamental/news enrichment is deliberately fetched only for candidates, cached locally, and never used to weaken S1–S4 rules.")
    st.info("Twelve Data provides India fundamentals/press releases; Dhan's current API documentation exposes market data, instruments, quotes, positions and related trading/data APIs rather than a fundamental-financial-statement endpoint.")
    sym_text=st.text_input("Candidate symbols (comma separated)","RELIANCE,TCS,HDFCBANK",key="fund_symbols_final")
    if st.button("🔎 Enrich Fundamentals + News",key="fund_enrich_final"):
        rows=[]
        for sym in [x.strip().upper() for x in sym_text.split(',') if x.strip()]:
            info,ff=company_info(sym)
            items,sent,risk=news_snapshot(sym)
            score,status,flags=_fundamental_score(info)
            rows.append({"Ticker":sym,"Fundamental Score":score,"Status":status,"News Sentiment":round(sent,1),"News Risk":round(risk,1),"Flags":"; ".join(ff+flags),"News Items":len(items)})
        st.session_state["fundamental_results_final"]=pd.DataFrame(rows)
    fr=st.session_state.get("fundamental_results_final",pd.DataFrame())
    if fr.empty: st.info("Enter candidates or feed the tab from the scanner's ≥85 queue.")
    else: st.dataframe(fr.sort_values(["Fundamental Score","News Sentiment"],ascending=[False,False]),use_container_width=True,hide_index=True)

with tabs[6]:
    st.subheader("🏢 Small/Micro Safety Engine")
    st.caption("Independent risk gate. It cannot create an S1–S4 signal; it can only downgrade/reject a qualifying candidate.")
    con=_db()
    try: syms=pd.read_sql_query("SELECT DISTINCT symbol FROM forward_tests WHERE status='ACTIVE'",con)
    finally: con.close()
    if syms.empty: st.info("No active forward-test stocks yet.")
    else:
        rows=[]
        for sym in syms.symbol:
            
            con2=_db()
            try:
                d=_read_cache(con2,str(sym).upper().replace('.NS',''),date.today()-timedelta(days=180),date.today())
            finally:
                con2.close()
            if d.empty:
                d=download_prices([sym],date.today()-timedelta(days=180),date.today(),max_workers=1).get(sym,pd.DataFrame())
            info,_=company_info(sym); _,_,newsrisk=news_snapshot(sym)
            sc,status,flags=advanced_small_micro_safety(info,d,newsrisk)
            rows.append({"Stock":sym,"Safety Score":sc,"Status":status,"News Risk":round(newsrisk,1),"Flags":", ".join(flags)})
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
    st.caption("Dhan is the primary Indian-equity market-data source. Historical candles are cached locally; backtests use the local dataset after it is built.")

    # ---- Explicit, read-only Dhan health check --------------------------------
    st.markdown("### 🔌 Dhan Connection Test")
    st.caption("These tests never place an order. First prove the Dhan historical API, then prove Dhan → parser → SQLite with one stock before starting a large sync.")

    if st.button("🧪 TEST DHAN CONNECTION",type="primary",key="dhan_connection_test"):
        with st.spinner("Testing Dhan connection..."):
            diag=dhan_connection_diagnostic()

        checks=[
            ("Credentials",diag["credentials"]),
            ("Instrument master",diag["instrument_master"]),
            ("RELIANCE NSE mapping",diag["reliance_mapping"]),
            ("Authenticated LTP API",diag["ltp_api"]),
            ("Authenticated historical API",diag["historical_api"]),
        ]
        cols=st.columns(5)
        for col,(label,ok) in zip(cols,checks):
            col.metric(label,"PASS" if ok else "FAIL")

        if all(ok for _,ok in checks):
            st.success("🟢 DHAN CONNECTED — authentication, NSE mapping, LTP and historical data are working.")
        else:
            st.error("🔴 Dhan connection is not fully verified. Read the diagnostics below.")
        for msg in diag["details"]:
            st.write("•",msg)

    st.markdown("### 🧪 One-Stock Data Smoke Test")
    st.caption("This downloads only RELIANCE for a small diagnostic range and immediately verifies that candles were written to SQLite. It does NOT start the 500-stock sync.")
    smoke_days=st.selectbox("Smoke-test range",[7,30,90],index=1,key="dhan_smoke_days")
    if st.button("🔎 TEST DHAN → SQLITE (RELIANCE)",type="secondary",key="dhan_smoke_test"):
        try:
            with st.spinner("Testing Dhan historical data and SQLite write..."):
                smoke=dhan_historical_smoke_test("RELIANCE",int(smoke_days))
            st.success(f"✅ End-to-end data test passed: {smoke['http/parser_candles']:,} candles received and {smoke['saved_rows']:,} rows written/updated in SQLite.")
            q1,q2,q3,q4=st.columns(4)
            q1.metric("Security ID",smoke["security_id"])
            q2.metric("Candles received",smoke["http/parser_candles"])
            q3.metric("DB rows after",smoke["db_rows_after"])
            q4.metric("Request time",f"{smoke['request_seconds']:.2f}s")
            st.write(f"**Requested:** {smoke['requested_start']} → {smoke['requested_end']}  |  **Returned:** {smoke['sample_first']} → {smoke['sample_last']}  |  **DB:** {smoke['db_min']} → {smoke['db_max']}")
            st.write(f"**Latest RELIANCE close:** ₹{smoke['sample_close']:,.2f}")
        except Exception as ex:
            st.error(f"❌ End-to-end data test failed: {ex}")
            st.warning("Do not start the 500-stock sync until this one-stock test passes.")

    st.markdown("### 📦 Local Dataset")
    st.caption(
        "Historical acquisition is controlled ONLY from this section. "
        "Backtest and scanner never synchronize historical data. "
        f"Latest expected NSE cash-session: {last_expected_nse_session().strftime('%d-%b-%Y')}. "
        "No candle is expected on Saturday/Sunday."
    )
    sync_universe=st.selectbox(
        "Sync universe",
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        key="dm_sync_universe"
    )
    sync_days=st.selectbox(
        "Historical range to maintain",
        [730,1000,1500,2000],
        index=1,
        format_func=lambda x: f"{x} calendar days",
        key="dm_sync_days"
    )
    if st.button("🔄 SYNC ONLY MISSING DATA",type="primary",key="dm_sync_missing"):
        try:
            sync_tickers=index_universe(sync_universe)
            with st.spinner(f"Checking local ranges and downloading ONLY missing data for {len(sync_tickers):,} stocks..."):
                sync_missing_backtest_data(
                    sync_tickers,
                    last_expected_nse_session()-timedelta(days=int(sync_days)),
                    last_expected_nse_session(),
                    max_workers=5
                )
            st.success("Sync completed. Existing local candles were reused; only missing ranges were requested from Dhan.")
            if _DHAN_LAST_DATA_ERRORS:
                st.warning("Recent Dhan data errors: "+" | ".join(_DHAN_LAST_DATA_ERRORS[:8]))
            st.rerun()
        except Exception as ex:
            st.error(f"Data sync error: {ex}")

    con=_db()
    try:
        ns=con.execute("SELECT COUNT(DISTINCT symbol) FROM candles").fetchone()[0]
        nc=con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        latest=con.execute("SELECT MAX(dt) FROM candles").fetchone()[0]
    finally:
        con.close()

    a,b,c=st.columns(3)
    a.metric("Cached stocks",ns)
    b.metric("Cached candles",f"{nc:,}")
    c.metric("Latest stored candle",latest or "—")

    if ns==0:
        st.warning("⚠️ Cache is empty. Run the Dhan Connection Test first, then use SYNC ONLY MISSING DATA in this Data Manager.")
    else:
        st.success(f"🟢 Local Dhan dataset contains {ns:,} stocks and {nc:,} candles.")

    st.info(
        "Architecture: Dhan → local candle cache → local backtest. "
        "The backtest runner does not call Dhan once the required local dataset is ready. "
        "Existing candles are reused and only missing historical ranges are downloaded."
    )

    if _DHAN_LAST_DATA_ERRORS:
        st.markdown("### ⚠️ Recent Dhan data-build errors")
        st.dataframe(
            pd.DataFrame({"Error":_DHAN_LAST_DATA_ERRORS}),
            use_container_width=True,
            hide_index=True
        )

    if st.button("⛔ Stop Live WebSocket",key="stop_ws"):
        stop_persistent_live_feed()
        st.success("Dhan WebSocket stop requested.")

with tabs[9]:
    st.subheader("🧪 Strategy 4 Recovery Study + Entry Timing")
    st.markdown("### 🎯 Higher-quality S4 retracement entry")
    st.info("Research rule: do not buy merely because price reaches a retracement zone. Prefer trend + controlled pullback + reclaim/confirmation + sufficient reward-to-risk. The 38.2–61.8% zone is a heuristic, not a proven probability edge.")
    s4a,s4b,s4c,s4d=st.columns(4)
    s4a.metric("Preferred retracement","38.2–61.8%")
    s4b.metric("Minimum target","≥ 3R")
    s4c.metric("Confirmation","Reclaim + higher high")
    s4d.metric("Risk stop","Below pullback low")
    st.caption("The engine should label setups WAIT / WATCH / BUY-TRIGGER, rather than force a purchase.")

    st.caption("Research layer only — exact S4 remains unchanged. This study searches for big-move → consolidation/retracement → reclaim → higher-high structures that the strict daily EMA20-close condition can miss.")
    c1,c2,c3,c4=st.columns(4)
    s4_min_score=c1.slider("Study score",50,95,70,1,key="s4study_score")
    impulse_min=c2.slider("Minimum prior impulse",10,60,20,1,key="s4study_impulse")/100
    base_max=c3.slider("Maximum base range",8,30,18,1,key="s4study_base")/100
    retr_max=c4.slider("Maximum retracement",30,80,65,1,key="s4study_retr")/100
    st.info("We are NOT replacing S4. We are creating a separate research hypothesis and measuring whether it has positive expectancy out-of-sample before considering any rule change.")
    study_universe=st.selectbox("Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],key="s4study_universe")
    if st.button("🔬 Study S4 Recovery Pattern",type="primary",key="s4study_run"):
        try:
            tickers=index_universe(study_universe)
            data=load_local_market_dataset(tuple(tickers),date.today()-timedelta(days=1000),date.today(),160)
            # Use custom impulse/base settings while retaining the research-only definition.
            rows=[]
            for ticker,d in data.items():
                if len(d)<160: continue
                sig=strategy4_recovery_signal(d,min_impulse=impulse_min,max_base_range=base_max,max_retracement=retr_max).iloc[-1]
                score,parts=_s4_recovery_quality(d)
                if bool(sig) and score>=s4_min_score:
                    rows.append({"Ticker":str(ticker).replace(".NS",""),"Study Score":score,"Signal":"RECOVERY → HIGHER HIGH",**parts})
            res=pd.DataFrame(rows)
            if res.empty:
                st.warning("No recovery candidates found with the current research thresholds.")
            else:
                res=res.sort_values(["Study Score","RelVol"],ascending=[False,False])
                st.success(f"Found {len(res)} research candidates. These are NOT S4 exact signals.")
                st.dataframe(res,use_container_width=True,hide_index=True)
                st.download_button("⬇️ Download S4 study candidates",res.to_csv(index=False),"s4_recovery_candidates.csv","text/csv")
        except Exception as ex:
            st.error(f"S4 recovery study error: {ex}")

    st.markdown("### What we will learn from this study")
    st.markdown("""
- **Impulse quality:** how large the preceding move was before consolidation.
- **Base quality:** whether volatility and range contracted instead of chaotic distribution.
- **Retracement depth:** shallow/healthy versus deep breakdown.
- **Volume behaviour:** contraction during the base and expansion on confirmation.
- **Reclaim:** EMA20/base-high recovery without requiring the exact S4 daily-close condition.
- **Higher-high confirmation:** evidence that the recovery is actually resuming, not merely bouncing.
- **Out-of-sample expectancy:** the pattern only becomes a candidate for a future rule change if it survives walk-forward testing.
""")
    st.subheader("🎯 S4 Entry Timing — preferred retracement workflow")
    st.markdown("""
**WAIT:** trend/structure is not ready.

**WATCH:** price reaches roughly the 38.2–61.8% pullback zone while the broader trend remains intact.

**BUY-TRIGGER:** only after confirmation such as EMA20 reclaim or a higher high, volume confirmation, and at least ~2.5R to the prior swing high. Stop goes below the pullback low. Prefer a 3R planning target when the structure supports it.

These thresholds are research heuristics—not guaranteed probabilities. The system should rank and label the setup rather than force a purchase.
""")
    st.warning("Important: the Study Score and BUY-TRIGGER are decision aids, not a probability of profit. Exact S4 remains unchanged.")

with tabs[10]:
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

                if market == "Crypto":
                    st.subheader("🧠 Crypto Continuous Learning")
                    cq = crypto_learning_summary(symbol)
                    if cq.empty:
                        st.info("No completed crypto-learning observations yet.")
                    else:
                        ca, cb, cc = st.columns(3)
                        ca.metric("Observations", len(cq))
                        cb.metric("Win %", round(float((cq.result_r > 0).mean()*100), 1))
                        cc.metric("Avg R", round(float(cq.result_r.mean()), 3))
                        st.dataframe(cq.head(200), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Strategy Rules")
    st.text_area("Paste your strategy",height=180,key="custom_strategy",
                 placeholder="Example: RSI > 55, close > 200 EMA, volume > 1.5x 20-day average. SL 7%, target 3R.")
    if st.button("🔍 Validate Strategy",key="custom_validate"):
        st.success("Strategy received. Convert ambiguous language into explicit testable rules before backtesting.")

st.markdown("---")
st.caption("Research / paper-testing system. Real-money Dhan order execution is intentionally disabled.")


# ========================= FINAL RESEARCH & RISK CONTROL =========================
with tabs[11]:
    st.subheader("🧬 Research & Risk Control — Final Architecture")
    st.caption("This control layer is intentionally separate from deterministic S1–S4 qualification. It measures whether the system is actually learning without changing the rules silently.")
    a,b,c,d=st.columns(4)
    con=_db()
    try:
        candles=int(con.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
        stocks=int(con.execute("SELECT COUNT(DISTINCT symbol) FROM candles").fetchone()[0])
        learn=int(con.execute("SELECT COUNT(*) FROM learning_observations").fetchone()[0])
        ft=int(con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0])
    finally: con.close()
    a.metric("Cached candles",f"{candles:,}"); b.metric("Cached stocks",f"{stocks:,}"); c.metric("Learning observations",f"{learn:,}"); d.metric("Forward records",f"{ft:,}")

    st.markdown("### Architecture safeguards")
    safeguards=pd.DataFrame([
        ["Exact S1–S4 qualification","ON","Learning cannot rewrite rules"],
        ["No-lookahead MTF features","ON","Historical week/month are as-of each date"],
        ["Dhan/local separation","ON","Backtest runner makes zero Dhan calls"],
        ["Persistent data cache","ON","Only missing ranges are downloaded"],
        ["Adaptive ranking","ON","Ranking only; qualification unchanged"],
        ["Fundamental enrichment","Candidate-only","Cached to avoid CPU/API overload"],
        ["News/event risk","Candidate-only","Press releases cached; risk never creates signals"],
        ["Real orders","OFF","Research/paper trading only"],
    ],columns=["Control","Status","Purpose"])
    st.dataframe(safeguards,use_container_width=True,hide_index=True)

    st.markdown("### 🧪 S4 Recovery — historical study")
    st.caption("Research hypothesis: large impulse → controlled consolidation/retracement → compression → reclaim → higher high. Exact S4 remains unchanged.")
    c1,c2,c3=st.columns(3)
    study_years=c1.selectbox("Study period",["6 Months","1 Year","2 Years","3 Years"],index=2,key="s4_walk_years")
    study_threshold=c2.slider("Recovery score",50,95,70,key="s4_walk_score")
    study_universe=c3.selectbox("Study universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],key="s4_walk_universe")
    if st.button("🔬 RUN S4 RECOVERY WALK-FORWARD STUDY",type="primary",key="s4_walk_run"):
        try:
            sd,ed=_bt_period(study_years); ticks=index_universe(study_universe)
            data=load_local_market_dataset(tuple(ticks),sd-timedelta(days=1000),ed,160)
            study=study_s4_recovery_walkforward(data,sd,ed,study_threshold)
            st.session_state["s4_recovery_bt_final"]=study
        except Exception as ex: st.error(f"S4 Recovery study error: {ex}")
    s4bt=st.session_state.get("s4_recovery_bt_final",pd.DataFrame())
    if s4bt.empty: st.info("Run the study to compare recovery setups against exact S4 behaviour.")
    else:
        m=research_metrics(s4bt)
        aa,bb,cc,dd=st.columns(4); aa.metric("Trades",m["trades"]); bb.metric("Win %",f"{m['win_rate']:.1f}%"); cc.metric("Avg R",f"{m['avg_r']:.2f}"); dd.metric("Profit Factor",f"{m['profit_factor']:.2f}")
        st.dataframe(s4bt.sort_values(["Score","Date"],ascending=[False,False]).head(300),use_container_width=True,hide_index=True)
        st.warning("Promotion rule: S4 Recovery is not allowed into the exact strategy until it survives out-of-sample/walk-forward evidence with adequate sample size and positive expectancy.")

    st.markdown("### 🛡️ Portfolio risk simulator")
    capital=st.number_input("Starting capital ₹",10000,100000000,100000,10000,key="risk_capital_final")
    risk_pct=st.slider("Risk per trade %",0.25,3.0,1.0,0.25,key="risk_pct_final")
    slots=st.slider("Maximum concurrent positions",1,20,5,key="risk_slots_final")
    bt=st.session_state.get("backtest_final",pd.DataFrame())
    if bt.empty: st.info("Run the local backtest first to simulate capital-aware portfolio results.")
    else:
        pr=portfolio_from_backtest(bt,float(capital),float(risk_pct),int(slots))
        st.dataframe(pd.DataFrame([pr]),use_container_width=True,hide_index=True)

    st.markdown("### 🧭 Advocate mode")
    st.info("The system should reject a trade when deterministic rules fail, safety is unacceptable, data quality is poor, or the learned evidence is insufficient. It should never manufacture a reason to trade.")

st.markdown("---")
st.caption(f"{APP_VERSION} • {ARCHITECTURE_STANDARD} • Research only • Real-money order execution disabled")
