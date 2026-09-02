import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import re
import sqlite3
import time
import threading
import queue
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime
from pathlib import Path
import math
import bisect
import os
import base64
import anthropic

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

# ---- GitHub-based DB backup/restore (Tier 1 fix for Streamlit Cloud's
# ephemeral filesystem: every reboot/redeploy clones a fresh container from
# GitHub, and DATA_DB is not committed to git, so accumulated learning data
# would otherwise vanish on any restart). This is a stopgap, not a permanent
# architecture - it commits a binary SQLite file to git on every backup,
# which will bloat the repo's history over months. A hosted SQLite-compatible
# DB (e.g. Turso) is the real long-term fix; this just prevents data loss now.
GITHUB_BACKUP_PATH = "backups/market_data.sqlite3"

def _github_configured():
    try:
        return bool(st.secrets.get("GITHUB_TOKEN")) and bool(st.secrets.get("GITHUB_REPO"))
    except Exception:
        return False

def _github_headers():
    return {
        "Authorization": f"token {st.secrets['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }

def restore_db_from_github():
    """Call once at app startup, before any _db() call. If the local DB file
    is missing or empty, pulls the last backup from GitHub so learning data
    survives a Streamlit Cloud reboot. Never raises - a failed restore just
    means the app starts fresh, same as today's behavior without this patch."""
    if not _github_configured():
        return False
    if os.path.exists(DATA_DB) and os.path.getsize(DATA_DB) > 0:
        return False  # local file already present this container session
    try:
        repo = st.secrets["GITHUB_REPO"]
        url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}"
        r = requests.get(url, headers=_github_headers(), timeout=30)
        if r.status_code != 200:
            return False  # no backup exists yet, or auth issue - fail quiet
        content_b64 = r.json().get("content", "")
        raw = base64.b64decode(content_b64)
        with open(DATA_DB, "wb") as f:
            f.write(raw)
        return True
    except Exception:
        return False

def backup_db_to_github():
    """Uploads the current local DB file to GitHub, overwriting the last
    backup. Returns True on success, False otherwise (never raises)."""
    if not _github_configured():
        return False
    if not os.path.exists(DATA_DB):
        return False
    try:
        repo = st.secrets["GITHUB_REPO"]
        url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}"
        with open(DATA_DB, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()
        # Need the current file's SHA if it already exists, else GitHub
        # rejects the update as a conflicting create.
        sha = None
        r = requests.get(url, headers=_github_headers(), timeout=30)
        if r.status_code == 200:
            sha = r.json().get("sha")
        payload = {
            "message": f"Auto-backup DB {datetime.now().isoformat(timespec='seconds')}",
            "content": content_b64,
        }
        if sha:
            payload["sha"] = sha
        put_r = requests.put(url, headers=_github_headers(), json=payload, timeout=60)
        return put_r.status_code in (200, 201)
    except Exception:
        return False

def maybe_backup_db(min_interval_minutes=15):
    """Rate-limited backup trigger - call after any write worth protecting
    (a learning trade recorded, a forward test closed, a candidate added).
    Only actually uploads if enough time has passed since the last backup
    this session, so routine activity doesn't spam GitHub commits."""
    key = "_last_db_backup_ts"
    last = st.session_state.get(key)
    now = datetime.now()
    if last is not None and (now - last).total_seconds() < min_interval_minutes * 60:
        return False
    ok = backup_db_to_github()
    if ok:
        st.session_state[key] = now
    return ok

restore_db_from_github()

DHAN_MIN_INTERVAL=0.205  # stay below the documented 5 data-API requests/sec
_DHAN_RATE_LOCK=threading.Lock()
_DHAN_LAST_REQUEST=0.0
_DHAN_LAST_DATA_ERRORS=[]

# Dhan access tokens are only valid 24h (SEBI/exchange requirement) with no
# refresh-token flow for a bare access token - PIN+TOTP (or a browser OAuth
# login) is required to mint a new one. If DHAN_PIN and DHAN_TOTP_SECRET are
# configured, the app renews the token itself once the cached one is older
# than DHAN_TOKEN_MAX_AGE_HOURS, instead of a manual daily Secrets paste.
# DHAN_ACCESS_TOKEN remains supported as a manual fallback when PIN+TOTP
# aren't configured.
DHAN_TOKEN_MAX_AGE_HOURS = 23
_DHAN_TOKEN_LOCK = threading.Lock()

def _dhan_pin_totp_configured():
    try:
        return bool(st.secrets["DHAN_CLIENT_ID"]) and bool(st.secrets["DHAN_PIN"]) and bool(st.secrets["DHAN_TOTP_SECRET"])
    except Exception:
        return False

def _dhan_manual_token_configured():
    try:
        return bool(st.secrets["DHAN_ACCESS_TOKEN"])
    except Exception:
        return False

def dhan_configured():
    try:
        if not st.secrets["DHAN_CLIENT_ID"]:
            return False
    except Exception:
        return False
    return _dhan_pin_totp_configured() or _dhan_manual_token_configured()

def _read_cached_dhan_token():
    con=_db()
    try:
        row=con.execute("SELECT access_token,issued_at FROM dhan_token_cache WHERE id=1").fetchone()
    finally:
        con.close()
    return (row[0],row[1]) if row else (None,None)

def _write_cached_dhan_token(token):
    con=_db()
    try:
        con.execute("""INSERT INTO dhan_token_cache(id,access_token,issued_at) VALUES(1,?,?)
            ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token,issued_at=excluded.issued_at""",
            (token,datetime.now().isoformat(timespec="seconds")))
        con.commit()
    finally:
        con.close()

def _dhan_generate_fresh_token():
    """Headless PIN+TOTP login (no browser step). Requires DHAN_PIN and
    DHAN_TOTP_SECRET (the base32 secret shown once when enabling TOTP-based
    API login in Dhan's console) alongside DHAN_CLIENT_ID in Streamlit Secrets."""
    import pyotp
    from dhanhq import DhanLogin
    code = pyotp.TOTP(str(st.secrets["DHAN_TOTP_SECRET"])).now()
    login = DhanLogin(str(st.secrets["DHAN_CLIENT_ID"]))
    result = login.generate_token(str(st.secrets["DHAN_PIN"]), code)
    token = None
    if isinstance(result, str):
        token = result
    elif isinstance(result, dict):
        for key in ("accessToken", "access_token", "token"):
            v = result.get(key)
            if isinstance(v, str) and v:
                token = v
                break
    if not token:
        # Unknown response shape from the dhanhq SDK - fail loudly rather than
        # silently caching a bad value. Whatever `result` actually looks like
        # here tells us exactly which key name to add above.
        raise RuntimeError(f"Dhan generate_token() returned an unrecognized response: {result!r}")
    _write_cached_dhan_token(token)
    return token

def _dhan_ensure_fresh_token():
    """Returns a valid Dhan access token, auto-renewing via PIN+TOTP if the
    cached one is missing/expired. Falls back to a manually-pasted
    DHAN_ACCESS_TOKEN secret when PIN+TOTP aren't configured."""
    if not _dhan_pin_totp_configured():
        return str(st.secrets["DHAN_ACCESS_TOKEN"])
    with _DHAN_TOKEN_LOCK:
        token, issued_at = _read_cached_dhan_token()
        fresh = False
        if token and issued_at:
            try:
                age_hours = (datetime.now() - datetime.fromisoformat(issued_at)).total_seconds() / 3600
                fresh = age_hours < DHAN_TOKEN_MAX_AGE_HOURS
            except Exception:
                fresh = False
        return token if fresh else _dhan_generate_fresh_token()

def _dhan_headers():
    return {
        "access-token":_dhan_ensure_fresh_token(),
        "client-id":str(st.secrets["DHAN_CLIENT_ID"]),
        "Content-Type":"application/json","Accept":"application/json"
    }

def _db():
    con=sqlite3.connect(DATA_DB,timeout=60,check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS candles(
        symbol TEXT NOT NULL, dt TEXT NOT NULL, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY(symbol,dt))""")
    con.execute("""CREATE TABLE IF NOT EXISTS dhan_token_cache(
        id INTEGER PRIMARY KEY CHECK (id=1), access_token TEXT, issued_at TEXT)""")
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
    if False:
        con.execute("""CREATE INDEX IF NOT EXISTS idx_scanner_signals_forward
                       ON scanner_signals(selected_for_forward,status)""")
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
    con.execute("""CREATE TABLE IF NOT EXISTS sync_diagnostics(
        symbol TEXT PRIMARY KEY, checked_at TEXT, bar_count INTEGER, reason TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sync_freshness_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, synced_at TEXT,
        most_recent_date_pulled TEXT, symbols_updated INTEGER)""")
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


# NSE cash-market close, IST wall-clock. The whole app already treats
# datetime.now()/date.today() as local wall-clock time (see the Dhan token
# cache above), so this follows the same convention rather than introducing
# timezone-aware datetimes into a codebase that has none.
NSE_MARKET_CLOSE_HOUR = 15
NSE_MARKET_CLOSE_MINUTE = 30

def latest_completed_nse_session(now=None):
    """Most recently *completed* NSE cash session: weekday-aware (via
    last_expected_nse_session) AND time-of-day aware (rolls back one more
    day before today's 15:30 IST close). Distinct from
    last_expected_nse_session(), which is date-only and used for sync/backtest
    date-range bounds where an off-by-one before market close is harmless.

    `now` is an injectable datetime for testing; defaults to wall-clock now.
    """
    now = now if now is not None else datetime.now()
    close_today = now.replace(hour=NSE_MARKET_CLOSE_HOUR, minute=NSE_MARKET_CLOSE_MINUTE,
                               second=0, microsecond=0)
    d = now.date()
    if now < close_today:
        d -= timedelta(days=1)
    return last_expected_nse_session(d)


def data_freshness_status(tickers, now=None):
    """Compare the MAX cached candle date across `tickers` against the most
    recently completed NSE session. Read-only diagnostics — never syncs."""
    expected = latest_completed_nse_session(now)
    symbols = sorted({str(t).upper().replace(".NS", "") for t in tickers}) if tickers else []
    latest = None
    if symbols:
        con = _db()
        try:
            qmarks = ",".join(["?"] * len(symbols))
            row = con.execute(f"SELECT MAX(dt) FROM candles WHERE symbol IN ({qmarks})", symbols).fetchone()
        finally:
            con.close()
        if row and row[0]:
            latest = pd.Timestamp(row[0]).date()
    if latest is None:
        return {"expected": expected, "latest": None, "current": False, "days_behind": None}
    if latest >= expected:
        days_behind = 0
    else:
        days_behind = len(pd.bdate_range(start=latest + timedelta(days=1), end=expected))
    return {"expected": expected, "latest": latest, "current": latest >= expected, "days_behind": int(days_behind)}


def render_data_freshness_banner(tickers, now=None):
    """Prominent, read-only freshness indicator for the Scanner/Backtest tabs.
    Visibility only — per the app's explicit-sync architecture, this never
    triggers a sync itself."""
    if not tickers:
        st.info("Select a universe to check local data freshness.")
        return None
    status = data_freshness_status(tickers, now=now)
    if status["latest"] is None:
        st.error("⚠️ No local candle data found for this universe yet. Run Data Manager → SYNC ONLY MISSING DATA before scanning.")
    elif status["current"]:
        st.success(f"✅ Data current as of {status['latest'].strftime('%d-%b-%Y')}")
    else:
        n = status["days_behind"]
        unit = "day" if n == 1 else "days"
        st.warning(
            f"⚠️ Local data is {n} {unit} behind — latest cached session is "
            f"{status['latest'].strftime('%d-%b-%Y')}, but {status['expected'].strftime('%d-%b-%Y')} "
            "has already closed. Run SYNC ONLY MISSING DATA before scanning, or signals will be based on stale prices."
        )
    return status


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
        # forward_tests already has its own 'ltp' column, and read_live_prices()
        # also returns one — merging both without renaming makes pandas
        # silently produce 'ltp_x'/'ltp_y' instead of a plain 'ltp', so
        # q["ltp"] below raised KeyError once a live tick actually existed.
        live_renamed = live[["symbol", "ts", "ltp"]].rename(columns={"ltp": "live_ltp", "ts": "live_ts"})
        q = q.merge(live_renamed, on="symbol", how="left")
        q["LTP"] = q["live_ltp"]
        q["P/L %"] = (q["LTP"] / q["entry"] - 1) * 100
        q["Live Updated"] = q["live_ts"]
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
    try:
        r=requests.get(f"{TWELVE_BASE}/{endpoint}",headers=_td_headers(),params=params,timeout=timeout)
    except Exception as exc:
        return {"_error":f"Network error: {exc}"}
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


# ============================================================================
# FUNDAMENTAL SCREENS A & B (Phase 2) — universe-wide quality screens built
# from raw Twelve Data financial statements, since Twelve Data has no direct
# "Piotroski score" field.
#
# UNVERIFIED ASSUMPTION — FLAGGED, NOT SILENTLY FIXED: this sandbox has no
# TWELVEDATA_API_KEY / live network access, so the exact field names inside
# Twelve Data's income_statement/balance_sheet/cash_flow responses have never
# been confirmed against a real response. _stmt_num() below tries several
# plausible key spellings per field, but they are GUESSES, exactly like the
# original patch this was built from. Do not trust a Piotroski score, ROCE
# fallback, or Screen A/B pass/fail without spot-checking it against a real
# filing first — see the st.info() caveat rendered in the Screen A/B tab.
# ============================================================================

def _td_get_statements(sym, outputsize=2):
    """Fetch income statement, balance sheet, cash flow (annual periods).
    outputsize defaults to 2 (enough for Screen A's YoY Piotroski checks);
    Screen B's 5-year sales-growth check needs 5 years of history, so its
    caller (run_fundamental_screens) passes outputsize=5 explicitly rather
    than this function always requesting 5 years regardless of which screen
    is running (that would cost extra Twelve Data API weight for history
    Screen A never uses).
    Returns dict with keys: income, balance, cashflow — each a list of
    period dicts (most recent first) or [] on failure. Never raises.
    """
    if not twelvedata_configured():
        return {"income": [], "balance": [], "cashflow": []}
    out = {}
    for key, ep in [("income", "income_statement"),
                     ("balance", "balance_sheet"),
                     ("cashflow", "cash_flow")]:
        try:
            j = _td_get(ep, {"symbol": sym, "exchange": "XNSE",
                              "period": "annual", "outputsize": outputsize})
            if isinstance(j, dict) and "_error" not in j:
                rows = j.get(key + "_statement", j.get("statement", []))
                if not rows:
                    for v in j.values():
                        if isinstance(v, list):
                            rows = v
                            break
                out[key] = rows if isinstance(rows, list) else []
            else:
                out[key] = []
        except Exception:
            out[key] = []
    return out


def _stmt_num(period_dict, *keys):
    """Pull a numeric field from one statement period, trying several
    possible key spellings (Twelve Data naming varies by statement type)."""
    if not isinstance(period_dict, dict):
        return np.nan
    flat = {}
    for section in period_dict.values():
        if isinstance(section, dict):
            flat.update(section)
    flat.update(period_dict)
    for k in keys:
        v = flat.get(k)
        try:
            if v is not None:
                return float(v)
        except Exception:
            pass
    return np.nan


def piotroski_score(statements):
    """Standard 9-point Piotroski F-Score using 2 years of statements.
    Returns (score:int 0-9, detail:dict) — missing data scores that test 0
    rather than raising, so a partial statement still returns a usable score.
    """
    inc = statements.get("income", [])
    bal = statements.get("balance", [])
    cf = statements.get("cashflow", [])
    if len(inc) < 2 or len(bal) < 2 or len(cf) < 1:
        return 0, {"error": "Insufficient statement history (need 2 years)"}

    cur_inc, prev_inc = inc[0], inc[1]
    cur_bal, prev_bal = bal[0], bal[1]
    cur_cf = cf[0]

    net_income = _stmt_num(cur_inc, "net_income", "netIncome")
    total_assets_cur = _stmt_num(cur_bal, "total_assets", "totalAssets")
    total_assets_prev = _stmt_num(prev_bal, "total_assets", "totalAssets")
    cfo = _stmt_num(cur_cf, "operating_cash_flow", "cash_from_operating_activities")
    lt_debt_cur = _stmt_num(cur_bal, "long_term_debt", "longTermDebt")
    lt_debt_prev = _stmt_num(prev_bal, "long_term_debt", "longTermDebt")
    cur_assets_cur = _stmt_num(cur_bal, "total_current_assets", "totalCurrentAssets")
    cur_liab_cur = _stmt_num(cur_bal, "total_current_liabilities", "totalCurrentLiabilities")
    cur_assets_prev = _stmt_num(prev_bal, "total_current_assets", "totalCurrentAssets")
    cur_liab_prev = _stmt_num(prev_bal, "total_current_liabilities", "totalCurrentLiabilities")
    shares_cur = _stmt_num(cur_bal, "common_shares_outstanding", "shares_outstanding")
    shares_prev = _stmt_num(prev_bal, "common_shares_outstanding", "shares_outstanding")
    gross_profit_cur = _stmt_num(cur_inc, "gross_profit", "grossProfit")
    revenue_cur = _stmt_num(cur_inc, "sales", "total_revenue", "revenue")
    gross_profit_prev = _stmt_num(prev_inc, "gross_profit", "grossProfit")
    revenue_prev = _stmt_num(prev_inc, "sales", "total_revenue", "revenue")
    net_income_prev = _stmt_num(prev_inc, "net_income", "netIncome")

    def safe_div(a, b):
        return a / b if (pd.notna(a) and pd.notna(b) and b != 0) else np.nan

    roa_cur = safe_div(net_income, total_assets_cur)
    roa_prev = safe_div(net_income_prev, total_assets_prev)
    leverage_cur = safe_div(lt_debt_cur, total_assets_cur)
    leverage_prev = safe_div(lt_debt_prev, total_assets_prev)
    current_ratio_cur = safe_div(cur_assets_cur, cur_liab_cur)
    current_ratio_prev = safe_div(cur_assets_prev, cur_liab_prev)
    gross_margin_cur = safe_div(gross_profit_cur, revenue_cur)
    gross_margin_prev = safe_div(gross_profit_prev, revenue_prev)
    asset_turnover_cur = safe_div(revenue_cur, total_assets_cur)
    asset_turnover_prev = safe_div(revenue_prev, total_assets_prev)

    tests = {}
    tests["positive_roa"] = pd.notna(roa_cur) and roa_cur > 0
    tests["positive_cfo"] = pd.notna(cfo) and cfo > 0
    tests["roa_improving"] = pd.notna(roa_cur) and pd.notna(roa_prev) and roa_cur > roa_prev
    tests["cfo_gt_netincome"] = pd.notna(cfo) and pd.notna(net_income) and cfo > net_income
    tests["leverage_decreasing"] = pd.notna(leverage_cur) and pd.notna(leverage_prev) and leverage_cur < leverage_prev
    tests["current_ratio_improving"] = pd.notna(current_ratio_cur) and pd.notna(current_ratio_prev) and current_ratio_cur > current_ratio_prev
    tests["no_new_shares"] = pd.notna(shares_cur) and pd.notna(shares_prev) and shares_cur <= shares_prev
    tests["gross_margin_improving"] = pd.notna(gross_margin_cur) and pd.notna(gross_margin_prev) and gross_margin_cur > gross_margin_prev
    tests["asset_turnover_improving"] = pd.notna(asset_turnover_cur) and pd.notna(asset_turnover_prev) and asset_turnover_cur > asset_turnover_prev

    score = int(sum(1 for v in tests.values() if v))
    return score, tests


def screen_a_metrics(sym, info, statements, price_return_1y):
    """Screen A — momentum + quality growth (Piotroski = 9 required)."""
    stats = info.get("statistics", {}) if isinstance(info.get("statistics"), dict) else {}
    prof = info.get("profile", {}) if isinstance(info.get("profile"), dict) else {}

    def num(*keys):
        for k in keys:
            v = stats.get(k, prof.get(k))
            try:
                if v is not None:
                    return float(v)
            except Exception:
                pass
        return np.nan

    mcap = num("market_capitalization", "market_cap")
    roce = num("return_on_capital_employed", "roce")
    roe = num("return_on_equity", "roe")
    qsales_g = num("quarterly_revenue_growth_yoy", "yoy_quarterly_sales_growth")
    qprofit_g = num("quarterly_earnings_growth_yoy", "yoy_quarterly_profit_growth")

    # ROCE fallback: EBIT / (Total Assets - Current Liabilities), latest statement
    if pd.isna(roce) and statements.get("income") and statements.get("balance"):
        ebit = _stmt_num(statements["income"][0], "operating_income", "ebit")
        ta = _stmt_num(statements["balance"][0], "total_assets", "totalAssets")
        cl = _stmt_num(statements["balance"][0], "total_current_liabilities", "totalCurrentLiabilities")
        if pd.notna(ebit) and pd.notna(ta) and pd.notna(cl) and (ta - cl) != 0:
            roce = 100.0 * ebit / (ta - cl)

    pscore, pdetail = piotroski_score(statements)

    checks = {
        "Market Cap (200-20000cr)": pd.notna(mcap) and 200 <= mcap <= 20000,
        "1Yr Return > 0": pd.notna(price_return_1y) and price_return_1y > 0,
        "YoY Qtr Sales Growth > 10%": pd.notna(qsales_g) and qsales_g > 10,
        "YoY Qtr Profit Growth > 10%": pd.notna(qprofit_g) and qprofit_g > 10,
        "ROCE > 15%": pd.notna(roce) and roce > 15,
        "ROE > 15%": pd.notna(roe) and roe > 15,
        "Piotroski = 9": pscore == 9,
    }
    passed = all(checks.values())
    return {
        "Ticker": sym, "Screen": "A", "Pass": passed,
        "Market Cap": mcap, "1Yr Return %": price_return_1y,
        "YoY Qtr Sales %": qsales_g, "YoY Qtr Profit %": qprofit_g,
        "ROCE %": roce, "ROE %": roe, "Piotroski": pscore,
        "Checks": checks,
    }


def screen_b_metrics(sym, info, statements):
    """Screen B — quality value + dividend (Promoter Holding flagged N/A:
    India shareholding-pattern disclosure, not carried by Twelve Data)."""
    stats = info.get("statistics", {}) if isinstance(info.get("statistics"), dict) else {}
    prof = info.get("profile", {}) if isinstance(info.get("profile"), dict) else {}

    def num(*keys):
        for k in keys:
            v = stats.get(k, prof.get(k))
            try:
                if v is not None:
                    return float(v)
            except Exception:
                pass
        return np.nan

    mcap = num("market_capitalization", "market_cap")
    eps = num("eps", "trailing_eps")
    roe = num("return_on_equity", "roe")
    debt_eq = num("debt_to_equity", "debt_equity")
    pe = num("pe_ratio", "trailing_pe")
    current_ratio = num("current_ratio")
    div_yield = num("dividend_yield")

    roce = num("return_on_capital_employed", "roce")
    if pd.isna(roce) and statements.get("income") and statements.get("balance"):
        ebit = _stmt_num(statements["income"][0], "operating_income", "ebit")
        ta = _stmt_num(statements["balance"][0], "total_assets", "totalAssets")
        cl = _stmt_num(statements["balance"][0], "total_current_liabilities", "totalCurrentLiabilities")
        if pd.notna(ebit) and pd.notna(ta) and pd.notna(cl) and (ta - cl) != 0:
            roce = 100.0 * ebit / (ta - cl)

    # Sales growth 5Y — needs 5+ annual periods. run_fundamental_screens()
    # requests outputsize=5 whenever Screen B is selected (see
    # _td_get_statements docstring) so this actually computes instead of
    # always being left NaN.
    sales_g5 = np.nan
    inc = statements.get("income", [])
    if len(inc) >= 5:
        rev_now = _stmt_num(inc[0], "sales", "total_revenue", "revenue")
        rev_5y = _stmt_num(inc[4], "sales", "total_revenue", "revenue")
        if pd.notna(rev_now) and pd.notna(rev_5y) and rev_5y > 0:
            sales_g5 = 100.0 * ((rev_now / rev_5y) ** (1/5) - 1)

    net_profit_margin = num("profit_margin", "net_profit_margin")
    op_profit_g = np.nan
    if len(inc) >= 2:
        op_cur = _stmt_num(inc[0], "operating_income", "ebit")
        op_prev = _stmt_num(inc[1], "operating_income", "ebit")
        if pd.notna(op_cur) and pd.notna(op_prev) and op_prev != 0:
            op_profit_g = 100.0 * (op_cur - op_prev) / abs(op_prev)

    pfcf = np.nan
    cf = statements.get("cashflow", [])
    if cf and pd.notna(mcap):
        cfo = _stmt_num(cf[0], "operating_cash_flow", "cash_from_operating_activities")
        capex = _stmt_num(cf[0], "capital_expenditure", "capex")
        if pd.notna(cfo) and pd.notna(capex):
            fcf = cfo - abs(capex)
            if fcf > 0:
                pfcf = mcap / fcf

    checks = {
        "Market Cap > 5000cr": pd.notna(mcap) and mcap > 5000,
        "EPS > 15": pd.notna(eps) and eps > 15,
        "Sales Growth 5Y > 10%": (pd.notna(sales_g5) and sales_g5 > 10) if pd.notna(sales_g5) else None,
        "ROE > 15%": pd.notna(roe) and roe > 15,
        "ROCE > 15%": pd.notna(roce) and roce > 15,
        "Debt/Equity < 0.5": pd.notna(debt_eq) and debt_eq < 0.5,
        "Price/FCF > 0": pd.notna(pfcf) and pfcf > 0,
        "Net Profit Margin > 10%": pd.notna(net_profit_margin) and net_profit_margin > 10,
        "PE < 25": pd.notna(pe) and pe < 25,
        "Current Ratio > 1.5": pd.notna(current_ratio) and current_ratio > 1.5,
        "Dividend Yield > 1%": pd.notna(div_yield) and div_yield > 1,
        "Operating Profit Growth > 15%": pd.notna(op_profit_g) and op_profit_g > 15,
        "Promoter Holding > 40%": None,  # data not available via Twelve Data — never silently true
    }
    evaluated = {k: v for k, v in checks.items() if v is not None}
    unverifiable = [k for k, v in checks.items() if v is None]
    passed = all(evaluated.values()) if evaluated else False

    return {
        "Ticker": sym, "Screen": "B", "Pass": passed,
        "Unverifiable": ", ".join(unverifiable) if unverifiable else "",
        "Market Cap": mcap, "EPS": eps, "ROE %": roe, "ROCE %": roce,
        "Debt/Equity": debt_eq, "P/E": pe, "Current Ratio": current_ratio,
        "Dividend Yield %": div_yield, "Sales Growth 5Y %": sales_g5,
        "Op Profit Growth %": op_profit_g, "Net Profit Margin %": net_profit_margin,
        "P/FCF": pfcf,
        "Checks": checks,
    }


def run_fundamental_screens(universe_names, run_a=True, run_b=True, progress_cb=None):
    """Scans the given universes against Screen A and/or B.
    progress_cb(done:int, total:int, symbol:str) is called after each stock
    if provided, so the UI can render a live progress bar.
    Returns a single DataFrame with all results (both screens if both run).
    """
    symbols = set()
    for u in universe_names:
        try:
            symbols.update(index_universe(u))
        except Exception:
            continue
    symbols = sorted(symbols)

    # Screen B's 5-year sales-growth check needs 5 annual periods; Screen A
    # only ever looks at 2. Only pay the extra Twelve Data outputsize cost
    # when Screen B is actually selected.
    stmt_outputsize = 5 if run_b else 2

    rows = []
    total = len(symbols)
    for i, full_sym in enumerate(symbols):
        sym = full_sym.replace(".NS", "")
        try:
            info, flags = company_info(sym)
            statements = _td_get_statements(sym, outputsize=stmt_outputsize)

            price_return_1y = np.nan
            try:
                stats = info.get("statistics", {}) if isinstance(info, dict) else {}
                price_return_1y = float(stats.get("52_week_change", stats.get("year_change", np.nan)))
            except Exception:
                pass

            if run_a:
                rows.append(screen_a_metrics(sym, info, statements, price_return_1y))
            if run_b:
                rows.append(screen_b_metrics(sym, info, statements))
        except Exception as e:
            rows.append({"Ticker": sym, "Screen": "ERROR", "Pass": False, "Checks": {"error": str(e)}})
        finally:
            if progress_cb:
                progress_cb(i + 1, total, sym)
            time.sleep(0.15)  # gentle pacing against Twelve Data rate limits

    return pd.DataFrame(rows)


def add_fundamental_forward_candidates(results_df):
    """Persists PASSing fundamental candidates into the existing forward_tests
    table (tagged FUNDA/FUNDB), same table/schema pattern as
    add_forward_candidates()/add_smc_forward_candidates() so they show up in
    the Forward Testing tab automatically — no new table.

    Unlike the original draft of this function, entry/sl/target are never
    left NULL: refresh_forward_positions() unconditionally does
    float(row.entry)/float(row.sl)/float(row.target) on every ACTIVE
    forward_tests row and would raise on a NULL price field, so a candidate
    without a resolvable local Dhan close price is skipped rather than
    inserted with placeholder nulls.

    Fundamental screens are long-term theses, not tactical S1-S4 setups, so
    entry/stop/target use a wider 15% stop (vs S1-S4's 7%) while keeping the
    same 3R target convention used everywhere else in the app, so result_r
    stays on a comparable scale across strategies in forward_summary_table().
    """
    if results_df is None or results_df.empty:
        return 0
    passed = results_df[results_df["Pass"] == True]
    if passed.empty:
        return 0
    con = _db(); added = 0
    try:
        today = str(date.today())
        for _, r in passed.iterrows():
            symbol = str(r.get("Ticker", "")).upper()
            strategy = "FUND" + str(r.get("Screen", "")).upper()
            if not symbol or strategy not in {"FUNDA", "FUNDB"}:
                continue
            exists = con.execute(
                "SELECT id FROM forward_tests WHERE symbol=? AND strategy=? AND signal_date=? LIMIT 1",
                (symbol, strategy, today)
            ).fetchone()
            if exists:
                continue

            d = _read_cache(con, symbol, date.today()-timedelta(days=30), date.today())
            if d is None or d.empty:
                continue  # no local Dhan price to anchor entry — skip rather than insert a NULL price row
            entry = float(d.close.iloc[-1])
            if not np.isfinite(entry) or entry <= 0:
                continue
            stop = entry * 0.85
            target = entry + 3 * (entry - stop)

            score = float(r.get("Piotroski", r.get("ROE %", 0)) or 0)
            now = datetime.now().isoformat(timespec="seconds")
            snapshot = {k: r.get(k, None) for k in r.index}
            cur = con.execute("""INSERT INTO forward_tests(
                created_at,symbol,strategy,score,regime,entry,sl,target,status,ltp,mfe,mae,
                exit_price,result_r,updated_at,signal_date,signal_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                now, symbol, strategy, score, "FUNDAMENTAL", entry, stop, target, "ACTIVE",
                entry, 0.0, 0.0, None, None, now, today,
                json.dumps(snapshot, default=str, allow_nan=True)
            ))
            fid = int(cur.lastrowid); added += 1
            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                fid, now, today, entry, entry, entry, 0.0, 0.0, 0.0, "ACTIVE"
            ))
        con.commit()
    finally:
        con.close()
    if added:
        maybe_backup_db()
    return added


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

# ============================================================================
# SMC PRICE ACTION STRATEGY (Forex/Crypto) — HTF=4h, LTF=15min
# ============================================================================
# detect_swings, _atr, detect_msb, find_order_block, detect_fvg, detect_sfp,
# premium_discount_zone, confluence_score, smc_htf_context, smc_ltf_trigger,
# and smc_signal below are taken from the user-supplied SMC patch, with one
# change: detect_msb's "strong MSB" thresholds (candle-body % and
# close-beyond %) were hardcoded literals (0.6, 0.10) in the supplied code
# despite the patch's own header saying they're "already" configurable via
# function args — they are now actual parameters (defaulting to the same
# 0.6/0.10 values) so the UI slider added below can actually vary them
# without editing this file.
#
# smc_backtest()'s loop body, scan_smc_pairs(), and add_smc_forward_
# candidates() were NOT present in the supplied patch (it was cut off
# mid-function) and are Claude's completion of the behavior described in
# the patch's own docstrings/header comment (partial-at-1R, move-to-
# breakeven, final target at opposing HTF liquidity; live multi-pair scan;
# tracking into the existing forward_tests table as strategy='FX_SMC').
# Review these three specifically before trusting their output — they are
# not verbatim from your file.
# ============================================================================

def detect_swings(df, left=3, right=3):
    """Marks swing highs/lows using a simple fractal: a bar is a swing high
    if its high is the max within [i-left, i+right], swing low similarly.
    Returns df copy with 'swing_high' and 'swing_low' boolean columns.
    """
    d = df.copy()
    d["swing_high"] = False
    d["swing_low"] = False
    n = len(d)
    highs = d["high"].values
    lows = d["low"].values
    for i in range(left, n - right):
        window_h = highs[i-left:i+right+1]
        window_l = lows[i-left:i+right+1]
        if highs[i] == window_h.max() and (window_h == highs[i]).sum() == 1:
            d.iloc[i, d.columns.get_loc("swing_high")] = True
        if lows[i] == window_l.min() and (window_l == lows[i]).sum() == 1:
            d.iloc[i, d.columns.get_loc("swing_low")] = True
    return d


def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def detect_msb(df_swung, atr_series, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Walks swing points in order, tracks the prevailing trend (based on
    sequence of higher-highs/higher-lows vs lower-highs/lower-lows), and
    flags the bar where price breaks the most recent counter-trend swing —
    i.e. an MSB. Only the break of the swing belonging to the DEEPEST leg
    counts (per the guide's rule), not every minor swing break.

    strong_body_pct / strong_close_beyond_pct: configurable "strong MSB"
    thresholds (calibrated guesses per the source guide, not exact values
    from any source) - candle body must be >= strong_body_pct of its range
    AND close beyond the broken level by >= strong_close_beyond_pct of the
    candle's range.

    Returns a list of dicts, one per detected MSB:
      {idx, direction ('bull'/'bear'), strength ('strong'/'weak'),
       broken_level, deepest_extreme_idx, origin_swing_idx}
    """
    d = df_swung
    swing_rows = d[(d["swing_high"]) | (d["swing_low"])].copy()
    if len(swing_rows) < 3:
        return []

    events = []
    seen_idx = set()
    last_swing_high_idx = None
    last_swing_low_idx = None
    deepest_low_idx = None
    deepest_high_idx = None

    for i in range(len(d)):
        row = d.iloc[i]
        if row["swing_high"]:
            last_swing_high_idx = i
            if deepest_high_idx is None or d["high"].iloc[i] > d["high"].iloc[deepest_high_idx]:
                deepest_high_idx = i
        if row["swing_low"]:
            last_swing_low_idx = i
            if deepest_low_idx is None or d["low"].iloc[i] < d["low"].iloc[deepest_low_idx]:
                deepest_low_idx = i

        # Bullish MSB: in a downtrend, close breaks above last swing high
        # that sits between the deepest low and now.
        if last_swing_high_idx is not None and deepest_low_idx is not None and last_swing_high_idx > deepest_low_idx:
            level = d["high"].iloc[last_swing_high_idx]
            if d["close"].iloc[i] > level and i not in seen_idx:
                body = abs(d["close"].iloc[i] - d["open"].iloc[i])
                rng = max(d["high"].iloc[i] - d["low"].iloc[i], 1e-9)
                close_beyond = d["close"].iloc[i] - level
                strong = (body / rng >= strong_body_pct) and (close_beyond >= strong_close_beyond_pct * rng)
                events.append({
                    "idx": i, "direction": "bull",
                    "strength": "strong" if strong else "weak",
                    "broken_level": float(level),
                    "deepest_extreme_idx": deepest_low_idx,
                    "origin_swing_idx": last_swing_high_idx,
                })
                seen_idx.add(i)
                deepest_low_idx = None  # reset leg after confirmed break

        # Bearish MSB: mirror logic breaking below last swing low.
        if last_swing_low_idx is not None and deepest_high_idx is not None and last_swing_low_idx > deepest_high_idx:
            level = d["low"].iloc[last_swing_low_idx]
            if d["close"].iloc[i] < level and i not in seen_idx:
                body = abs(d["close"].iloc[i] - d["open"].iloc[i])
                rng = max(d["high"].iloc[i] - d["low"].iloc[i], 1e-9)
                close_beyond = level - d["close"].iloc[i]
                strong = (body / rng >= strong_body_pct) and (close_beyond >= strong_close_beyond_pct * rng)
                events.append({
                    "idx": i, "direction": "bear",
                    "strength": "strong" if strong else "weak",
                    "broken_level": float(level),
                    "deepest_extreme_idx": deepest_high_idx,
                    "origin_swing_idx": last_swing_low_idx,
                })
                seen_idx.add(i)
                deepest_high_idx = None

    return events


def find_order_block(df, msb_event):
    """Scans backward from the MSB's origin swing to find the last
    opposite-colored candle before the impulsive leg. Returns dict with
    zone_top/zone_bottom or None if not found.
    """
    d = df
    start = msb_event["deepest_extreme_idx"]
    end = msb_event["origin_swing_idx"]
    if start is None or end is None or start >= end:
        return None
    bullish = msb_event["direction"] == "bull"
    for i in range(end, start - 1, -1):
        is_bear_candle = d["close"].iloc[i] < d["open"].iloc[i]
        is_bull_candle = d["close"].iloc[i] > d["open"].iloc[i]
        if bullish and is_bear_candle:
            return {"idx": i, "zone_top": float(d["high"].iloc[i]), "zone_bottom": float(d["low"].iloc[i]), "type": "demand_OB"}
        if (not bullish) and is_bull_candle:
            return {"idx": i, "zone_top": float(d["high"].iloc[i]), "zone_bottom": float(d["low"].iloc[i]), "type": "supply_OB"}
    return None


def detect_fvg(df, atr_series, min_atr_mult=0.10):
    """3-candle gap pattern. Bullish FVG: low[i] > high[i-2] (gap not
    filled by candle i-1). Bearish FVG: high[i] < low[i-2].
    Returns list of dicts: {idx, type, top, bottom}.
    """
    fvgs = []
    n = len(df)
    for i in range(2, n):
        atr_v = atr_series.iloc[i]
        if pd.isna(atr_v) or atr_v <= 0:
            continue
        min_gap = atr_v * min_atr_mult
        low_i = df["low"].iloc[i]
        high_i2 = df["high"].iloc[i-2]
        high_i = df["high"].iloc[i]
        low_i2 = df["low"].iloc[i-2]
        if low_i - high_i2 > min_gap:
            fvgs.append({"idx": i, "type": "bullish_fvg", "top": float(low_i), "bottom": float(high_i2)})
        if low_i2 - high_i > min_gap:
            fvgs.append({"idx": i, "type": "bearish_fvg", "top": float(low_i2), "bottom": float(high_i)})
    return fvgs


def detect_sfp(df_swung, atr_series, tolerance_atr_mult=0.15):
    """A bar that wicks beyond a prior swing high/low but closes back
    inside it — a stop-hunt / liquidity grab. Returns list of dicts.
    """
    d = df_swung
    sfps = []
    swing_highs = d.index[d["swing_high"]].tolist()
    swing_lows = d.index[d["swing_low"]].tolist()
    for i in range(len(d)):
        atr_v = atr_series.iloc[i]
        if pd.isna(atr_v) or atr_v <= 0:
            continue
        tol = atr_v * tolerance_atr_mult
        recent_highs = [sh for sh in swing_highs if sh < d.index[i]]
        if recent_highs:
            level = d.loc[recent_highs[-1], "high"]
            if d["high"].iloc[i] > level and d["high"].iloc[i] - level <= tol and d["close"].iloc[i] < level:
                sfps.append({"idx": i, "type": "bearish_sfp", "level": float(level)})
        recent_lows = [sl for sl in swing_lows if sl < d.index[i]]
        if recent_lows:
            level = d.loc[recent_lows[-1], "low"]
            if d["low"].iloc[i] < level and level - d["low"].iloc[i] <= tol and d["close"].iloc[i] > level:
                sfps.append({"idx": i, "type": "bullish_sfp", "level": float(level)})
    return sfps


def premium_discount_zone(swing_low_price, swing_high_price, current_price):
    """Returns (zone:'premium'/'discount'/'equilibrium', pct_of_range,
    ote_low, ote_high) — OTE = 0.7-0.8 retracement zone from swing extremes.
    """
    rng = swing_high_price - swing_low_price
    if rng <= 0:
        return "unknown", np.nan, np.nan, np.nan
    pct = (current_price - swing_low_price) / rng
    if pct >= 0.7:
        zone = "premium"
    elif pct <= 0.3:
        zone = "discount"
    else:
        zone = "equilibrium"
    ote_low = swing_low_price + 0.7 * rng
    ote_high = swing_low_price + 0.8 * rng
    return zone, round(pct, 3), ote_low, ote_high


def confluence_score(price_level, order_block, fvgs, sfps, tolerance_pct=0.0015):
    """Counts how many structures sit within tolerance of price_level.
    order_block: dict or None. fvgs/sfps: lists (already filtered to
    relevant recent ones by the caller). Returns (score:int, matched:list).
    """
    matched = []
    tol = price_level * tolerance_pct
    if order_block and order_block["zone_bottom"] - tol <= price_level <= order_block["zone_top"] + tol:
        matched.append(order_block["type"])
    for fvg in fvgs:
        if fvg["bottom"] - tol <= price_level <= fvg["top"] + tol:
            matched.append(fvg["type"])
    for sfp in sfps:
        if abs(sfp["level"] - price_level) <= tol:
            matched.append(sfp["type"])
    return len(matched), matched


def smc_htf_context(htf_df, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Full HTF read at the LATEST completed bar. Returns dict or None if
    no valid strong MSB / zone currently active.
    """
    d = detect_swings(htf_df)
    atr_s = _atr(d)
    msbs = detect_msb(d, atr_s, strong_body_pct, strong_close_beyond_pct)
    if not msbs:
        return None
    last_msb = msbs[-1]
    if last_msb["strength"] != "strong":
        return {"has_zone": False, "reason": "Last HTF MSB is weak — skip per guide's rule", "last_msb": last_msb}

    ob = find_order_block(d, last_msb)
    fvgs = detect_fvg(d, atr_s)
    sfps = detect_sfp(d, atr_s)

    deepest_idx = last_msb["deepest_extreme_idx"]
    origin_idx = last_msb["origin_swing_idx"]
    if last_msb["direction"] == "bull":
        zone_extreme = d["low"].iloc[deepest_idx]
        zone_origin = d["high"].iloc[origin_idx]
        swing_low_price, swing_high_price = zone_extreme, zone_origin
    else:
        zone_extreme = d["high"].iloc[deepest_idx]
        zone_origin = d["low"].iloc[origin_idx]
        swing_low_price, swing_high_price = zone_origin, zone_extreme

    current_price = float(d["close"].iloc[-1])
    zone_label, pct, ote_low, ote_high = premium_discount_zone(
        min(swing_low_price, swing_high_price), max(swing_low_price, swing_high_price), current_price
    )

    recent_fvgs = [f for f in fvgs if f["idx"] >= deepest_idx]
    recent_sfps = [s for s in sfps if s["idx"] >= deepest_idx]
    score, matched = confluence_score(current_price, ob, recent_fvgs, recent_sfps)

    bias_ok = (last_msb["direction"] == "bull" and zone_label == "discount") or \
              (last_msb["direction"] == "bear" and zone_label == "premium")

    return {
        "has_zone": True,
        "direction": last_msb["direction"],
        "msb": last_msb,
        "order_block": ob,
        "zone_label": zone_label,
        "zone_pct": pct,
        "ote_low": ote_low, "ote_high": ote_high,
        "confluence_score": score,
        "confluence_matched": matched,
        "bias_ok": bias_ok,
        "current_price": current_price,
        "swing_low": min(swing_low_price, swing_high_price),
        "swing_high": max(swing_low_price, swing_high_price),
    }


def smc_ltf_trigger(ltf_df, htf_ctx, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Checks if price is currently inside the HTF zone AND the LTF shows
    a micro-MSB (or SFP) confirming the HTF direction. Returns dict or None.
    """
    if not htf_ctx or not htf_ctx.get("has_zone"):
        return None
    price = float(ltf_df["close"].iloc[-1])
    in_zone = htf_ctx["swing_low"] <= price <= htf_ctx["swing_high"]
    if not in_zone:
        return None

    d = detect_swings(ltf_df)
    atr_s = _atr(d)
    micro_msbs = detect_msb(d, atr_s, strong_body_pct, strong_close_beyond_pct)
    if not micro_msbs:
        return None
    last_micro = micro_msbs[-1]
    if last_micro["idx"] < len(d) - 6:
        return None
    if last_micro["direction"] != htf_ctx["direction"]:
        return None

    sfps = detect_sfp(d, atr_s)
    recent_sfp = [s for s in sfps if s["idx"] >= len(d) - 6]

    return {
        "confirmed": True,
        "micro_msb": last_micro,
        "sfp_present": len(recent_sfp) > 0,
        "entry_price": float(d["close"].iloc[-1]),
        "trigger_idx": last_micro["idx"],
    }


def _smc_precompute(df, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """One-time precompute of swings/MSB/FVG/SFP for the FULL series.

    Used by smc_backtest() so it can do an O(log n) 'as of bar i' lookup
    per bar instead of what it did before: calling smc_htf_context()/
    smc_ltf_trigger() (which each re-run detect_swings/detect_msb from
    scratch) on an ever-growing slice ltf_df.iloc[:i+1] for every candidate
    bar. That growing-slice recompute is O(n) per call and was being called
    up to once per bar, making the whole backtest O(n^2) - this is what
    made the backtest hang/never finish on a ~5000-bar LTF series.

    This precompute is NOT a behavior change: detect_swings' fractal check
    at index k only ever reads bars [k-left, k+right], and detect_msb
    processes bars strictly in increasing order using only already-
    confirmed swings, so the value at any prefix of the series is
    identical whether computed on that prefix alone or on the full
    series and then read as-of that point. Same principle as the
    features_fast()/_regime_from_row() fix applied to the S1-S4 backtest.
    """
    swung = detect_swings(df)
    atr_s = _atr(swung)
    msbs = detect_msb(swung, atr_s, strong_body_pct, strong_close_beyond_pct)
    fvgs = detect_fvg(swung, atr_s)
    sfps = detect_sfp(swung, atr_s)
    return {"swung": swung, "atr": atr_s, "msbs": msbs, "msb_idx": [m["idx"] for m in msbs], "fvgs": fvgs, "sfps": sfps}


def _smc_htf_context_asof(pre, asof_idx):
    """O(log n) equivalent of smc_htf_context(), reading _smc_precompute()'s
    output as of bar asof_idx instead of recomputing from scratch."""
    if asof_idx < 0:
        return None
    pos = bisect.bisect_right(pre["msb_idx"], asof_idx) - 1
    if pos < 0:
        return None
    last_msb = pre["msbs"][pos]
    if last_msb["strength"] != "strong":
        return {"has_zone": False, "reason": "Last HTF MSB is weak — skip per guide's rule", "last_msb": last_msb}

    d = pre["swung"]
    ob = find_order_block(d, last_msb)
    deepest_idx = last_msb["deepest_extreme_idx"]
    origin_idx = last_msb["origin_swing_idx"]
    if last_msb["direction"] == "bull":
        swing_low_price = d["low"].iloc[deepest_idx]
        swing_high_price = d["high"].iloc[origin_idx]
    else:
        swing_low_price = d["low"].iloc[origin_idx]
        swing_high_price = d["high"].iloc[deepest_idx]

    current_price = float(d["close"].iloc[asof_idx])
    zone_label, pct, ote_low, ote_high = premium_discount_zone(
        min(swing_low_price, swing_high_price), max(swing_low_price, swing_high_price), current_price
    )

    recent_fvgs = [f for f in pre["fvgs"] if deepest_idx <= f["idx"] <= asof_idx]
    recent_sfps = [s for s in pre["sfps"] if deepest_idx <= s["idx"] <= asof_idx]
    score, matched = confluence_score(current_price, ob, recent_fvgs, recent_sfps)

    bias_ok = (last_msb["direction"] == "bull" and zone_label == "discount") or \
              (last_msb["direction"] == "bear" and zone_label == "premium")

    return {
        "has_zone": True,
        "direction": last_msb["direction"],
        "msb": last_msb,
        "order_block": ob,
        "zone_label": zone_label,
        "zone_pct": pct,
        "ote_low": ote_low, "ote_high": ote_high,
        "confluence_score": score,
        "confluence_matched": matched,
        "bias_ok": bias_ok,
        "current_price": current_price,
        "swing_low": min(swing_low_price, swing_high_price),
        "swing_high": max(swing_low_price, swing_high_price),
    }


def _smc_ltf_trigger_asof(pre, asof_idx, htf_ctx):
    """O(log n) equivalent of smc_ltf_trigger(), reading _smc_precompute()'s
    output as of bar asof_idx instead of recomputing from scratch."""
    if not htf_ctx or not htf_ctx.get("has_zone"):
        return None
    d = pre["swung"]
    price = float(d["close"].iloc[asof_idx])
    if not (htf_ctx["swing_low"] <= price <= htf_ctx["swing_high"]):
        return None
    pos = bisect.bisect_right(pre["msb_idx"], asof_idx) - 1
    if pos < 0:
        return None
    last_micro = pre["msbs"][pos]
    if last_micro["idx"] < asof_idx - 5:
        return None
    if last_micro["direction"] != htf_ctx["direction"]:
        return None
    recent_sfp = [s for s in pre["sfps"] if asof_idx - 5 <= s["idx"] <= asof_idx]
    return {
        "confirmed": True,
        "micro_msb": last_micro,
        "sfp_present": len(recent_sfp) > 0,
        "entry_price": price,
        "trigger_idx": last_micro["idx"],
    }


def smc_signal(htf_df, ltf_df, min_confluence=2, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Returns a signal dict if a valid trade setup exists right now,
    else None. Encodes the guide's stop/target rules directly.
    """
    htf_ctx = smc_htf_context(htf_df, strong_body_pct, strong_close_beyond_pct)
    if not htf_ctx or not htf_ctx.get("has_zone") or not htf_ctx.get("bias_ok"):
        return None
    if htf_ctx["confluence_score"] < min_confluence:
        return None

    ltf_trig = smc_ltf_trigger(ltf_df, htf_ctx, strong_body_pct, strong_close_beyond_pct)
    if not ltf_trig:
        return None

    direction = htf_ctx["direction"]
    entry = ltf_trig["entry_price"]

    if direction == "bull":
        stop = htf_ctx["swing_low"] * 0.999
        risk_per_unit = entry - stop
        target = htf_ctx["swing_high"]
    else:
        stop = htf_ctx["swing_high"] * 1.001
        risk_per_unit = stop - entry
        target = htf_ctx["swing_low"]

    if risk_per_unit <= 0:
        return None
    rr = abs(target - entry) / risk_per_unit

    return {
        "direction": direction,
        "entry": round(entry, 6),
        "stop": round(stop, 6),
        "target": round(target, 6),
        "risk_reward": round(rr, 2),
        "confluence_score": htf_ctx["confluence_score"],
        "confluence_matched": htf_ctx["confluence_matched"],
        "zone_label": htf_ctx["zone_label"],
        "msb_strength": htf_ctx["msb"]["strength"],
        "sfp_confirmation": ltf_trig["sfp_present"],
        "note": "Confirm macro/news calendar manually before entry — not automated in this system.",
    }


def smc_backtest(htf_df, ltf_df, capital=100000, risk_pct=1.0, min_confluence=2, slip=0.0005,
                  strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Walks the LTF series bar-by-bar, re-evaluating HTF context every N
    bars (approximating a live re-scan), simulating entries per smc_signal
    logic. Applies: partial at 1R (half position, then stop moved to
    breakeven), final target at the opposing HTF swing (liquidity).
    Returns (trades_df, equity_curve_list).

    NOT present in the supplied patch (file was truncated mid-loop) —
    this loop body is Claude's completion of the behavior described in the
    function's own docstring/header comment. Review before trusting it.

    SIMPLIFICATION: slip is a fixed percentage placeholder applied to the
    entry price (default 0.05%), not a real spread/liquidity/session model.
    Do not treat backtest R-multiples as production-accurate without this
    caveat in mind — the UI surfaces this same warning next to the results.

    PERFORMANCE: uses _smc_precompute()/_smc_htf_context_asof()/
    _smc_ltf_trigger_asof() rather than calling smc_htf_context()/
    smc_ltf_trigger() on a growing ltf_df.iloc[:i+1] slice per bar - the
    growing-slice version re-ran detect_swings/detect_msb from scratch on
    every candidate bar (O(n) per call, called up to once per bar), making
    the whole backtest O(n^2) and causing it to hang/never finish on a
    full ~5000-bar LTF series. See _smc_precompute()'s docstring for why
    this is a pure performance fix with no behavior change.
    """
    equity = float(capital)
    rows = []
    equity_curve = [equity]
    htf_recompute_every = 16  # ~ once per HTF bar equivalent (4h/15m = 16)
    i = 60  # warmup for swing/ATR detection
    n = len(ltf_df)
    if n <= i + 1 or len(htf_df) < 60:
        return pd.DataFrame(rows), equity_curve

    htf_pre = _smc_precompute(htf_df, strong_body_pct, strong_close_beyond_pct)
    ltf_pre = _smc_precompute(ltf_df, strong_body_pct, strong_close_beyond_pct)
    htf_ctx_cache = None
    pos = None

    while i < n - 1:
        if pos is None:
            if htf_ctx_cache is None or i % htf_recompute_every == 0:
                htf_asof = int(htf_df.index.searchsorted(ltf_df.index[i], side="right")) - 1
                htf_ctx_cache = _smc_htf_context_asof(htf_pre, htf_asof) if htf_asof >= 60 else None

            sig = None
            if htf_ctx_cache and htf_ctx_cache.get("has_zone") and htf_ctx_cache.get("bias_ok") \
               and htf_ctx_cache["confluence_score"] >= min_confluence:
                ltf_trig = _smc_ltf_trigger_asof(ltf_pre, i, htf_ctx_cache)
                if ltf_trig:
                    direction = htf_ctx_cache["direction"]
                    raw_entry = float(ltf_df["close"].iloc[i])
                    entry = raw_entry * (1 + slip) if direction == "bull" else raw_entry * (1 - slip)
                    if direction == "bull":
                        stop = htf_ctx_cache["swing_low"] * 0.999
                        risk_per_unit = entry - stop
                        target = htf_ctx_cache["swing_high"]
                    else:
                        stop = htf_ctx_cache["swing_high"] * 1.001
                        risk_per_unit = stop - entry
                        target = htf_ctx_cache["swing_low"]
                    if risk_per_unit > 0 and abs(target - entry) / risk_per_unit >= 1.0:
                        sig = {
                            "direction": direction, "entry": entry, "stop": stop, "target": target,
                            "risk_per_unit": risk_per_unit, "entry_idx": i, "partial_taken": False,
                            "confluence_score": htf_ctx_cache["confluence_score"],
                            "msb_strength": htf_ctx_cache["msb"]["strength"],
                        }
            if sig:
                pos = sig
                htf_ctx_cache = None  # force a fresh HTF read before the next entry
        else:
            bar = ltf_df.iloc[i]
            direction = pos["direction"]
            one_r_level = pos["entry"] + pos["risk_per_unit"] if direction == "bull" else pos["entry"] - pos["risk_per_unit"]
            exit_now, exit_price, outcome = False, None, None

            if direction == "bull":
                if not pos["partial_taken"] and bar["high"] >= one_r_level:
                    pos["partial_taken"] = True
                    pos["stop"] = pos["entry"]  # move to breakeven
                if bar["low"] <= pos["stop"]:
                    exit_now, exit_price = True, pos["stop"]
                elif bar["high"] >= pos["target"]:
                    exit_now, exit_price = True, pos["target"]
            else:
                if not pos["partial_taken"] and bar["low"] <= one_r_level:
                    pos["partial_taken"] = True
                    pos["stop"] = pos["entry"]
                if bar["high"] >= pos["stop"]:
                    exit_now, exit_price = True, pos["stop"]
                elif bar["low"] <= pos["target"]:
                    exit_now, exit_price = True, pos["target"]

            if i == n - 2 and not exit_now:
                exit_now, exit_price, outcome = True, float(ltf_df["close"].iloc[i]), "TIMEOUT"

            if exit_now:
                final_r = (exit_price - pos["entry"]) / pos["risk_per_unit"] if direction == "bull" \
                    else (pos["entry"] - exit_price) / pos["risk_per_unit"]
                # Half the position was already realized at +1R if the partial
                # fired; the other half rides to the final exit (>=0R once the
                # stop is at breakeven).
                blended_r = 0.5 * 1.0 + 0.5 * final_r if pos["partial_taken"] else final_r
                if outcome is None:
                    outcome = "WIN" if blended_r > 0 else "LOSS"
                risk_cash = equity * (risk_pct / 100.0)
                equity += risk_cash * blended_r
                equity_curve.append(equity)
                rows.append({
                    "Entry Date": ltf_df.index[pos["entry_idx"]], "Exit Date": ltf_df.index[i],
                    "Direction": direction.upper(), "Entry": round(pos["entry"], 6),
                    "Stop": round(pos["stop"], 6), "Target": round(pos["target"], 6),
                    "Exit": round(exit_price, 6), "Partial at 1R": pos["partial_taken"],
                    "R": round(blended_r, 3), "Outcome": outcome,
                    "Confluence": pos["confluence_score"], "MSB Strength": pos["msb_strength"],
                    "Holding Bars": i - pos["entry_idx"],
                })
                pos = None
        i += 1

    return pd.DataFrame(rows), equity_curve


def scan_smc_pairs(pairs, market="Forex", min_confluence=2, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Live multi-pair SMC scan: fetches HTF(4h)+LTF(15min) data for each
    pair via Twelve Data and evaluates smc_signal(). One bad pair never
    blanks the rest (per-pair try/except, matching this app's existing
    scanner pattern). Returns a DataFrame of current setups (possibly
    empty). NOT present in the supplied patch - Claude's completion.
    """
    rows = []
    for pair in pairs:
        try:
            htf_df = td_market_history(pair, market, "4h", years=1)
            ltf_df = td_market_history(pair, market, "15min", years=1)
            if htf_df.empty or ltf_df.empty or len(htf_df) < 60 or len(ltf_df) < 60:
                continue
            sig = smc_signal(htf_df, ltf_df, min_confluence, strong_body_pct, strong_close_beyond_pct)
            if sig:
                rows.append({"Pair": pair, **sig})
        except Exception as e:
            rows.append({"Pair": pair, "direction": "ERROR", "entry": np.nan, "stop": np.nan,
                         "target": np.nan, "risk_reward": np.nan, "confluence_score": np.nan,
                         "confluence_matched": [], "zone_label": str(e), "msb_strength": "",
                         "sfp_confirmation": False, "note": ""})
    return pd.DataFrame(rows)


def add_smc_forward_candidates(candidates):
    """Persist SMC scanner signals into the EXISTING forward_tests table,
    tagged strategy='FX_SMC' - same table/schema as add_forward_candidates(),
    no new table created. NOT present in the supplied patch - Claude's
    completion, modeled directly on add_forward_candidates()'s pattern.
    """
    if candidates is None or len(candidates) == 0:
        return 0
    valid = candidates[candidates.get("direction", pd.Series(dtype=str)) != "ERROR"] if "direction" in candidates.columns else candidates
    if valid.empty:
        return 0
    con = _db(); added = 0
    try:
        today = str(date.today())
        for _, r in valid.iterrows():
            symbol = str(r.get("Pair", "")).upper()
            entry = float(r.get("entry", np.nan)); sl = float(r.get("stop", np.nan)); target = float(r.get("target", np.nan))
            if not symbol or not np.isfinite(entry) or entry <= 0 or not np.isfinite(sl) or not np.isfinite(target):
                continue
            exists = con.execute(
                """SELECT id FROM forward_tests WHERE symbol=? AND strategy=? AND signal_date=? LIMIT 1""",
                (symbol, "FX_SMC", today)
            ).fetchone()
            if exists:
                continue
            now = datetime.now().isoformat(timespec="seconds")
            # forward_tests' "score" column is 0-100 elsewhere (S1-S4); SMC has
            # no natural 0-100 score, so confluence_score (typically 2-5) is
            # scaled for rough display/sort convenience only - not comparable
            # to S1-S4 scores.
            display_score = float(min(100, r.get("confluence_score", 0) * 20))
            snapshot = {k: r.get(k, None) for k in r.index}
            cur = con.execute("""INSERT INTO forward_tests(
                created_at,symbol,strategy,score,regime,entry,sl,target,status,ltp,mfe,mae,
                exit_price,result_r,updated_at,signal_date,signal_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                now, symbol, "FX_SMC", display_score, str(r.get("zone_label", "")),
                entry, sl, target, "ACTIVE", entry, 0.0, 0.0, None, None, now,
                today, json.dumps(snapshot, default=str, allow_nan=True)
            ))
            fid = int(cur.lastrowid); added += 1
            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                fid, now, today, entry, entry, entry, 0.0, 0.0, 0.0, "ACTIVE"
            ))
        con.commit()
    finally:
        con.close()
    if added:
        maybe_backup_db()
    return added


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

def s4_base_conditions(x):
    """Every exact Strategy 4 condition EXCEPT the daily close<=1.03*EMA20
    proximity rule. Shared by strategy_signal(s=4) (which ANDs the exact 3%
    rule back in) and s4_ema20_extension_calibration(), which studies what
    the historically best-performing EMA20 distance actually is instead of
    assuming 3% without evidence."""
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
        (x.mmom >= 20) &
        (x.mrsi14 >= 50) &
        (x.mema10 >= x.mema20) &
        (x.vol30 >= 50000) &
        (x.close >= 20) &
        (
            (monthly_bull_cross_count >= 1) |
            monthly_reclaim
        )
    )

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

        return s4_base_conditions(x) & (x.close <= 1.03 * x.ema20)

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

def _regime_from_row(f,i):
    """O(1) equivalent of regime_from_index(hist) — reads the already-computed
    features_fast() frame at row i instead of recomputing features() from scratch
    on a growing history slice for every signal (that recompute is O(len^2) per
    call because of the weekly/monthly as-of loops, and was being called once per
    signal per ticker per strategy inside the backtest — an O(n^3)-class hot path)."""
    if i<30 or i-20<0:
        return "UNKNOWN",0
    z=f.iloc[i]
    ema200_lag20=f.ema200.iloc[i-20]
    req=(z.close,z.ema200,z.ema50,z.rsi14,z.ema20,z.relvol,ema200_lag20)
    if any(pd.isna(v) for v in req):
        return "UNKNOWN",0
    score=0
    score += 25 if z.close>z.ema200 else 0
    score += 20 if z.ema50>z.ema200 else 0
    score += 15 if z.ema200>ema200_lag20 else 0
    score += 15 if z.rsi14>=55 else 0
    score += 10 if z.close>z.ema20 else 0
    score += 15 if z.relvol>=1 else 0
    if score>=75: return "STRONG BULL",score
    if score>=60: return "BULL",score
    if score>=45: return "RECOVERY / SIDEWAYS",score
    if score>=30: return "EARLY BEAR",score
    return "BEAR",score

def _safety_fast_series(df):
    """Vectorized once-per-ticker precompute of the rolling stats safety() reads,
    so the backtest hot loop can look them up in O(1) per signal instead of
    re-slicing/re-computing tail(20)/tail(30) windows from scratch per signal."""
    avg_value=(df.close*df.volume).rolling(20,min_periods=1).mean()
    abnormal=(df.close.pct_change().abs()>.15).rolling(30,min_periods=1).sum()
    return avg_value,abnormal

def _safety_from_row(avg_value,abnormal,i):
    """O(1) equivalent of safety({}, hist) for the backtest (info is always {}
    there, so the debt/insider branches never fire)."""
    score=100; flags=[]
    av=avg_value.iloc[i]
    if pd.notna(av):
        if av<2_000_000: score-=30; flags.append("Low traded value")
        if av<500_000: score-=20; flags.append("Very low liquidity")
    ab=abnormal.iloc[i]
    if pd.notna(ab) and ab>=3:
        score-=15; flags.append("Abnormal volatility")
    score=max(0,min(100,score))
    status="ELIGIBLE" if score>=70 else ("CAUTION" if score>=50 else "REJECT")
    return score,status,flags


# ========================= CUSTOM STRATEGY DSL =========================
# Whitelist-only rule language — never eval()/exec(). Each non-blank, non-
# comment line must be "<COLUMN> <op> <RHS>" where COLUMN is one of the
# known features_fast() columns and RHS is a number, another known column,
# or "NUMBER * COLUMN" (e.g. "VOLUME > 1.5 * VOL20"). Lines are AND-combined.

CUSTOM_DSL_COLUMNS = {
    "open","high","low","close","volume",
    "ema10","ema20","ema50","ema200","ema250","vol20","vol30","rsi14","relvol","atr14",
    "wrsi14","wema20","wema50","wclose",
    "mclose","mopen","mhigh","mlow","mrsi14","mema10","mema15","mema20","mmom","mmax20",
    "mprevclose","mprevhigh","mprevlow","m_cross_count20","m_cross_10_20",
}
CUSTOM_DSL_OPS = {
    ">": lambda a,b: a>b, ">=": lambda a,b: a>=b,
    "<": lambda a,b: a<b, "<=": lambda a,b: a<=b,
    "==": lambda a,b: a==b, "!=": lambda a,b: a!=b,
}
_CUSTOM_DSL_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")
_CUSTOM_DSL_MUL_RE_NC = re.compile(r"^([0-9]*\.?[0-9]+)\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)$")
_CUSTOM_DSL_MUL_RE_CN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\*\s*([0-9]*\.?[0-9]+)$")

def parse_custom_strategy(text):
    """Parse the DSL into a validated condition list. Returns (conditions, errors);
    conditions is empty and errors non-empty when any line fails to validate —
    callers must refuse to run a strategy with any error, not silently drop lines."""
    conditions, errors = [], []
    for lineno, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _CUSTOM_DSL_LINE_RE.match(line)
        if not m:
            errors.append(f"Line {lineno}: could not parse '{raw}'. Expected '<COLUMN> <op> <value>', e.g. 'RSI14 > 55'.")
            continue
        left_raw, op, rhs = m.group(1), m.group(2), m.group(3).strip()
        left = left_raw.lower()
        if left not in CUSTOM_DSL_COLUMNS:
            errors.append(f"Line {lineno}: unknown column '{left_raw}'. Known columns: {', '.join(sorted(CUSTOM_DSL_COLUMNS))}.")
            continue
        try:
            conditions.append({"left":left,"op":op,"rhs_kind":"number","rhs_value":float(rhs),"text":line})
            continue
        except ValueError:
            pass
        mm = _CUSTOM_DSL_MUL_RE_NC.match(rhs)
        if mm:
            mult,col = float(mm.group(1)), mm.group(2).lower()
        else:
            mm = _CUSTOM_DSL_MUL_RE_CN.match(rhs)
            mult,col = (float(mm.group(2)), mm.group(1).lower()) if mm else (None,None)
        if mm:
            if col not in CUSTOM_DSL_COLUMNS:
                errors.append(f"Line {lineno}: unknown column '{col}' on the right-hand side of '{raw}'.")
                continue
            conditions.append({"left":left,"op":op,"rhs_kind":"multiplier","rhs_value":(mult,col),"text":line})
            continue
        if rhs.lower() in CUSTOM_DSL_COLUMNS:
            conditions.append({"left":left,"op":op,"rhs_kind":"column","rhs_value":rhs.lower(),"text":line})
            continue
        errors.append(f"Line {lineno}: right-hand side '{rhs}' is not a number, a known column, or 'NUMBER * COLUMN'.")
    return conditions, errors

def custom_strategy_signal(f, conditions):
    """Vectorized AND of all parsed conditions against a features_fast() frame."""
    if f.empty or not conditions:
        return pd.Series(False, index=f.index)
    sig = pd.Series(True, index=f.index)
    for c in conditions:
        left = f[c["left"]]
        if c["rhs_kind"] == "number":
            right = c["rhs_value"]
        elif c["rhs_kind"] == "column":
            right = f[c["rhs_value"]]
        else:
            mult, col = c["rhs_value"]
            right = f[col] * mult
        sig = sig & CUSTOM_DSL_OPS[c["op"]](left, right).fillna(False)
    return sig


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
        maybe_backup_db()
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
    # learned_score/holding_bars are legacy columns added via ALTER TABLE
    # migration (ensure_learning_tables) and never populated by any INSERT
    # (_learn_from_backtest only writes the original column set). When every
    # value in a SQL column is NULL, pandas has nothing to infer a numeric
    # dtype from, so the column stays dtype=object holding literal Python
    # None instead of NaN - and st.dataframe() renders that as the literal
    # text "None" (this is what showed up in the Market Learning tab's
    # "Persistent Learning Database" table). Coercing explicitly avoids that
    # regardless of whether every row happens to be NULL.
    for _col in ("learned_score", "holding_bars"):
        if _col in q.columns:
            q[_col] = pd.to_numeric(q[_col], errors="coerce")
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


def compute_and_store_sync_diagnostics(tickers):
    """For every symbol below the 260-bar backtest-readiness threshold, work
    out WHY and persist it to sync_diagnostics (upserted per symbol) so the
    Data Manager can show an actionable list instead of a silent gap.

    Distinguishes three root causes:
      - not present in the Dhan instrument master at all (symbol mismatch,
        e.g. index reconstitution renamed/added/removed a constituent)
      - a real Dhan API error recorded on the last sync attempt
      - a successful download that simply doesn't have 260 bars yet
        (e.g. a recently listed stock), or zero bars (never synced)
    Never raises: a failure to reach the instrument master itself (e.g. no
    network/credentials) is reported as a reason, not swallowed.
    """
    symbols = sorted({str(t).upper().replace(".NS", "") for t in tickers}) if tickers else []
    if not symbols:
        return pd.DataFrame(columns=["symbol", "bar_count", "reason"])

    con = _db()
    try:
        qmarks = ",".join(["?"] * len(symbols))
        rows = con.execute(
            f"SELECT symbol,COUNT(*) FROM candles WHERE symbol IN ({qmarks}) GROUP BY symbol", symbols
        ).fetchall()
    finally:
        con.close()
    bar_counts = {r[0]: r[1] for r in rows}
    for s in symbols:
        bar_counts.setdefault(s, 0)

    below = [s for s in symbols if bar_counts[s] < 260]
    if not below:
        return pd.DataFrame(columns=["symbol", "bar_count", "reason"])

    mapping = None
    map_error = None
    try:
        mapping = dhan_map()
    except Exception as exc:
        map_error = str(exc)

    err_by_symbol = {}
    for e in _DHAN_LAST_DATA_ERRORS:
        if ":" in e:
            sym, msg = e.split(":", 1)
            err_by_symbol[str(sym).strip().upper().replace(".NS", "")] = msg.strip()

    out = []
    checked_at = datetime.now().isoformat(timespec="seconds")
    for s in below:
        bc = bar_counts[s]
        if mapping is not None and s not in mapping:
            reason = "Not found in Dhan instrument master — likely a symbol mismatch (index reconstitution: addition/removal/rename)"
        elif s in err_by_symbol:
            reason = f"Dhan API error on last sync: {err_by_symbol[s]}"
        elif mapping is None:
            reason = f"Could not verify Dhan instrument-master mapping ({map_error})" if map_error else "Instrument-master mapping unavailable"
        elif bc == 0:
            reason = "No candles downloaded yet — symbol not synced"
        else:
            reason = f"Only {bc} trading bar(s) available in Dhan history (likely a recently listed stock)"
        out.append({"symbol": s, "bar_count": bc, "reason": reason})

    con = _db()
    try:
        for row in out:
            con.execute(
                """INSERT INTO sync_diagnostics(symbol,checked_at,bar_count,reason)
                   VALUES(?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET checked_at=excluded.checked_at,
                       bar_count=excluded.bar_count, reason=excluded.reason""",
                (row["symbol"], checked_at, row["bar_count"], row["reason"]),
            )
        con.commit()
    finally:
        con.close()
    return pd.DataFrame(out).sort_values("bar_count").reset_index(drop=True)


def _log_sync_freshness(most_recent_date_pulled, symbols_updated):
    """One-line log entry: a sync pulled a new most-recent trading day's
    candle for at least one symbol. Lets the app owner observe, over real
    trading sessions, how soon after close Dhan's data actually becomes
    available."""
    con = _db()
    try:
        con.execute(
            "INSERT INTO sync_freshness_log(synced_at,most_recent_date_pulled,symbols_updated) VALUES(?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), str(most_recent_date_pulled), int(symbols_updated)),
        )
        con.commit()
    finally:
        con.close()


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
            avg_value,abnormal=_safety_fast_series(df)
            for s in strategies:
                sig=strategy_signal(f,s).fillna(False).to_numpy()
                for i in np.flatnonzero(sig):
                    dt=pd.Timestamp(f.index[i])
                    if dt<start or dt>end or i>=len(df)-1:continue
                    regime,_=_regime_from_row(f,i)
                    safe,_,_=_safety_from_row(avg_value,abnormal,i)
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

def _custom_strategy_backtest(data,conditions,start_date,end_date,sl_pct=0.07,target_r=3.0,threshold=0):
    """Local-only walk-forward replay of a validated Custom Strategy DSL rule
    set. Same architecture/columns as _professional_bt (S1-S4) so the result
    feeds _learn_from_backtest() unmodified, tagged strategy='CUSTOM'."""
    rows=[];start=pd.Timestamp(start_date);end=pd.Timestamp(end_date)
    for ticker,df in data.items():
        if len(df)<260:continue
        try:
            df=df.sort_index();f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
            if f.empty:continue
            avg_value,abnormal=_safety_fast_series(df)
            sig=custom_strategy_signal(f,conditions).fillna(False).to_numpy()
            for i in np.flatnonzero(sig):
                dt=pd.Timestamp(f.index[i])
                if dt<start or dt>end or i>=len(df)-1:continue
                regime,_=_regime_from_row(f,i)
                safe,_,_=_safety_from_row(avg_value,abnormal,i)
                score,parts=_row_score(f,i,"CUSTOM",regime,safe)
                if score<int(threshold):continue
                entry_i=i+1; entry=float(df.close.iloc[entry_i])
                if not np.isfinite(entry) or entry<=0:continue
                stop=entry*(1-sl_pct);target=entry+target_r*(entry-stop);risk=entry-stop
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
                    'Date':dt.date(),'Ticker':str(ticker).replace('.NS',''),'Strategy':'CUSTOM',
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
            # known up to the candidate date. To keep execution sharp, use an
            # O(1) lookup on the already-computed feature frame instead of
            # recomputing features()/safety() from scratch per signal.
            avg_value, abnormal = _safety_fast_series(df)
            for s in strategies:
                sig = strategy_signal(f, s).fillna(False).to_numpy()
                idxs = np.flatnonzero(sig)

                for i in idxs:
                    dt = pd.Timestamp(f.index[i])
                    if dt < start or i >= len(f)-1:
                        continue

                    regime, _ = _regime_from_row(f, i)
                    safe, _, _ = _safety_from_row(avg_value, abnormal, i)
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
    if n:
        maybe_backup_db()
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

def fallback_win_probability(market, strategy, score):
    """Score-band historical win rate (adaptive_edge_table), used as the
    Win Probability % estimate whenever the ML classifier isn't trained yet."""
    q = adaptive_edge_table(market)
    if q.empty:
        return np.nan
    band = "85-89" if 85 <= score <= 89 else "90-94" if score <= 94 else "95-100" if score >= 95 else "<85"
    row = q[(q.Strategy == strategy) & (q["Score Band"] == band)]
    if row.empty or int(row.iloc[0]["Samples"]) < 20:
        return np.nan
    return float(row.iloc[0]["Win % (shrunk)"])


# ========================= AI SYSTEM COACH (LLM) — Phase 6 =========================
# On-demand LLM analysis of the marking system as a WHOLE (backtest performance,
# forward-test resolution, component correlations, adaptive edge table) — not one
# trade. Distinct from the existing rule-based "🎓 Strategy Coach" tab (decision-tree/
# regime-breakdown, no LLM call); this one is titled "AI System Coach (LLM)" in the
# UI specifically to avoid confusion between the two.
#
# COST CONTROL: one batched API call per run, sending only AGGREGATED stats (never
# raw trade rows) — small payload regardless of how many trades exist. Runs only on
# a button click, never automatically on every scan.
#
# Model note: the original design called for "claude-sonnet-4-6" (a real, valid,
# one-generation-behind model). Using "claude-sonnet-5" instead — the current model
# in the same mid-cost "Sonnet" tier the design intended (not the upmarket "Opus"
# tier), and cheaper per-token than 4.6.

ANTHROPIC_COACH_MODEL = "claude-sonnet-5"


def _anthropic_configured():
    # Mirrors twelvedata_configured()/_github_configured()'s established
    # pattern in this file: st.secrets.__contains__ raises
    # StreamlitSecretNotFoundError (not just a missing-key False) when no
    # secrets.toml exists at all - a bare `"X" not in st.secrets`/`st.secrets[...]`
    # crashes the whole app in that state, so every access here goes through
    # a try/except, never a bare lookup.
    try:
        return bool(st.secrets.get("ANTHROPIC_API_KEY"))
    except Exception:
        return False


def _anthropic_key():
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _table_exists(con, name):
    r = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return r is not None


def ensure_coach_table():
    con = _db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS coach_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            total_backtest_trades INTEGER,
            total_forward_closed INTEGER,
            report_text TEXT,
            verdict TEXT
        )""")
        con.commit()
    finally:
        con.close()

ensure_coach_table()


def build_coach_payload():
    """Compiles a compact JSON-able summary of everything the Coach needs:
    edge table, component weights, backtest performance, forward-test
    resolution stats (including fundamental/SMC strategies if present).
    Returns (payload:dict, has_enough_data:bool).
    """
    payload = {}

    # --- Backtest performance per strategy ---
    con = _db()
    try:
        bt_summary = pd.read_sql_query(
            "SELECT * FROM backtest_trades", con
        ) if _table_exists(con, "backtest_trades") else pd.DataFrame()
    except Exception:
        bt_summary = pd.DataFrame()
    finally:
        con.close()

    # NOTE: backtest_trades is the RAW sqlite table (lowercase columns:
    # strategy, r_multiple) - not the "Strategy"/"R" display-renamed columns
    # used elsewhere in the UI. The original patch draft checked for
    # "Strategy" here, which never matches this table and would have silently
    # produced an empty backtest_performance every single run.
    if not bt_summary.empty and "strategy" in bt_summary.columns:
        perf_rows = []
        for strat, g in bt_summary.groupby("strategy"):
            has_r = "r_multiple" in g.columns
            perf_rows.append({
                "strategy": strat, "trades": len(g),
                "win_pct": round(float((g.r_multiple > 0).mean() * 100), 1) if has_r else None,
                "avg_r": round(float(g.r_multiple.mean()), 3) if has_r else None,
            })
        payload["backtest_performance"] = perf_rows
    else:
        payload["backtest_performance"] = []

    # --- Adaptive edge table (score-band level win%/avg R) ---
    edge = adaptive_edge_table("INDIA")
    payload["edge_by_score_band"] = edge.to_dict(orient="records") if not edge.empty else []

    # --- Component-level correlation with R ---
    comp = adaptive_component_weights("INDIA")
    payload["component_weights"] = comp.to_dict(orient="records") if not comp.empty else []

    # --- Forward test resolution (the real-world check) ---
    con = _db()
    try:
        ft = pd.read_sql_query("SELECT * FROM forward_tests", con)
    finally:
        con.close()

    closed = ft[ft.status.isin(["CLOSED", "TARGET", "STOP", "EXIT", "EXPIRED"])] if not ft.empty else pd.DataFrame()
    active = ft[ft.status == "ACTIVE"] if not ft.empty else pd.DataFrame()

    fwd_rows = []
    if not closed.empty:
        for strat, g in closed.groupby("strategy"):
            fwd_rows.append({
                "strategy": strat, "closed_trades": len(g),
                "win_pct": round(float((g.result_r > 0).mean() * 100), 1) if g.result_r.notna().any() else None,
                "avg_r": round(float(g.result_r.dropna().mean()), 3) if g.result_r.notna().any() else None,
            })
    payload["forward_test_closed"] = fwd_rows
    payload["forward_test_active_count"] = int(len(active))
    payload["forward_test_closed_count"] = int(len(closed))

    total_bt = len(bt_summary)
    total_fwd_closed = len(closed)
    has_enough = total_bt >= 20 or total_fwd_closed >= 10

    payload["totals"] = {"backtest_trades": total_bt, "forward_closed": total_fwd_closed}
    return payload, has_enough


def run_strategy_coach():
    """Sends the aggregated payload to Claude, gets back a written analysis.
    Returns (report_text:str, error:str or None).
    """
    if not _anthropic_configured():
        return None, "ANTHROPIC_API_KEY not set in Streamlit secrets."

    payload, has_enough = build_coach_payload()
    if not has_enough:
        return None, (
            f"Not enough data yet for a reliable analysis "
            f"({payload['totals']['backtest_trades']} backtest trades, "
            f"{payload['totals']['forward_closed']} closed forward tests). "
            f"Run more backtests or let more forward tests resolve first."
        )

    system_prompt = """You are a quantitative trading systems analyst reviewing a solo trader's
algorithmic research framework. You will receive aggregated statistics (NOT raw trade data) about:
- backtest_performance: win rate / avg R per strategy (S1-S4 = stock strategies, FUNDA/FUNDB =
  fundamental screens, FX_SMC = forex/crypto price action strategy)
- edge_by_score_band: empirical win rate and avg R-multiple by setup-score band, per strategy
  (uses Bayesian shrinkage toward 50%/0R for small samples already)
- component_weights: whether each scoring component (HTF, Footprint, Entry Quality, Relative
  Strength, Safety) shows a real difference in outcome between its high vs low values
- forward_test_closed / forward_test_active_count: REAL live-market outcomes, the most
  trustworthy signal since it isn't backtest-fitted

Your job: give an honest, statistically grounded verdict on whether the marking/scoring system
is working, and concrete recommendations to improve accuracy. Rules:
1. ALWAYS state sample sizes next to any claim. Never treat n<20 as reliable evidence.
2. If backtest and forward-test results diverge meaningfully, flag this explicitly — it usually
   means curve-fitting or regime drift, and is the single most important thing to surface.
3. For components with weight near 1.0 and high sample size, say plainly that they show no
   measurable edge and are candidates to deprioritize or drop from scoring.
4. Do not recommend specific numeric parameter changes unless the sample size genuinely
   supports it — say "not enough data yet" rather than guessing.
5. Structure your response with these headers: OVERALL VERDICT, WHAT'S WORKING, WHAT'S NOT
   WORKING, SPECIFIC RECOMMENDATIONS (numbered, priority order), CONFIDENCE CAVEATS.
6. Keep it concise and actionable — this is read by the developer, not published.
"""

    user_content = "Here is the current aggregated system data:\n\n" + json.dumps(payload, indent=2, default=str)

    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        report = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not report:
            return None, "Claude API returned an empty response."
        return report, None
    except anthropic.AuthenticationError as e:
        return None, f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return None, f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return None, f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return None, f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"


def save_coach_report(report_text):
    payload, _ = build_coach_payload()
    verdict_line = ""
    lines = report_text.splitlines()
    for idx, line in enumerate(lines):
        if "OVERALL VERDICT" in line.upper():
            rest = lines[idx+1:idx+3]
            verdict_line = " ".join(rest).strip()[:300]
            break
    con = _db()
    try:
        con.execute(
            """INSERT INTO coach_reports(created_at, total_backtest_trades, total_forward_closed, report_text, verdict)
               VALUES(?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"),
             payload["totals"]["backtest_trades"], payload["totals"]["forward_closed"],
             report_text, verdict_line)
        )
        con.commit()
    finally:
        con.close()


# ========================= 5-AGENT AI TRADE DEBATE PANEL — Phase 8 =========================
# Analyzes individual TRADE CANDIDATES from the scanner's forward-test queue (different
# job from the AI System Coach above, which analyzes the whole system). Meant to run
# after a scan, on the filtered shortlist that already qualifies for forward testing,
# before capital is committed.
#
# COST CONTROL: NOT 5 agents x N candidates. Four agents each get ALL shortlisted
# candidates in ONE message, returning a JSON array of verdicts; the Judge gets all
# four verdict-arrays plus the original data in one final call. Total = 5 API calls
# per panel run regardless of shortlist size (capped at 15 candidates below).
#
# JSON ROBUSTNESS: the installed anthropic SDK (checked in this environment, not
# guessed) exposes `output_config={"format": {"type": "json_schema", "schema": ...}}`
# on messages.create() (see anthropic.types.output_config_param /
# json_output_format_param), so every agent call below constrains its response to a
# JSON array matching an explicit schema. Fence-stripping + json.loads() is still kept
# as a defensive second layer (harmless when the schema already produced clean JSON,
# a real safety net if some future SDK/account combination doesn't honor the schema) -
# no live-credentialed run of this exact call has been possible in this sandbox, so
# both layers stay in rather than betting everything on the unverified end-to-end path.

_AGENT_VERDICT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "verdict": {"type": "string"},
            "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "flag": {"type": "boolean"},
        },
        "required": ["ticker", "verdict", "confidence", "flag"],
        "additionalProperties": False,
    },
}

_JUDGE_VERDICT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "rank": {"type": "integer"},
            "reasoning": {"type": "string"},
            "overall_confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        },
        "required": ["ticker", "rank", "reasoning", "overall_confidence"],
        "additionalProperties": False,
    },
}


def build_debate_shortlist(scan_result_df, max_candidates=15):
    """Filters scan results down to a cost-bounded shortlist: drops
    INSUFFICIENT SAMPLE learning confidence when better options exist,
    sorts by Learned Rank, caps at max_candidates.
    """
    if scan_result_df is None or scan_result_df.empty:
        return pd.DataFrame()

    df = scan_result_df.copy()
    good_conf = df[df.get("Learning Confidence", "") != "INSUFFICIENT SAMPLE"]
    pool = good_conf if len(good_conf) >= 3 else df  # fallback if too few confident ones

    sort_col = "Learned Rank" if "Learned Rank" in pool.columns else "Score"
    return pool.sort_values(sort_col, ascending=False).head(max_candidates).reset_index(drop=True)


def _candidates_to_payload(shortlist_df):
    cols = ["Ticker", "Strategy", "Score", "Adaptive Score", "Learned Rank", "Historical Edge R",
            "Learning Confidence", "Entry", "SL 7%", "Target 3R", "RSI", "RelVol",
            "HTF Score", "Footprint Score", "Entry Quality", "Relative Strength",
            "Safety Score", "Safety Flags", "Regime"]
    available = [c for c in cols if c in shortlist_df.columns]
    return shortlist_df[available].to_dict(orient="records")


def _call_agent(system_prompt, candidates_payload, max_tokens=2500):
    """Sends one candidates_payload (list of dicts) to Claude with the given
    system_prompt, expecting back a JSON array of {ticker, verdict,
    confidence, flag} objects — one per candidate. Returns (list, error).
    """
    if not _anthropic_configured():
        return [], "ANTHROPIC_API_KEY not set in Streamlit secrets."

    user_content = (
        "Analyze EVERY candidate below and return a JSON array, one object per "
        "candidate, each with exactly these keys: \"ticker\", \"verdict\" (2-3 "
        "sentences), \"confidence\" (LOW/MEDIUM/HIGH), \"flag\" (true if this is a "
        "serious concern, false otherwise).\n\n"
        + json.dumps(candidates_payload, indent=2, default=str)
    )
    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": _AGENT_VERDICT_SCHEMA}},
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return [], "Agent did not return a JSON array."
        return parsed, None
    except json.JSONDecodeError as e:
        return [], f"Could not parse agent response as JSON: {e}"
    except anthropic.AuthenticationError as e:
        return [], f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return [], f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return [], f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return [], f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"


def agent_technical_analyst(candidates_payload):
    system = """You are a Technical Analyst reviewing deterministic strategy setups from an
Indian equities trading system. Each candidate already PASSED all mandatory rules of its
strategy (S1-S4) — your job is not to re-qualify them, but to assess RELATIVE setup quality
using the component scores provided: HTF Score (higher-timeframe demand), Footprint Score,
Entry Quality, Relative Strength, RSI, RelVol. Identify which candidates have genuinely clean,
well-supported setups versus which merely cleared the minimum bar. Be specific about which
component(s) drive your view for each candidate."""
    return _call_agent(system, candidates_payload)


def agent_statistical_skeptic(candidates_payload):
    system = """You are a Statistical Skeptic reviewing trade candidates from a system that
tracks empirical win rates with Bayesian shrinkage. Each candidate includes: Score, Learned
Rank (blends score + historical edge), Historical Edge R (shrunk average R-multiple for this
strategy/score-band), and Learning Confidence (HIGH = 100+ samples, MEDIUM = 20-99, INSUFFICIENT
SAMPLE = under 20). Your ONLY job: flag any candidate whose apparent edge you don't trust yet
due to small sample size, and separately note any candidate where the historical edge is both
strong AND well-sampled (genuinely trustworthy). Be blunt about which numbers are noise."""
    return _call_agent(system, candidates_payload)


def agent_risk_capital(candidates_payload, capital=None, max_slots=None, risk_pct=None):
    context = ""
    if capital and max_slots:
        context = (f"\n\nTrader's context: total capital ₹{capital:,.0f}, max {max_slots} "
                    f"concurrent positions, risking {risk_pct or 1.0}% of capital per trade. "
                    f"Each candidate's SL 7% and Target 3R fields define its risk unit.")
    system = ("""You are a Risk & Capital Agent. Given a trader's available capital and maximum
concurrent position count, assess whether taking ALL of these candidates together would create
excessive concentration — same sector, correlated stocks, or too many positions for the stated
capital to size properly. Flag any candidate that should be deprioritized purely for portfolio
construction reasons, even if its setup looks technically fine on its own."""
              + context)
    return _call_agent(system, candidates_payload)


def agent_devils_advocate(candidates_payload):
    system = """You are the Devil's Advocate / Bear Case agent. Your job is to argue AGAINST
each candidate, specifically — not generic caution, but the single most likely way this specific
setup fails: regime risk, crowded trade, weak relative strength despite a passing score, thin
liquidity (low RelVol), safety flags present, or anything else in the data that a purely bullish
read would gloss over. If a candidate genuinely has no strong bear case, say so plainly rather
than inventing one — false negatives here are as costly as missed risks."""
    return _call_agent(system, candidates_payload)


def agent_judge(candidates_payload, tech_verdicts, skeptic_verdicts, risk_verdicts, bear_verdicts, target_count=5):
    if not _anthropic_configured():
        return [], "ANTHROPIC_API_KEY not set in Streamlit secrets."

    system = f"""You are the Judge/Synthesizer. You will receive the original candidate data plus
four independent agent verdicts per candidate: Technical Analyst, Statistical Skeptic, Risk/Capital
Agent, and Devil's Advocate. Resolve disagreements using judgment, weighting the Statistical
Skeptic's confidence flags heavily (don't rank a candidate highly if its edge is statistically
unreliable, regardless of how clean the setup looks technically). Output a JSON array of the TOP
{target_count} candidates (fewer if fewer than {target_count} are genuinely defensible — never pad
the list with weak picks), each object with keys: "ticker", "rank" (1 = best), "reasoning" (2-3
sentences synthesizing the four views), "overall_confidence" (LOW/MEDIUM/HIGH)."""

    user_content = json.dumps({
        "candidates": candidates_payload,
        "technical_analyst_verdicts": tech_verdicts,
        "statistical_skeptic_verdicts": skeptic_verdicts,
        "risk_capital_verdicts": risk_verdicts,
        "devils_advocate_verdicts": bear_verdicts,
    }, indent=2, default=str)

    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": _JUDGE_VERDICT_SCHEMA}},
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return [], "Judge did not return a JSON array."
        return parsed, None
    except json.JSONDecodeError as e:
        return [], f"Could not parse Judge response as JSON: {e}"
    except anthropic.AuthenticationError as e:
        return [], f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return [], f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return [], f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return [], f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"


def run_trade_debate_panel(scan_result_df, capital=None, max_slots=None, risk_pct=None, target_count=5, max_candidates=15):
    """Full pipeline: shortlist -> 4 parallel-in-spirit agent calls -> Judge.
    Returns dict with keys: shortlist_df, tech, skeptic, risk, bear (each a
    list of verdict dicts), final (Judge's ranked list), errors (list of any
    agent errors encountered — non-fatal, panel continues with what it has).
    """
    shortlist = build_debate_shortlist(scan_result_df, max_candidates=max_candidates)
    if shortlist.empty:
        return {"error": "No candidates available to analyze. Run a scan first."}

    payload = _candidates_to_payload(shortlist)
    errors = []

    tech, e1 = agent_technical_analyst(payload)
    if e1: errors.append(f"Technical Analyst: {e1}")

    skeptic, e2 = agent_statistical_skeptic(payload)
    if e2: errors.append(f"Statistical Skeptic: {e2}")

    risk, e3 = agent_risk_capital(payload, capital, max_slots, risk_pct)
    if e3: errors.append(f"Risk/Capital Agent: {e3}")

    bear, e4 = agent_devils_advocate(payload)
    if e4: errors.append(f"Devil's Advocate: {e4}")

    final, e5 = agent_judge(payload, tech, skeptic, risk, bear, target_count=target_count)
    if e5: errors.append(f"Judge: {e5}")

    return {
        "shortlist_df": shortlist,
        "tech": tech, "skeptic": skeptic, "risk": risk, "bear": bear,
        "final": final, "errors": errors,
    }


# ========================= ML WIN PROBABILITY =========================
# Trained on learning_observations (completed backtest/forward-test trades).
# Falls back to the existing score-band edge table (adaptive_edge_table) when
# there isn't yet enough completed evidence to trust a classifier.

ML_MIN_SAMPLES = 60
ML_MIN_CLASS_SAMPLES = 15
ML_FEATURE_COLUMNS = [
    "score", "htf", "footprint", "strategy_score",
    "entry_quality", "relative_strength", "safety_score"
]

@st.cache_resource(ttl=1800, show_spinner=False)
def train_win_probability_model(market="INDIA"):
    """Fit a win-probability classifier on completed learning_observations.

    Returns a dict:
      ready=False, n_samples=<n>, min_samples=<needed> when there isn't
      enough completed evidence yet (or scikit-learn/data is unavailable) —
      callers should fall back to adaptive_edge_table()/current_candidate_edge().
      ready=True with the fitted models, feature schema, and honest
      out-of-sample reliability metrics (AUC / Brier score) otherwise.
    """
    result = {"ready": False, "n_samples": 0, "min_samples": ML_MIN_SAMPLES}
    q = learning_snapshot(market)
    if q.empty or "result_r" not in q.columns:
        return result
    q = q.dropna(subset=["result_r"]).copy()
    result["n_samples"] = len(q)
    if len(q) < ML_MIN_SAMPLES:
        return result

    q["win"] = (pd.to_numeric(q["result_r"], errors="coerce") > 0).astype(int)
    if q.win.sum() < ML_MIN_CLASS_SAMPLES or (len(q)-q.win.sum()) < ML_MIN_CLASS_SAMPLES:
        result["reason"] = "Not enough win/loss diversity yet"
        return result

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import roc_auc_score, brier_score_loss
    except ImportError:
        result["reason"] = "scikit-learn is not installed"
        return result

    x_num = q[ML_FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    strat_dummies = pd.get_dummies(q["strategy"].astype(str).str.upper(), prefix="strategy")
    regime_dummies = pd.get_dummies(q["regime"].astype(str), prefix="regime")
    X = pd.concat([x_num, strat_dummies, regime_dummies], axis=1).fillna(0.0)
    y = q["win"].to_numpy()

    try:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
    except ValueError:
        X_train, X_test, y_train, y_test = X, X, y, y

    gbc = GradientBoostingClassifier(random_state=42)
    gbc.fit(X_train, y_train)
    logit = LogisticRegression(max_iter=1000)
    logit.fit(X_train, y_train)

    def _reliability(model):
        p = model.predict_proba(X_test)[:, 1]
        try:
            auc = float(roc_auc_score(y_test, p))
        except ValueError:
            auc = np.nan
        return auc, float(brier_score_loss(y_test, p))

    gbc_auc, gbc_brier = _reliability(gbc)
    logit_auc, logit_brier = _reliability(logit)

    # Refit on the full dataset for production inference; the held-out split
    # above is only used to report honest reliability metrics.
    gbc.fit(X, y)
    logit.fit(X, y)

    result.update({
        "ready": True,
        "gbc_model": gbc,
        "logit_model": logit,
        "feature_columns": list(X.columns),
        "gbc_auc": gbc_auc, "gbc_brier": gbc_brier,
        "logit_auc": logit_auc, "logit_brier": logit_brier,
    })
    return result

def ml_win_probability(model_info, row):
    """O(1) inference of win probability (0-100) for one candidate row using a
    model dict from train_win_probability_model(). `row` may use either the
    learning_observations naming (score/htf/...) or scanner naming
    (Score/HTF Score/...). Returns np.nan when the model isn't ready."""
    if not model_info or not model_info.get("ready"):
        return np.nan

    def g(*keys, default=0.0):
        for k in keys:
            v = row.get(k) if hasattr(row, "get") else None
            if v is not None and pd.notna(v):
                return v
        return default

    feat = {
        "score": g("score", "Score"),
        "htf": g("htf", "HTF Score", "HTF Demand", "HTF"),
        "footprint": g("footprint", "Footprint Score", "Footprint"),
        "strategy_score": g("strategy_score", "Strategy Score"),
        "entry_quality": g("entry_quality", "Entry Quality"),
        "relative_strength": g("relative_strength", "Relative Strength"),
        "safety_score": g("safety_score", "Safety Score"),
    }
    strategy = str(g("strategy", "Strategy", default="")).upper()
    regime = str(g("regime", "Regime", default=""))

    x = pd.DataFrame([feat])
    x[f"strategy_{strategy}"] = 1.0
    x[f"regime_{regime}"] = 1.0
    x = x.reindex(columns=model_info["feature_columns"], fill_value=0.0)
    try:
        p = model_info["gbc_model"].predict_proba(x)[0, 1]
        return float(round(p*100, 1))
    except Exception:
        return np.nan


# ========================= STRATEGY COACH =========================
# Analyzes completed learning_observations per strategy: regime win-rate/avg-R
# breakdown, high-vs-low component splits, and a shallow (max_depth<=3)
# decision tree translated into plain-English rules. Never rewrites strategy
# rules — this is read-only evidence with explicit sample-size caveats.

STRATEGY_COACH_MIN_SAMPLES = 20
STRATEGY_COACH_TREE_MIN_SAMPLES = 40

def strategy_coach_regime_breakdown(q):
    g = q.groupby("regime").agg(
        Samples=("result_r", "count"),
        WinRate=("win", "mean"),
        AvgR=("result_r", "mean"),
    ).reset_index().rename(columns={"regime": "Regime"})
    g["WinRate"] = (g.WinRate * 100).round(1)
    g["AvgR"] = g.AvgR.round(3)
    return g.sort_values("Samples", ascending=False)

def strategy_coach_component_breakdown(q):
    rows = []
    for c in ML_FEATURE_COLUMNS:
        if c not in q.columns:
            continue
        vals = pd.to_numeric(q[c], errors="coerce")
        med = vals.median()
        if pd.isna(med):
            continue
        hi = q[vals >= med]; lo = q[vals < med]
        if len(hi) == 0 or len(lo) == 0:
            continue
        rows.append({
            "Component": c.replace("_", " ").title(),
            "High Samples": len(hi), "High Win %": round(float(hi.win.mean()) * 100, 1),
            "High Avg R": round(float(hi.result_r.mean()), 3),
            "Low Samples": len(lo), "Low Win %": round(float(lo.win.mean()) * 100, 1),
            "Low Avg R": round(float(lo.result_r.mean()), 3),
        })
    return pd.DataFrame(rows)

def _coach_pretty_feature(name):
    if name.startswith("regime_"):
        return f"Regime == {name[len('regime_'):]}"
    return name.replace("_", " ").upper()

def _coach_extract_tree_rules(tree, feature_names, min_leaf_samples):
    from sklearn.tree import _tree
    t = tree.tree_
    leaves = []
    def recurse(node, path):
        if t.feature[node] != _tree.TREE_UNDEFINED:
            name = feature_names[t.feature[node]]
            thresh = t.threshold[node]
            recurse(t.children_left[node], path + [(name, "<=", thresh)])
            recurse(t.children_right[node], path + [(name, ">", thresh)])
        else:
            n = int(t.n_node_samples[node])
            # tree_.value stores per-node class PROPORTIONS (rows sum to 1),
            # not raw counts, so this is already the leaf's win rate.
            win_rate = float(t.value[node][0][1]) if t.value[node].shape[1] > 1 else 0.0
            leaves.append((path, n, win_rate))
    recurse(0, [])
    leaves.sort(key=lambda x: (-x[2], -x[1]))
    rules = []
    for path, n, win_rate in leaves:
        if n < min_leaf_samples:
            continue
        desc = " AND ".join(f"{_coach_pretty_feature(nm)} {op} {th:.1f}" for nm, op, th in path) or "Overall population"
        rules.append({"Rule": desc, "Samples": n, "Win Rate %": round(win_rate * 100, 1)})
    return rules[:5]

def strategy_coach_tree_rules(q, max_depth=3, min_samples=STRATEGY_COACH_TREE_MIN_SAMPLES):
    """Fit a shallow decision tree and translate its leaves into plain-English
    rules, most winning first. Returns (rules, note); note explains why rules
    are empty when there isn't enough evidence yet."""
    if len(q) < min_samples:
        return [], f"Need ≥{min_samples} completed observations to extract rules; have {len(q)}."
    try:
        from sklearn.tree import DecisionTreeClassifier
    except ImportError:
        return [], "scikit-learn is not installed."
    feat_cols = [c for c in ML_FEATURE_COLUMNS if c in q.columns]
    x_num = q[feat_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    regime_dummies = pd.get_dummies(q["regime"].astype(str), prefix="regime")
    X = pd.concat([x_num, regime_dummies], axis=1)
    y = q["win"].to_numpy()
    if y.sum() < 5 or (len(y) - y.sum()) < 5:
        return [], "Not enough win/loss diversity to extract rules yet."
    min_leaf = max(10, len(q) // 20)
    tree = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=min_leaf, random_state=42)
    tree.fit(X, y)
    rules = _coach_extract_tree_rules(tree, list(X.columns), min_leaf)
    if not rules:
        return [], "No leaf had enough samples to report as a reliable rule."
    return rules, None

def strategy_coach_report(market, strategy):
    """Full read-only coaching report for one strategy, or None when there
    isn't at least one completed observation to analyze."""
    q = learning_snapshot(market)
    if q.empty or "strategy" not in q.columns:
        return None
    q = q[q.strategy.astype(str).str.upper() == str(strategy).upper()].copy()
    q = q.dropna(subset=["result_r"])
    if q.empty:
        return None
    q["result_r"] = pd.to_numeric(q["result_r"], errors="coerce")
    q = q.dropna(subset=["result_r"])
    if q.empty:
        return None
    q["win"] = (q.result_r > 0).astype(int)
    n = len(q)
    enough = n >= STRATEGY_COACH_MIN_SAMPLES
    rules, rule_note = strategy_coach_tree_rules(q)
    return {
        "strategy": strategy, "n_samples": n, "enough_for_breakdown": enough,
        "overall_win_rate": round(float(q.win.mean()) * 100, 1),
        "overall_avg_r": round(float(q.result_r.mean()), 3),
        "regime_breakdown": strategy_coach_regime_breakdown(q) if enough else pd.DataFrame(),
        "component_breakdown": strategy_coach_component_breakdown(q) if enough else pd.DataFrame(),
        "tree_rules": rules, "tree_note": rule_note,
    }


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

S4_EXTENSION_BUCKETS = [
    (-100.0, 0.0, "At/below EMA20"),
    (0.0, 3.0, "0-3% above (exact S4 rule)"),
    (3.0, 6.0, "3-6% above"),
    (6.0, 10.0, "6-10% above"),
    (10.0, 15.0, "10-15% above"),
    (15.0, 25.0, "15-25% above"),
    (25.0, 1000.0, ">25% above"),
]
S4_CALIBRATION_MIN_BUCKET_SAMPLES = 15

def s4_ema20_extension_calibration(data, start_date, end_date, sl_pct=0.07, target_r=3.0):
    """Backtest every exact Strategy 4 condition EXCEPT the fixed
    close<=1.03*EMA20 rule (via s4_base_conditions), and record how far above
    or below EMA20 price actually was at each qualifying signal, plus the
    resulting trade outcome. This is the raw evidence behind
    s4_extension_bucket_report() - it does not itself assume 3% is correct."""
    rows=[]; start=pd.Timestamp(start_date); end=pd.Timestamp(end_date)
    for ticker,df in data.items():
        if df is None or len(df)<260: continue
        try:
            df=df.sort_index(); f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
            if f.empty: continue
            sig=s4_base_conditions(f).fillna(False).to_numpy()
            for i in np.flatnonzero(sig):
                dt=pd.Timestamp(f.index[i])
                if dt<start or dt>end or i>=len(df)-1: continue
                z=f.iloc[i]
                if pd.isna(z.ema20) or z.ema20<=0 or pd.isna(z.close): continue
                extension=(float(z.close)/float(z.ema20)-1)*100
                regime,_=_regime_from_row(f,i)
                entry_i=i+1; entry=float(df.close.iloc[entry_i])
                if not np.isfinite(entry) or entry<=0: continue
                stop=entry*(1-sl_pct); target=entry+target_r*(entry-stop)
                outcome,exit_price,held=_fast_trade_outcome(df,entry_i,stop,target)
                result_r=(exit_price-entry)/(entry-stop) if (entry-stop)>0 else 0.0
                rows.append({
                    'Date':dt.date(),'Ticker':str(ticker).replace('.NS',''),
                    'EMA20 Extension %':round(extension,2),'Regime':regime,
                    'Entry':round(entry,2),'Outcome':outcome,'R':round(float(result_r),3),
                    'Holding Bars':int(held)
                })
        except Exception:
            continue
    return pd.DataFrame(rows)

def s4_extension_bucket_report(cal_df):
    """Bucket s4_ema20_extension_calibration() output by EMA20 distance and
    report win rate/avg R per bucket, flagging which buckets have enough
    samples to be trusted (>=S4_CALIBRATION_MIN_BUCKET_SAMPLES)."""
    if cal_df.empty:
        return pd.DataFrame()
    df=cal_df.copy()
    edges=[b[0] for b in S4_EXTENSION_BUCKETS]+[S4_EXTENSION_BUCKETS[-1][1]]
    labels=[b[2] for b in S4_EXTENSION_BUCKETS]
    df["Bucket"]=pd.cut(df["EMA20 Extension %"],bins=edges,labels=labels,include_lowest=True)
    df["Win"]=(df.R>0).astype(int)
    g=df.groupby("Bucket",observed=False).agg(
        Samples=("R","count"), WinRate=("Win","mean"), AvgR=("R","mean"), TotalR=("R","sum")
    ).reset_index()
    g["WinRate"]=(g.WinRate*100).round(1); g["AvgR"]=g.AvgR.round(3); g["TotalR"]=g.TotalR.round(2)
    g["Reliable (>=%d samples)"%S4_CALIBRATION_MIN_BUCKET_SAMPLES]=g.Samples>=S4_CALIBRATION_MIN_BUCKET_SAMPLES
    return g

def s4_custom_dsl_from_bucket(bucket_label):
    """Render a Custom Strategy DSL rule set replicating S4's other
    conditions with the learned EMA20 distance swapped in for the fixed 3%
    rule. The DSL is AND-only, so the 'OR reclaim' branch of exact S4 is
    approximated by the monthly-cross-count condition alone - this is a
    slightly narrower (fewer false positives, some missed reclaim-only
    setups), not identical, scan."""
    lo, hi, _ = next(b for b in S4_EXTENSION_BUCKETS if b[2] == bucket_label)
    lines = ["MMOM >= 20", "MRSI14 >= 50", "MEMA10 >= MEMA20", "VOL30 >= 50000", "CLOSE >= 20", "M_CROSS_COUNT20 >= 1"]
    if hi < 1000.0:
        lines.append(f"CLOSE <= {round(1+hi/100,3)} * EMA20")
    if lo > -100.0:
        lines.append(f"CLOSE >= {round(1+lo/100,3)} * EMA20")
    return "\n".join(lines)

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
    if added:
        maybe_backup_db()
    return added

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
    "⚡ Live Monitor",
    "💾 Dhan Data Manager",
    "🧪 S4 Recovery Study",
    "🧪 Custom Strategy",
    "🧬 Research & Risk Control",
    "🎓 Strategy Coach",
    "💱 Forex/Crypto SMC"
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

    st.markdown("### 📅 Data Freshness")
    try:
        _freshness_universe=set()
        for u in universes:
            _freshness_universe.update(index_universe(u))
        scan_freshness_tickers=sorted(_freshness_universe)
    except Exception as ex:
        scan_freshness_tickers=[]
        st.caption(f"Could not verify data freshness (index universe fetch failed): {ex}")
    render_data_freshness_banner(scan_freshness_tickers)

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
            with st.spinner(f"Loading local price cache for {len(tickers):,} stocks..."):
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
            ml_model = train_win_probability_model("INDIA")

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
                    # Per-component adaptive weighting (adaptive_candidate_score) was
                    # built but never wired into the scan loop - it was computed
                    # nowhere and had zero effect. This does NOT change which stocks
                    # qualify (already decided by `signal` above) or replace Learned
                    # Rank; it's blended 70% raw / 30% learned inside the function
                    # itself, shown as an independent extra column for comparison.
                    adaptive_score = adaptive_candidate_score(
                        float(score), "INDIA", f"S{s}", parts
                    )
                    row = {
                        "Score": score,
                        "Adaptive Score": round(adaptive_score, 2),
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
                    }
                    win_prob = ml_win_probability(ml_model, row)
                    if pd.isna(win_prob):
                        win_prob = fallback_win_probability("INDIA", f"S{s}", float(score))
                    row["Win Probability %"] = win_prob
                    rows.append(row)

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
                        st.dataframe(_best,width='stretch',hide_index=True)
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
                        st.dataframe(s4counts, width='stretch', hide_index=True)
                        with st.expander("View S4 stock-by-stock audit"):
                            st.dataframe(s4df, width='stretch', hide_index=True)

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
                        st.dataframe(counts, width='stretch', hide_index=True)
                        with st.expander("View S2 stock-by-stock audit"):
                            st.dataframe(audit_df, width='stretch', hide_index=True)


            st.subheader("🧠 ML Win Probability")
            if ml_model.get("ready"):
                m1,m2,m3,m4 = st.columns(4)
                m1.metric("Training samples", ml_model["n_samples"])
                m2.metric("GBC AUC", f"{ml_model['gbc_auc']:.2f}" if np.isfinite(ml_model['gbc_auc']) else "—")
                m3.metric("GBC Brier", f"{ml_model['gbc_brier']:.3f}")
                m4.metric("Logistic AUC (baseline)", f"{ml_model['logit_auc']:.2f}" if np.isfinite(ml_model['logit_auc']) else "—")
                st.caption(
                    "AUC 0.5 = no better than chance, 1.0 = perfect separation. Brier score is mean "
                    "squared error of the probability (lower is better, 0 is perfect). With this few "
                    "samples these numbers can swing a lot run to run — treat them as directional, not final."
                )
            else:
                st.info(
                    f"ML model not trained yet: {ml_model.get('n_samples',0)} completed learning "
                    f"observations, needs ≥{ml_model['min_samples']}"
                    + (f" ({ml_model['reason']})" if ml_model.get('reason') else "")
                    + ". 'Win Probability %' falls back to the score-band historical edge table below "
                      "(Historical Edge R / Learning Confidence) until then."
                )

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
            st.dataframe(diag,width='stretch',hide_index=True)

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
            st.dataframe(pd.DataFrame(cov),width='stretch',hide_index=True)

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
                                    f"HTF {r.get('HTF Score','-')} | "
                                    f"Footprint {r.get('Footprint Score','-')} | "
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
                    st.dataframe(conf,width='stretch',hide_index=True)

                st.subheader("📋 All Qualifying Setups")
                st.dataframe(full_result,width='stretch',hide_index=True)

                forward=full_result[
                    (full_result["Score"]>=min_score) &
                    (full_result["Safety"]!="REJECT")
                ].copy()
                st.subheader(f"🚀 Forward-Test Queue — Score ≥ {min_score}")
                if forward.empty:
                    st.info("No complete-rule setup currently meets the forward-test gate.")
                else:
                    st.dataframe(forward,width='stretch',hide_index=True)
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
                                width='stretch',
                                hide_index=True
                            )

        except Exception as e:
            st.error(f"Scanner error: {e}")

    st.divider()
    st.subheader("🧑‍⚖️ AI Trade Debate Panel")
    st.caption("5 agents (Technical, Statistical Skeptic, Risk/Capital, Devil's Advocate, Judge) analyze the scanner's forward-test queue. 5 API calls total per run, regardless of shortlist size.")

    # "forward_queue" is the actual session_state key the scanner populates with
    # its forward-test-qualifying shortlist (Score >= min_score, Safety != REJECT)
    # right before calling add_forward_candidates() above - there is no session_state
    # key holding the full unfiltered scan result (full_result is a local variable,
    # not persisted across reruns), so this is the closest and most fitting analog:
    # it's exactly the "before you commit capital" shortlist this panel is meant to
    # analyze, not the raw universe of every strategy-qualified setup.
    panel_result = st.session_state.get('forward_queue', pd.DataFrame())
    if panel_result.empty:
        st.info("Run a scan first — the panel analyzes the scanner's forward-test queue (Score above the gate).")
    elif not _anthropic_configured():
        st.info("ANTHROPIC_API_KEY not set in Streamlit secrets — add it to enable this section.")
    else:
        pc1, pc2, pc3 = st.columns(3)
        panel_capital = pc1.number_input("Capital ₹", 10000, 100000000, 100000, 10000, key="panel_capital")
        panel_slots = pc2.number_input("Max concurrent positions", 1, 20, 5, 1, key="panel_slots")
        panel_target = pc3.slider("Final shortlist size", 2, 6, 5, 1, key="panel_target")

        if st.button("🔬 RUN 5-AGENT DEBATE PANEL", type="primary", key="panel_run"):
            with st.spinner("Running 5-agent analysis (5 API calls)..."):
                panel = run_trade_debate_panel(
                    panel_result, capital=panel_capital, max_slots=panel_slots,
                    risk_pct=1.0, target_count=panel_target
                )
            st.session_state["latest_panel"] = panel

        panel = st.session_state.get("latest_panel")
        if panel:
            if panel.get("error"):
                st.warning(panel["error"])
            else:
                if panel["errors"]:
                    st.warning("Some agents had issues: " + " | ".join(panel["errors"]))

                if panel["final"]:
                    st.subheader("🏆 Judge's Final Ranking")
                    st.dataframe(pd.DataFrame(panel["final"]), width='stretch', hide_index=True)

                with st.expander("🔍 View individual agent verdicts"):
                    vt1, vt2, vt3, vt4 = st.tabs(["Technical", "Statistical Skeptic", "Risk/Capital", "Devil's Advocate"])
                    with vt1:
                        st.dataframe(pd.DataFrame(panel["tech"]), width='stretch', hide_index=True) if panel["tech"] else st.info("No data.")
                    with vt2:
                        st.dataframe(pd.DataFrame(panel["skeptic"]), width='stretch', hide_index=True) if panel["skeptic"] else st.info("No data.")
                    with vt3:
                        st.dataframe(pd.DataFrame(panel["risk"]), width='stretch', hide_index=True) if panel["risk"] else st.info("No data.")
                    with vt4:
                        st.dataframe(pd.DataFrame(panel["bear"]), width='stretch', hide_index=True) if panel["bear"] else st.info("No data.")

# ========================= RESEARCH MODULES =========================

def refresh_forward_positions():
    """Update active forward records using only locally stored daily candles."""
    con=_db()
    try:
        active=pd.read_sql_query(
            """SELECT id,created_at,signal_date,symbol,strategy,score,regime,entry,sl,target
               FROM forward_tests WHERE status='ACTIVE' ORDER BY created_at DESC""",con
        )
    finally: con.close()
    if active.empty:return 0,0

    today=last_expected_nse_session(); updates=0
    newly_closed=[]
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
                newly_closed.append({
                    "symbol": s, "strategy": str(r.strategy), "signal_time": str(signal_date),
                    "score": float(r.score), "regime": str(r.regime), "entry": entry,
                    "exit_price": exitp, "result_r": result_r,
                    "outcome": "WIN" if status == "TARGET" else "LOSS" if status == "STOP" else status,
                    "holding_minutes": held * 24 * 60,  # daily-bar strategy; bars converted to minutes for schema consistency
                })
            else:
                con.execute("""UPDATE forward_tests SET ltp=?,mfe=?,mae=?,updated_at=? WHERE id=?""",
                            (close,mfe,mae,datetime.now().isoformat(timespec="seconds"),int(r.id)))
            updates+=1
        con.commit()
    finally: con.close()

    # Feed the learning DB only after the connection above is committed and
    # closed, so this never contends with it for the SQLite write lock.
    # Previously forward-test outcomes closed here (forward_tests/forward_results)
    # but never reached learning_observations at all - the learning engine only
    # ever learned from backtests, never from real forward performance.
    for trade in newly_closed:
        _record_learning_trade("INDIA", trade, source="forward")

    return updates, len(newly_closed)

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
    # SQLite AVG()/SUM() return NULL when every row is still ACTIVE (no closed
    # trades yet for that strategy), which pd.read_sql_query surfaces as an
    # object-dtype column of Nones rather than numeric NaN — .round() raises
    # TypeError on an object dtype, so coerce to numeric first.
    for col in ["AvgR","TotalR","AvgROIProxy","AvgMFE","AvgMAE"]:
        q[col]=pd.to_numeric(q[col],errors="coerce")
    q["Win %"]=np.where((q["Wins"]+q["Losses"])>0,q["Wins"]/(q["Wins"]+q["Losses"])*100,np.nan)
    q["Status"]=np.where(q["Closed"]<3,"BUILDING SAMPLE",
                         np.where(q["AvgR"]>0.75,"STRONG",
                                  np.where(q["AvgR"]>0.2,"POSITIVE",
                                           np.where(q["AvgR"]>-0.1,"NEUTRAL","WEAK"))))
    q["AvgR"]=q["AvgR"].round(3);q["TotalR"]=q["TotalR"].round(2)
    q["Win %"]=pd.to_numeric(q["Win %"],errors="coerce").round(1)
    q["AvgMFE"]=q["AvgMFE"].round(2);q["AvgMAE"]=q["AvgMAE"].round(2)
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
    tickers=[]
    if universes:
        try:
            tickers=sorted(set(sum([index_universe(u) for u in universes],[])))
        except Exception as e:
            st.error(f"Could not load index universe constituents (network/data issue): {e}")
    st.info(f"{period} | Signal window {start_date} → {end_date} | Warm-up {data_start} → {start_date} | {len(tickers):,} stocks | S1–S4 | local SQLite only | forward gate ≥{threshold}")

    st.markdown("### 📅 Data Freshness")
    render_data_freshness_banner(tickers)

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
        st.dataframe(bt.sort_values(["Score","Date"],ascending=[False,False]),width='stretch',hide_index=True)

        st.subheader("📈 Strategy Performance / ROI / Risk")
        perf=[]
        for strat,g in bt.groupby('Strategy'):
            wins=g[g['R']>0];loss=g[g['R']<=0];grossw=float(wins['R'].sum());grossl=abs(float(loss['R'].sum()))
            pf=grossw/grossl if grossl>0 else (99.99 if grossw>0 else 0)
            perf.append({'Strategy':strat,'Trades':len(g),'Win %':round((g.R>0).mean()*100,1),'Avg R':round(g.R.mean(),3),'Total R':round(g.R.sum(),2),'Profit Factor':round(pf,2),'Avg Return %':round(g['Return %'].mean(),2),'Avg MFE %':round(g['MFE %'].mean(),2),'Avg MAE %':round(g['MAE %'].mean(),2),'Best Score':int(g.Score.max())})
        st.dataframe(pd.DataFrame(perf).sort_values('Avg R',ascending=False),width='stretch',hide_index=True)

        st.subheader("💰 Capital / ROI Simulation")
        pc1,pc2,pc3=st.columns(3);capital=pc1.number_input("Starting capital ₹",10000,100000000,100000,10000,key='bt_capital');risk_pct=pc2.number_input("Risk per trade %",0.1,5.0,1.0,0.1,key='bt_risk');slots=pc3.number_input("Capital slots",1,50,5,1,key='bt_slots')
        roi=portfolio_from_backtest(bt,float(capital),float(risk_pct),int(slots));st.dataframe(pd.DataFrame([roi]),width='stretch',hide_index=True)

        st.subheader("🎯 Score Learning")
        bands=pd.cut(bt.Score,[84,89,94,100],labels=["85–89","90–94","95–100"],include_lowest=True);bx=bt.assign(Band=bands,Win=(bt.Outcome.str.upper()=='WIN').astype(int))
        learn=bx.groupby('Band',observed=True).agg(Signals=('Ticker','count'),Wins=('Win','sum'),WinRate=('Win','mean'),AvgR=('R','mean'),TotalR=('R','sum'),AvgReturn=('Return %','mean'),AvgMFE=('MFE %','mean'),AvgMAE=('MAE %','mean')).reset_index();learn['WinRate']=(learn.WinRate*100).round(1);learn[['AvgR','TotalR','AvgReturn','AvgMFE','AvgMAE']]=learn[['AvgR','TotalR','AvgReturn','AvgMFE','AvgMAE']].round(2);st.dataframe(learn,width='stretch',hide_index=True)

        st.subheader("🧠 Marking Conditions Used")
        st.info("A row exists only when ALL mandatory rules of its strategy passed. The columns below preserve the score components used to rank the historical setup; the strategy itself is independently re-evaluated from the full rule set.")
        st.dataframe(bt[['Ticker','Date','Strategy','Score','Strategy Score','HTF','Footprint','Trend','Entry Quality','Relative Strength','Safety','Regime','Outcome','R','Return %','MFE %','MAE %','Holding Bars']].sort_values('Score',ascending=False),width='stretch',hide_index=True)

        st.subheader("🔎 Individual Strategy Results")
        stabs=st.tabs(['S1','S2','S3','S4'])
        for tab,ss in zip(stabs,[1,2,3,4]):
            with tab:
                sr=bt[bt.Strategy==f'S{ss}'].sort_values(['Score','Date'],ascending=[False,False])
                if not sr.empty:
                    st.dataframe(sr,width='stretch',hide_index=True)
                else:
                    st.info(f'S{ss}: no qualifying historical setups in this window.')

with tabs[3]:
    st.subheader('🔬 Forward Testing — Persistent Strategy Outcome Tracker')
    changed,newly_closed_count=refresh_forward_positions()
    if newly_closed_count:
        st.success(f"✅ {newly_closed_count} forward test(s) resolved this refresh and recorded to the learning database.")
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
        st.dataframe(ft,width='stretch',hide_index=True)
        st.subheader("🏆 Strategy Performance Scorecard")
        try:
            fs=forward_summary_table()
        except Exception as e:
            fs=pd.DataFrame(); st.error(f"Strategy scorecard error: {e}")
        if not fs.empty: st.dataframe(fs,width='stretch',hide_index=True)
        else: st.info("Waiting for completed forward-test outcomes.")
        st.subheader("🧠 What is being learned")
        st.write("The system tracks strategy, score, regime, entry/stop/target, MFE/MAE, R and final outcome. This is the permanent evidence base for future strategy ranking.")

    st.subheader("🗃️ Persisted Scanner Signals")
    if signals.empty: st.info("No scanner signals saved for the forward-test gate yet.")
    else:
        st.dataframe(signals.head(500),width='stretch',hide_index=True)
        st.download_button("⬇️ Download forward signal history",signals.to_csv(index=False).encode(),"forward_signal_history.csv","text/csv",key="download_forward_history")

with tabs[4]:
    st.subheader("🧠 Adaptive Market Learning")
    try:
        fwd=forward_summary_table()
    except Exception as e:
        fwd=pd.DataFrame(); st.error(f"Forward strategy leaderboard error: {e}")
    if not fwd.empty:
        st.subheader("🏆 Forward Strategy Leaderboard")
        st.dataframe(fwd,width='stretch',hide_index=True)

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
            st.dataframe(_learning_summary(bt),width='stretch',hide_index=True)
            rows=[]
            for c in ['HTF','Footprint','Strategy Score','Safety','Entry Quality','Relative Strength']:
                if c in bt.columns:
                    med=bt[c].median();hi=bt[bt[c]>=med];lo=bt[bt[c]<med]
                    rows.append({'Component':c,'High Samples':len(hi),'High Avg R':round(float(hi.R.mean()),3) if len(hi) else 0,'Low Samples':len(lo),'Low Avg R':round(float(lo.R.mean()),3) if len(lo) else 0,'High Win %':round(float((hi.Outcome.str.upper()=='WIN').mean()*100),1) if len(hi) else 0})
            st.subheader('🔬 Marking Component Learning');st.dataframe(pd.DataFrame(rows),width='stretch',hide_index=True)
        st.subheader('🎯 Adaptive Score Edge')
        edge=adaptive_edge_table('INDIA')
        if not edge.empty:
            st.dataframe(edge,width='stretch',hide_index=True)
        else:
            st.info('Not enough completed observations for adaptive edge estimates.')
        st.subheader('🗄️ Persistent Learning Database')
        st.metric('Completed observations',len(learn_db))
        if not learn_db.empty:
            st.dataframe(adaptive_component_weights('INDIA'),width='stretch',hide_index=True)
            st.dataframe(learn_db.head(500),width='stretch',hide_index=True)
        st.caption('Learning ranks candidates using evidence; it never changes the deterministic S1–S4 qualification rules.')

    st.divider()
    st.subheader("🧑‍🏫 AI System Coach (LLM)")
    st.caption(
        "Different from the 🎓 Strategy Coach tab, which uses deterministic decision-tree rules — "
        "this one is an on-demand LLM analysis of the same underlying data."
    )
    st.caption("On-demand AI analysis of the marking system's accuracy across backtest + forward-test history. One API call per run — you control when it runs.")

    if not _anthropic_configured():
        st.info("ANTHROPIC_API_KEY not set in Streamlit secrets — add it to enable this section.")
    elif st.button("🔬 RUN AI SYSTEM COACH ANALYSIS", type="primary", key="coach_run"):
        with st.spinner("Analyzing backtest performance, forward-test outcomes, and component correlations..."):
            coach_report, coach_err = run_strategy_coach()
        if coach_err:
            st.warning(coach_err)
        else:
            save_coach_report(coach_report)
            st.session_state["latest_coach_report"] = coach_report
            st.success("Analysis complete and saved.")

    latest_coach = st.session_state.get("latest_coach_report")
    if latest_coach:
        st.markdown(latest_coach)

    with st.expander("📜 Report History"):
        con = _db()
        try:
            coach_hist = pd.read_sql_query("SELECT id, created_at, total_backtest_trades, total_forward_closed, verdict FROM coach_reports ORDER BY id DESC", con)
        finally:
            con.close()
        if coach_hist.empty:
            st.info("No reports yet — run your first analysis above.")
        else:
            st.dataframe(coach_hist, width='stretch', hide_index=True)
            coach_pick = st.selectbox("View full report", coach_hist["id"].tolist(), key="coach_history_pick")
            if coach_pick:
                con = _db()
                try:
                    coach_full = con.execute("SELECT report_text FROM coach_reports WHERE id=?", (coach_pick,)).fetchone()
                finally:
                    con.close()
                if coach_full:
                    st.markdown(coach_full[0])

with tabs[5]:
    st.subheader("💎 Long-Term Fundamentals + News")
    st.caption("Dhan remains the primary Indian market-price source. Twelve Data provides fundamentals; Screen A / Screen B run against the full index universe, not just typed symbols.")

    fscreen_tab1, fscreen_tab2 = st.tabs(["📋 Screen A / B — Universe Scan", "🔎 Manual Symbol Lookup"])

    with fscreen_tab1:
        st.info(
            "⚠️ Twelve Data field-name mappings for income_statement/balance_sheet/cash_flow "
            "(and therefore the Piotroski score, ROCE fallback, and every Screen A/B pass/fail below) "
            "are UNVERIFIED assumptions — this deployment has not been checked against a live Twelve "
            "Data key or a real company filing. Spot-check any PASS result against the company's actual "
            "financial statements before acting on it."
        )
        fc1, fc2, fc3 = st.columns([2, 1, 1])
        fund_universes = fc1.multiselect(
            "Universe", ["Nifty 500", "Nifty Smallcap 100", "Nifty Smallcap 250", "Nifty Midcap 150"],
            default=["Nifty 500"], key="fund_screen_universe"
        )
        fund_run_a = fc2.checkbox("Screen A", value=True, key="fund_run_a")
        fund_run_b = fc3.checkbox("Screen B", value=True, key="fund_run_b")

        fund_auto_track = st.checkbox(
            "Auto-track PASS results into Forward Testing", value=True, key="fund_auto_track",
            help="Passing stocks are inserted into the same forward_tests table used by the technical "
                 "scanner (tagged FUNDA/FUNDB) so they can be watched forward, using a local Dhan close "
                 "as entry with a wide 15%/3R stop-target (see add_fundamental_forward_candidates)."
        )

        if st.button("🔬 RUN FUNDAMENTAL SCREENS", type="primary", key="fund_screen_run"):
            if not fund_universes:
                st.warning("Select at least one universe.")
            elif not (fund_run_a or fund_run_b):
                st.warning("Select at least one screen (A and/or B).")
            elif not twelvedata_configured():
                st.error("TWELVEDATA_API_KEY not configured in Streamlit secrets — Screen A/B need Twelve Data fundamentals.")
            else:
                fund_prog = st.progress(0.0, text="Starting scan...")

                def _fund_cb(done, total, sym):
                    fund_prog.progress(done / max(total, 1), text=f"Scanning {sym} ({done}/{total})")

                with st.spinner("Fetching fundamentals — this can take a while for large universes..."):
                    fund_result = run_fundamental_screens(fund_universes, run_a=fund_run_a, run_b=fund_run_b, progress_cb=_fund_cb)

                fund_prog.empty()
                st.session_state["fund_screen_results"] = fund_result

                if fund_auto_track and not fund_result.empty:
                    n_added = add_fundamental_forward_candidates(fund_result)
                    st.success(f"Scan complete. {n_added} new candidate(s) added to Forward Testing.")
                else:
                    st.success("Scan complete.")

        fund_result = st.session_state.get("fund_screen_results", pd.DataFrame())
        if fund_result.empty:
            st.info("Run a screen to see universe-wide fundamental results here.")
        else:
            fund_passed = fund_result[fund_result["Pass"] == True]
            fund_failed = fund_result[fund_result["Pass"] == False]
            fm1, fm2, fm3 = st.columns(3)
            fm1.metric("Scanned", len(fund_result))
            fm2.metric("Passed", len(fund_passed))
            fm3.metric("Failed", len(fund_failed))

            fund_display_cols = [c for c in fund_result.columns if c not in ("Checks",)]
            st.dataframe(
                fund_result[fund_display_cols].sort_values(["Pass", "Screen"], ascending=[False, True]),
                width='stretch', hide_index=True
            )

            if "Unverifiable" in fund_result.columns and fund_result["Unverifiable"].astype(str).str.len().gt(0).any():
                st.warning("Some checks could not be verified (e.g. Promoter Holding — not available via Twelve Data) and were excluded from the Pass/Fail decision rather than assumed true.")

            with st.expander("🔍 View individual stock check breakdown"):
                fund_pick = st.selectbox("Stock", fund_result["Ticker"].unique(), key="fund_screen_detail_pick")
                fund_sub = fund_result[fund_result["Ticker"] == fund_pick]
                for _, frow in fund_sub.iterrows():
                    st.markdown(f"**Screen {frow.get('Screen')}** — {'✅ PASS' if frow.get('Pass') else '❌ FAIL'}")
                    fchecks = frow.get("Checks", {})
                    if isinstance(fchecks, dict):
                        for k, v in fchecks.items():
                            ficon = "✅" if v is True else "❌" if v is False else "⚪ N/A"
                            st.write(f"{ficon} {k}")

    with fscreen_tab2:
        st.caption("Dhan remains the primary Indian market-price source. Fundamental/news enrichment is deliberately fetched only for candidates, cached locally, and never used to weaken S1–S4 rules.")
        st.info("Twelve Data provides India fundamentals/press releases; Dhan's current API documentation exposes market data, instruments, quotes, positions and related trading/data APIs rather than a fundamental-financial-statement endpoint.")
        sym_text=st.text_input("Candidate symbols (comma separated)","RELIANCE,TCS,HDFCBANK",key="fund_symbols_final")
        if st.button("🔎 Enrich Fundamentals + News",key="fund_enrich_final"):
            symbols=[x.strip().upper() for x in sym_text.split(',') if x.strip()]
            rows=[]
            with st.spinner(f"Enriching {len(symbols)} candidate(s)..."):
                for sym in symbols:
                    try:
                        info,ff=company_info(sym)
                        items,sent,risk=news_snapshot(sym)
                        score,status,flags=_fundamental_score(info)
                        rows.append({"Ticker":sym,"Fundamental Score":score,"Status":status,"News Sentiment":round(sent,1),"News Risk":round(risk,1),"Flags":"; ".join(ff+flags),"News Items":len(items)})
                    except Exception as e:
                        rows.append({"Ticker":sym,"Fundamental Score":np.nan,"Status":f"ERROR: {e}","News Sentiment":np.nan,"News Risk":np.nan,"Flags":"","News Items":0})
            st.session_state["fundamental_results_final"]=pd.DataFrame(rows)
        fr=st.session_state.get("fundamental_results_final",pd.DataFrame())
        if fr.empty: st.info("Enter candidates or feed the tab from the scanner's ≥85 queue.")
        else: st.dataframe(fr.sort_values(["Fundamental Score","News Sentiment"],ascending=[False,False]),width='stretch',hide_index=True)

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
            # LOCAL-ONLY. Safety must never trigger a live Dhan download on a bare rerun.
            if d is None or d.empty:
                rows.append({
                    "Stock":sym,"Safety Score":np.nan,
                    "Status":"NO LOCAL DATA — sync this symbol in Data Manager first",
                    "News Risk":np.nan,"Flags":""
                })
                continue
            try:
                info,_=company_info(sym); _,_,newsrisk=news_snapshot(sym)
                sc,status,flags=advanced_small_micro_safety(info,d,newsrisk)
                rows.append({"Stock":sym,"Safety Score":sc,"Status":status,"News Risk":round(newsrisk,1),"Flags":", ".join(flags)})
            except Exception as e:
                rows.append({"Stock":sym,"Safety Score":np.nan,"Status":f"ERROR: {e}","News Risk":np.nan,"Flags":""})
        st.dataframe(pd.DataFrame(rows).sort_values("Safety Score",ascending=False),width='stretch',hide_index=True)


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

        try:
            q=live_forward_test_table()
        except Exception as e:
            q=pd.DataFrame(); st.error(f"Live forward-test table error: {e}")
        if q.empty:
            st.info("Waiting for the first Dhan WebSocket ticks...")
        else:
            st.dataframe(q,width='stretch',hide_index=True)

        st.caption(
            "The feed is persistent only while this Streamlit application process is running. "
            "If the app sleeps/restarts, the manager reconnects automatically when the app resumes."
        )

with tabs[8]:
    st.subheader("💾 Dhan Data Manager")
    st.caption("Dhan is the primary Indian-equity market-data source. Historical candles are cached locally; backtests use the local dataset after it is built.")

    # ---- Access token status (Dhan tokens expire every 24h) -------------------
    st.markdown("### 🔑 Access Token Status")
    if _dhan_pin_totp_configured():
        _tok, _issued = _read_cached_dhan_token()
        if _tok and _issued:
            try:
                _age_h = (datetime.now() - datetime.fromisoformat(_issued)).total_seconds() / 3600
                st.success(f"🟢 Auto-renewal active (PIN+TOTP). Cached token is {_age_h:.1f}h old (renews automatically past {DHAN_TOKEN_MAX_AGE_HOURS}h).")
            except Exception:
                st.info("Auto-renewal active (PIN+TOTP). Token cached, age unknown.")
        else:
            st.info("Auto-renewal active (PIN+TOTP). No token generated yet — one will be minted on first Dhan call.")
        if st.button("🔄 Force-renew token now", key="dhan_force_renew"):
            with st.spinner("Generating a fresh Dhan access token via PIN+TOTP..."):
                try:
                    _dhan_generate_fresh_token()
                    st.success("✅ New access token generated and cached.")
                except Exception as e:
                    st.error(f"Token renewal failed: {e}")
    elif _dhan_manual_token_configured():
        st.warning("Using a manually-pasted DHAN_ACCESS_TOKEN. Dhan tokens expire every 24h — you'll need to regenerate it in Dhan's console and update Streamlit Secrets daily. Add DHAN_PIN and DHAN_TOTP_SECRET to Secrets to switch to automatic renewal.")
    else:
        st.error("No Dhan credentials configured. Add DHAN_CLIENT_ID plus either (DHAN_PIN + DHAN_TOTP_SECRET) for auto-renewal, or DHAN_ACCESS_TOKEN for manual daily renewal, to Streamlit Secrets.")

    # ---- GitHub DB backup status (Streamlit Cloud's filesystem is ephemeral) --
    st.markdown("### 🗄️ Database Backup (GitHub)")
    if _github_configured():
        st.success("🟢 GitHub backup configured — learning data is protected against Streamlit Cloud reboots. Auto-backs up after every closed forward test, learned backtest batch, and added candidate (rate-limited to once per 15 minutes).")
    else:
        st.error("🔴 GitHub backup NOT configured — accumulated learning data will be LOST on the next Streamlit Cloud reboot/redeploy. Add GITHUB_TOKEN and GITHUB_REPO to Streamlit Secrets to enable it.")
    if st.button("💾 Backup DB Now", key="db_backup_now"):
        with st.spinner("Uploading market_data.sqlite3 to GitHub..."):
            if backup_db_to_github():
                st.success("✅ Backed up.")
            else:
                st.error("Backup failed — check GITHUB_TOKEN/GITHUB_REPO in Streamlit Secrets, and that the token has Contents: Read and write access to this repo.")

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
            sync_symbols=[str(t).upper().replace(".NS","") for t in sync_tickers]
            con=_db()
            try:
                qmarks=",".join(["?"]*len(sync_symbols))
                pre_max={r[0]:r[1] for r in con.execute(
                    f"SELECT symbol,MAX(dt) FROM candles WHERE symbol IN ({qmarks})",sync_symbols).fetchall()}
            finally:
                con.close()

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

            # One-line freshness log: did this sync actually pull a NEW
            # most-recent trading day's candle for at least one symbol?
            con=_db()
            try:
                post_rows=con.execute(
                    f"SELECT symbol,MAX(dt) FROM candles WHERE symbol IN ({qmarks}) GROUP BY symbol",
                    sync_symbols).fetchall()
            finally:
                con.close()
            post_max={r[0]:r[1] for r in post_rows}
            newest_pulled=max((v for v in post_max.values() if v),default=None)
            if newest_pulled:
                advanced=sum(1 for s in sync_symbols if post_max.get(s)==newest_pulled and pre_max.get(s)!=newest_pulled)
                if advanced>0:
                    _log_sync_freshness(newest_pulled,advanced)

            # Refresh the per-symbol sync-diagnostics table for this universe.
            compute_and_store_sync_diagnostics(sync_tickers)
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
            width='stretch',
            hide_index=True
        )

    with st.expander("⚠️ Sync Diagnostics — why are stocks below the 260-bar threshold?"):
        st.caption(
            "Backtest/Scanner silently drop any stock with fewer than 260 usable local bars. "
            "This lists every such stock in the selected universe(s) with a specific reason, "
            "computed fresh each time this expander is rendered and persisted to sync_diagnostics."
        )
        diag_universes=st.multiselect(
            "Universe(s) to diagnose",
            ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
            default=[sync_universe],
            key="dm_diag_universes"
        )
        if diag_universes:
            try:
                diag_tickers=sorted(set(sum([index_universe(u) for u in diag_universes],[])))
                diag_df=compute_and_store_sync_diagnostics(diag_tickers)
                if diag_df.empty:
                    st.success(f"✅ All {len(diag_tickers):,} stocks in the selected universe(s) have ≥260 local bars.")
                else:
                    st.warning(f"{len(diag_df):,} of {len(diag_tickers):,} stocks are below the 260-bar threshold.")
                    st.dataframe(
                        diag_df.rename(columns={"symbol":"Symbol","bar_count":"Bar Count","reason":"Reason"}),
                        width='stretch',
                        hide_index=True
                    )
            except Exception as ex:
                st.error(f"Could not compute sync diagnostics (index universe fetch failed): {ex}")
        else:
            st.info("Select at least one universe to diagnose.")

    with st.expander("🕒 Sync Freshness Log — last 10 syncs that pulled a new session"):
        st.caption(
            "One entry each time SYNC ONLY MISSING DATA successfully pulled a new most-recent "
            "trading day's candle for at least one symbol. Use this to observe, over real "
            "trading sessions, how soon after close Dhan's data actually becomes available."
        )
        con=_db()
        try:
            log_df=pd.read_sql_query(
                """SELECT synced_at AS "Synced At", most_recent_date_pulled AS "Most Recent Date Pulled",
                          symbols_updated AS "Symbols Updated"
                   FROM sync_freshness_log ORDER BY id DESC LIMIT 10""",
                con
            )
        finally:
            con.close()
        if log_df.empty:
            st.info("No freshness-log entries yet. This fills in as syncs pull new trading sessions.")
        else:
            st.dataframe(log_df,width='stretch',hide_index=True)

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
            with st.spinner("Scanning for S4 recovery candidates..."):
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
                st.dataframe(res,width='stretch',hide_index=True)
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

    st.divider()
    st.subheader("📐 EMA20 Extension Calibration — is 3% actually the best cutoff?")
    st.caption(
        "Exact S4 requires daily close <= 1.03 x EMA20 (within 3% above EMA20), a fixed assumption. "
        "This runs every OTHER S4 condition unchanged and measures win rate/avg R by how far price "
        "actually was from EMA20 at signal time, so the 3% cutoff can be replaced with evidence "
        "instead of an assumption. Exact S4 itself is never changed by this."
    )
    ec1,ec2=st.columns(2)
    ext_universe=ec1.selectbox("Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],key="s4ext_universe")
    ext_period=ec2.selectbox("Backtest span",["1 Year","2 Years","3 Years"],index=1,key="s4ext_period")
    if st.button("📐 Run EMA20 Extension Calibration",type="primary",key="s4ext_run"):
        try:
            tickers=index_universe(ext_universe)
        except Exception as e:
            st.error(f"Could not load index universe constituents (network/data issue): {e}")
            tickers=[]
        if tickers:
            estart,eend=_bt_period(ext_period)
            with st.spinner(f"Replaying Strategy 4's other conditions across {len(tickers):,} stocks..."):
                data=load_local_backtest_data(tickers,estart,eend)
                cal=s4_ema20_extension_calibration(data,estart,eend)
            st.session_state["s4_ext_calibration"]=cal

    cal=st.session_state.get("s4_ext_calibration",pd.DataFrame())
    if cal.empty:
        st.info("Run the calibration to see which EMA20 distance actually performed best historically.")
    else:
        report=s4_extension_bucket_report(cal)
        reliable_col=f"Reliable (>={S4_CALIBRATION_MIN_BUCKET_SAMPLES} samples)"
        st.dataframe(report,width='stretch',hide_index=True)
        st.caption(f"Total qualifying signals (ignoring the 3% rule): {len(cal):,}. Buckets below {S4_CALIBRATION_MIN_BUCKET_SAMPLES} samples are marked unreliable — treat them as noise, not evidence.")

        reliable=report[report[reliable_col]]
        if reliable.empty:
            st.warning("No bucket has enough samples yet to recommend a threshold. Try a longer span or wider universe.")
        else:
            best=reliable.sort_values(["WinRate","Samples"],ascending=[False,False]).iloc[0]
            st.success(f"Best-performing reliable bucket: **{best['Bucket']}** — {best['WinRate']}% win rate, {best['AvgR']} avg R over {int(best['Samples'])} trades.")
            exact_row=report[report.Bucket=="0-3% above (exact S4 rule)"]
            if not exact_row.empty and exact_row.iloc[0][reliable_col]:
                st.caption(f"For comparison, the exact-S4 0-3% rule: {exact_row.iloc[0]['WinRate']}% win rate, {exact_row.iloc[0]['AvgR']} avg R over {int(exact_row.iloc[0]['Samples'])} trades.")
            st.markdown("#### Paste this into Custom Strategy Lab to scan with the learned threshold instead of the fixed 3% rule")
            st.code(s4_custom_dsl_from_bucket(str(best["Bucket"])), language="text")
            st.caption(
                "This replicates S4's other rules but swaps the EMA20 distance for the bucket above. "
                "The DSL is AND-only, so exact S4's 'OR monthly reclaim' branch is approximated here by "
                "the monthly-cross-count condition alone — this scan is narrower than exact S4, not identical."
            )

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
                    with st.spinner(f"Fetching live price for {symbol}..."):
                        px=td_price(symbol)
                    st.session_state["td_live_px"]=px
                except Exception as e:
                    st.error(str(e))
            if st.button("🧪 Test Symbol",key="td_test_symbol"):
                with st.spinner(f"Validating {symbol}..."):
                    ok,n,msg=td_validate_symbol(symbol,market)
                if ok: st.success(f"Working: {symbol} — {n} recent daily candles available.")
                else: st.error(f"Symbol test failed: {msg}")

            if "td_live_px" in st.session_state:
                st.metric("Live Price",st.session_state["td_live_px"])
            d=st.session_state.get("td_custom_data",pd.DataFrame())
            if not d.empty:
                st.dataframe(d.tail(200),width='stretch')
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
                        st.dataframe(cq.head(200), width='stretch', hide_index=True)

    st.divider()
    st.subheader("Strategy Rules")
    st.caption(
        "Whitelist rule DSL — never eval()/exec(). One condition per line, all lines AND-combined. "
        "Format: `<COLUMN> <op> <value>` where op is one of > >= < <= == != and value is a number, "
        "another known column, or `NUMBER * COLUMN`. Known columns: "
        + ", ".join(sorted(CUSTOM_DSL_COLUMNS)) + "."
    )
    st.text_area(
        "Strategy rules",height=160,key="custom_strategy",
        placeholder="RSI14 > 55\nCLOSE > EMA200\nVOLUME > 1.5 * VOL20",
        label_visibility="collapsed"
    )
    if st.button("🔍 Validate Strategy",key="custom_validate"):
        _,verr=parse_custom_strategy(st.session_state.get("custom_strategy",""))
        if verr:
            for e in verr: st.error(e)
        else:
            st.success("Strategy is valid. Ready to scan + backtest below.")

    st.markdown("### Indian Stocks — local-only scan + backtest")
    st.caption("Reuses the same local candle cache, fast features, and O(1) regime/safety lookups as the Daily Scanner and Backtest tabs. Makes zero Dhan/API calls.")
    cc1,cc2,cc3,cc4=st.columns(4)
    custom_universes=cc1.multiselect(
        "Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        default=["Nifty 500"],key="custom_universe"
    )
    custom_period=cc2.selectbox("Backtest span",["6 Months","1 Year","2 Years","3 Years"],index=0,key="custom_period")
    custom_sl_pct=cc3.slider("Stop loss %",1.0,15.0,7.0,0.5,key="custom_sl_pct")/100
    custom_target_r=cc4.number_input("Target (R multiple)",1.0,10.0,3.0,0.5,key="custom_target_r")

    if st.button("🔬 Run Custom Strategy Scan + Backtest",type="primary",key="custom_run"):
        conditions,cerr=parse_custom_strategy(st.session_state.get("custom_strategy",""))
        if cerr:
            for e in cerr: st.error(e)
        elif not conditions:
            st.warning("Enter at least one rule line before running.")
        elif not custom_universes:
            st.warning("Select at least one universe.")
        else:
            try:
                tickers=sorted(set(sum([index_universe(u) for u in custom_universes],[])))
            except Exception as e:
                st.error(f"Could not load index universe constituents (network/data issue): {e}")
                tickers=[]
            if tickers:
                cstart,cend=_bt_period(custom_period)
                status=local_backtest_status(tickers,cstart,cend)
                ready=int(status.Ready.sum()) if not status.empty else 0
                if ready==0:
                    st.error("No local candle data for this universe. Use Data Manager → SYNC ONLY MISSING DATA first.")
                else:
                    try:
                        with st.spinner(f"Replaying {ready:,} locally cached stocks against the custom rules..."):
                            data=load_local_backtest_data(tickers,cstart,cend)
                            cbt=_custom_strategy_backtest(data,conditions,cstart,cend,custom_sl_pct,float(custom_target_r))
                        st.session_state["custom_backtest"]=cbt
                        learned=_learn_from_backtest(cbt)
                        st.success(f"{len(cbt):,} historical CUSTOM setups found; {learned:,} saved to the learning database as strategy='CUSTOM'.")

                        st.subheader("📡 Today's Custom Strategy Candidates")
                        ml_model_custom=train_win_probability_model("INDIA")
                        today_rows=[]
                        for ticker,df in data.items():
                            if len(df)<260: continue
                            f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
                            if f.empty or len(f)<260: continue
                            if not bool(custom_strategy_signal(f,conditions).iloc[-1]): continue
                            i=len(f)-1
                            avg_value,abnormal=_safety_fast_series(df)
                            regime,_=_regime_from_row(f,i)
                            safe,safe_status,_=_safety_from_row(avg_value,abnormal,i)
                            score,parts=final_setup_score(f,"CUSTOM",regime,safe)
                            entry=float(f.close.iloc[-1]); stop=entry*(1-custom_sl_pct)
                            target=entry+float(custom_target_r)*(entry-stop)
                            row={
                                "Ticker":str(ticker).replace(".NS",""),"Score":score,"Regime":regime,
                                "Safety":safe_status,"Entry":round(entry,2),"Stop":round(stop,2),
                                "Target":round(target,2),"HTF Score":parts["HTF Demand"],
                                "Footprint Score":parts["Footprint"],"Entry Quality":parts["Entry Quality"],
                                "Relative Strength":parts["Relative Strength"],"Strategy":"CUSTOM",
                            }
                            wp=ml_win_probability(ml_model_custom,row)
                            if pd.isna(wp): wp=fallback_win_probability("INDIA","CUSTOM",float(score))
                            row["Win Probability %"]=wp
                            today_rows.append(row)
                        if today_rows:
                            st.dataframe(pd.DataFrame(today_rows).sort_values("Score",ascending=False),width='stretch',hide_index=True)
                        else:
                            st.info("No stock currently satisfies every custom rule.")
                    except Exception as ex:
                        st.error(f"Custom strategy backtest error: {ex}")

    cbt=st.session_state.get("custom_backtest",pd.DataFrame())
    if not cbt.empty:
        st.subheader("🏆 Custom Strategy — Historical Results")
        a,b,c,d=st.columns(4)
        a.metric("Trades",len(cbt))
        b.metric("Win %",f"{(cbt.Outcome.str.upper()=='WIN').mean()*100:.1f}%")
        c.metric("Avg R",f"{cbt.R.mean():.2f}")
        d.metric("Total R",f"{cbt.R.sum():.2f}")
        st.dataframe(cbt.sort_values(['Score','Date'],ascending=[False,False]),width='stretch',hide_index=True)

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
    st.dataframe(safeguards,width='stretch',hide_index=True)

    st.markdown("### 🧪 S4 Recovery — historical study")
    st.caption("Research hypothesis: large impulse → controlled consolidation/retracement → compression → reclaim → higher high. Exact S4 remains unchanged.")
    c1,c2,c3=st.columns(3)
    study_years=c1.selectbox("Study period",["6 Months","1 Year","2 Years","3 Years"],index=2,key="s4_walk_years")
    study_threshold=c2.slider("Recovery score",50,95,70,key="s4_walk_score")
    study_universe=c3.selectbox("Study universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],key="s4_walk_universe")
    if st.button("🔬 RUN S4 RECOVERY WALK-FORWARD STUDY",type="primary",key="s4_walk_run"):
        try:
            with st.spinner("Running S4 recovery walk-forward study..."):
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
        st.dataframe(s4bt.sort_values(["Score","Date"],ascending=[False,False]).head(300),width='stretch',hide_index=True)
        st.warning("Promotion rule: S4 Recovery is not allowed into the exact strategy until it survives out-of-sample/walk-forward evidence with adequate sample size and positive expectancy.")

    st.markdown("### 🛡️ Portfolio risk simulator")
    capital=st.number_input("Starting capital ₹",10000,100000000,100000,10000,key="risk_capital_final")
    risk_pct=st.slider("Risk per trade %",0.25,3.0,1.0,0.25,key="risk_pct_final")
    slots=st.slider("Maximum concurrent positions",1,20,5,key="risk_slots_final")
    bt=st.session_state.get("backtest_final",pd.DataFrame())
    if bt.empty: st.info("Run the local backtest first to simulate capital-aware portfolio results.")
    else:
        pr=portfolio_from_backtest(bt,float(capital),float(risk_pct),int(slots))
        st.dataframe(pd.DataFrame([pr]),width='stretch',hide_index=True)

    st.markdown("### 🧭 Advocate mode")
    st.info("The system should reject a trade when deterministic rules fail, safety is unacceptable, data quality is poor, or the learned evidence is insufficient. It should never manufacture a reason to trade.")

with tabs[12]:
    st.subheader("🎓 Strategy Coach")
    st.caption(
        "Read-only analysis of completed trades per strategy: regime win-rate/avg-R, high-vs-low "
        "component splits, and a shallow decision tree translated into plain-English rules. "
        "This never changes S1-S4/CUSTOM rules — it only reports what the evidence shows so far."
    )
    coach_strategy = st.selectbox("Strategy", ["S1", "S2", "S3", "S4", "CUSTOM"], key="coach_strategy")
    report = strategy_coach_report("INDIA", coach_strategy)

    if report is None:
        st.info(f"No completed {coach_strategy} observations yet. Run a backtest or complete forward-test trades first.")
    else:
        a, b = st.columns(2)
        a.metric("Completed observations", report["n_samples"])
        b.metric("Overall win % / avg R", f"{report['overall_win_rate']}% / {report['overall_avg_r']}")

        if not report["enough_for_breakdown"]:
            st.warning(
                f"Only {report['n_samples']} completed {coach_strategy} observations — need "
                f"≥{STRATEGY_COACH_MIN_SAMPLES} before the regime/component breakdown is shown. "
                "Treat any pattern below this threshold as noise, not evidence."
            )
        else:
            st.markdown("### 📊 Win rate / Avg R by regime")
            if report["regime_breakdown"].empty:
                st.info("No regime breakdown available yet.")
            else:
                st.dataframe(report["regime_breakdown"], width='stretch', hide_index=True)
                st.caption("Samples below ~10-15 per regime are too thin to draw conclusions from.")

            st.markdown("### 🔬 Component win-rate split (high half vs low half)")
            if report["component_breakdown"].empty:
                st.info("No component split available yet (not enough score variance in this strategy's history).")
            else:
                st.dataframe(report["component_breakdown"], width='stretch', hide_index=True)
                st.caption("Splits each score component at its median for this strategy's history and compares the two halves.")

        st.markdown("### 🌳 Auto-extracted rules")
        if report["tree_note"]:
            st.info(report["tree_note"])
        else:
            st.dataframe(pd.DataFrame(report["tree_rules"]), width='stretch', hide_index=True)
            st.caption(
                "Each row is one path through a shallow (depth ≤3) decision tree fit on completed "
                "outcomes, sorted by win rate then sample size. Read as: \"when these conditions held, "
                "this strategy's setups won at this rate over this many trades.\" These are patterns in "
                "past evidence, not guaranteed future performance — the smaller the sample, the less "
                "the rule should influence live decisions."
            )

with tabs[13]:
    st.subheader("💱 Forex/Crypto SMC — Smart Money Concepts (HTF 4h + LTF 15min)")
    st.caption(
        "Separate research engine from S1-S4. HTF (4h) establishes market structure/bias via "
        "MSB + order blocks + FVGs + premium/discount zones; LTF (15min) confirms entry with a "
        "micro-MSB or liquidity sweep inside the HTF zone. Real-money order execution remains disabled."
    )
    st.warning(
        "⚠️ No economic calendar / news-day filter is wired in. Manually check for CPI, NFP, and "
        "rate-decision days before acting on any signal below — this is not automated."
    )

    if not twelvedata_configured():
        st.warning("Add TWELVEDATA_API_KEY to Streamlit Secrets to activate this tab.")
    else:
        # "Market" is informational only — Twelve Data's symbol format (e.g.
        # "XAU/USD", "BTC/USD") is what actually matters to the API, so every
        # instrument (forex, metals, crypto) is offered in one combined list
        # instead of gating pairs behind a Forex/Crypto toggle.
        SMC_PRESET_PAIRS = [
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
            "XAU/USD", "XAG/USD",
            "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BNB/USD", "DOGE/USD",
        ]
        smc_market = st.selectbox(
            "Market (informational only — affects labeling, not which pairs you can pick)",
            ["Forex", "Crypto"], key="smc_market"
        )
        c1, c2, c3 = st.columns(3)
        smc_confluence = c1.slider("Min confluence score", 1, 5, 2, key="smc_confluence")
        smc_body_pct = c2.slider("Strong MSB: min candle body %", 30, 90, 60, 5, key="smc_body_pct") / 100
        smc_beyond_pct = c3.slider("Strong MSB: min close-beyond %", 0, 30, 10, 1, key="smc_beyond_pct") / 100
        st.caption("These three are calibrated guesses from the source guide, not exact values from any source — tune freely.")

        st.markdown("### 🔍 Live Multi-Pair Scan")
        smc_scan_pairs = st.multiselect(
            "Pairs to scan", SMC_PRESET_PAIRS,
            default=["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "BTC/USD", "ETH/USD"],
            key="smc_scan_pairs"
        )
        smc_extra_pairs_raw = st.text_input(
            "Additional pairs not in the list above (comma separated, Twelve Data symbol format)",
            "", key="smc_extra_pairs", placeholder="e.g. USD/INR, LTC/USD, WTI/USD"
        )
        smc_extra_pairs = [p.strip().upper() for p in smc_extra_pairs_raw.split(",") if p.strip()]
        smc_all_scan_pairs = list(dict.fromkeys(smc_scan_pairs + smc_extra_pairs))  # dedupe, keep order

        if st.button("🔍 Scan SMC Setups", type="primary", key="smc_scan_run"):
            if not smc_all_scan_pairs:
                st.warning("Select or type at least one pair.")
            else:
                with st.spinner(f"Scanning {len(smc_all_scan_pairs)} pair(s) for SMC setups..."):
                    smc_results = scan_smc_pairs(smc_all_scan_pairs, smc_market, smc_confluence, smc_body_pct, smc_beyond_pct)
                st.session_state["smc_scan_results"] = smc_results

        smc_results = st.session_state.get("smc_scan_results", pd.DataFrame())
        if smc_results.empty:
            st.info("No SMC setups found yet. Run a scan above.")
        else:
            errors = smc_results[smc_results.get("direction") == "ERROR"] if "direction" in smc_results.columns else pd.DataFrame()
            valid = smc_results[smc_results.get("direction") != "ERROR"] if "direction" in smc_results.columns else smc_results
            if not errors.empty:
                for _, e in errors.iterrows():
                    st.caption(f"⚠️ {e['Pair']}: {e['zone_label']}")
            if valid.empty:
                st.info("No qualifying setups right now (all selected pairs either had no valid HTF zone or failed the confluence gate).")
            else:
                st.dataframe(valid.drop(columns=["confluence_matched", "note"], errors="ignore"), width='stretch', hide_index=True)
                for _, row in valid.iterrows():
                    st.caption(f"**{row['Pair']}** ({row['direction'].upper()}): {row.get('note','')}")
                added = add_smc_forward_candidates(valid)
                if added:
                    st.success(f"{added} setup(s) added to forward-test tracking as strategy='FX_SMC'.")

        st.markdown("### 🧪 Backtest")
        st.warning(
            "Backtest slippage is a fixed 0.05% placeholder, not a real spread/liquidity/session model. "
            "Do not treat these R-multiples as production-accurate."
        )
        st.info(
            "⏱️ **How much history you actually get**: Twelve Data returns at most 5,000 bars per request "
            "regardless of the lookback you pick below. At 15min (the LTF leg this backtest walks bar-by-bar), "
            "5,000 bars ≈ 52 days (~1.7 months) — that's the real ceiling even if you ask for 12 months. "
            "HTF (4h) easily covers a full year in 5,000 bars, but the LTF cap is what actually limits the "
            "backtest's trade count. The exact coverage you got is shown after each run below."
        )
        bc1, bc2, bc3, bc4 = st.columns(4)
        smc_bt_pair_choice = bc1.selectbox("Pair", SMC_PRESET_PAIRS + ["✏️ Custom..."], key="smc_bt_pair_choice")
        if smc_bt_pair_choice == "✏️ Custom...":
            smc_bt_pair = bc1.text_input("Custom pair (Twelve Data symbol)", "EUR/USD", key="smc_bt_pair_custom")
        else:
            smc_bt_pair = smc_bt_pair_choice
        smc_bt_years = bc2.selectbox("Requested lookback", [0.25, 0.5, 1, 2], index=2, format_func=lambda y: f"{y} yr", key="smc_bt_years")
        smc_bt_capital = bc3.number_input("Starting capital", 1000, 10000000, 100000, 1000, key="smc_bt_capital")
        smc_bt_risk = bc4.number_input("Risk per trade %", 0.25, 5.0, 1.0, 0.25, key="smc_bt_risk")
        if st.button("🧪 Run SMC Backtest", type="primary", key="smc_bt_run"):
            try:
                with st.spinner(f"Fetching HTF/LTF history and replaying {smc_bt_pair}..."):
                    smc_htf = td_market_history(smc_bt_pair, smc_market, "4h", years=smc_bt_years)
                    smc_ltf = td_market_history(smc_bt_pair, smc_market, "15min", years=smc_bt_years)
                    if smc_htf.empty or smc_ltf.empty or len(smc_htf) < 60 or len(smc_ltf) < 60:
                        st.error("Not enough HTF/LTF history returned for this pair.")
                    else:
                        htf_days = (smc_htf.index[-1] - smc_htf.index[0]).days
                        ltf_days = (smc_ltf.index[-1] - smc_ltf.index[0]).days
                        st.caption(
                            f"📊 Actually fetched: HTF {len(smc_htf):,} bars (~{htf_days} days) | "
                            f"LTF {len(smc_ltf):,} bars (~{ltf_days} days, ~{ltf_days/30.4:.1f} months)"
                        )
                        smc_trades, smc_equity = smc_backtest(
                            smc_htf, smc_ltf, float(smc_bt_capital), float(smc_bt_risk),
                            smc_confluence, 0.0005, smc_body_pct, smc_beyond_pct
                        )
                        st.session_state["smc_backtest_trades"] = smc_trades
                        st.session_state["smc_backtest_equity"] = smc_equity
            except Exception as ex:
                st.error(f"SMC backtest error: {ex}")

        smc_trades = st.session_state.get("smc_backtest_trades", pd.DataFrame())
        if smc_trades.empty:
            st.info("Run the backtest to see historical SMC trade results.")
        else:
            a, b, c, d = st.columns(4)
            a.metric("Trades", len(smc_trades))
            b.metric("Win %", f"{(smc_trades.Outcome=='WIN').mean()*100:.1f}%")
            c.metric("Avg R", f"{smc_trades.R.mean():.2f}")
            d.metric("Total R", f"{smc_trades.R.sum():.2f}")
            st.dataframe(smc_trades, width='stretch', hide_index=True)
            smc_equity = st.session_state.get("smc_backtest_equity", [])
            if len(smc_equity) > 1:
                st.line_chart(pd.Series(smc_equity, name="Equity"))

        with st.expander("🔬 Debug: Swing/MSB Detection (cross-check against a real chart)"):
            st.caption(
                "Prints the raw swing points and MSB events this engine detects for one pair/timeframe, "
                "with timestamps, so you can manually verify them against a real chart (e.g. TradingView) "
                "before trusting the scan/backtest above."
            )
            dc1, dc2 = st.columns(2)
            debug_pair = dc1.text_input("Pair", smc_bt_pair, key="smc_debug_pair")
            debug_tf = dc2.selectbox("Timeframe", ["4h", "15min"], key="smc_debug_tf")
            if st.button("🔬 Run Debug Detection", key="smc_debug_run"):
                try:
                    with st.spinner(f"Fetching {debug_pair} {debug_tf}..."):
                        debug_df = td_market_history(debug_pair, smc_market, debug_tf, years=1)
                    if debug_df.empty or len(debug_df) < 20:
                        st.error("Not enough history returned for this pair/timeframe.")
                    else:
                        d_swung = detect_swings(debug_df)
                        d_atr = _atr(d_swung)
                        d_msbs = detect_msb(d_swung, d_atr, smc_body_pct, smc_beyond_pct)
                        sh = d_swung[d_swung.swing_high][["close"]].rename(columns={"close": "Swing High"})
                        sl = d_swung[d_swung.swing_low][["close"]].rename(columns={"close": "Swing Low"})
                        st.markdown("**Swing highs:**")
                        if not sh.empty:
                            st.dataframe(sh, width='stretch')
                        else:
                            st.info("None detected.")
                        st.markdown("**Swing lows:**")
                        if not sl.empty:
                            st.dataframe(sl, width='stretch')
                        else:
                            st.info("None detected.")
                        st.markdown("**MSB events:**")
                        if d_msbs:
                            msb_rows = [{
                                "Timestamp": d_swung.index[m["idx"]], "Direction": m["direction"],
                                "Strength": m["strength"], "Broken Level": round(m["broken_level"], 5)
                            } for m in d_msbs]
                            st.dataframe(pd.DataFrame(msb_rows), width='stretch', hide_index=True)
                        else:
                            st.info("None detected.")
                except Exception as ex:
                    st.error(f"Debug detection error: {ex}")

st.markdown("---")
st.caption(f"{APP_VERSION} • {ARCHITECTURE_STANDARD} • Research only • Real-money order execution disabled")
