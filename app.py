Stock market:
import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import sqlite3
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta

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
r = requests.get(INDEX_URLS[name], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
r.raise_for_status()
df = pd.read_csv(pd.io.common.BytesIO(r.content))
col = next(c for c in df.columns if str(c).strip().upper() == "SYMBOL")
return sorted({str(s).strip().upper() + ".NS" for s in df[col].dropna()})


# ========================= DHAN PERSISTENT DATA ENGINE =========================
DHAN_BASE_URL = "https://api.dhan.co/v2"
DATA_DB = "market_data.sqlite3"

def dhan_configured():
try:
return bool(st.secrets["DHAN_CLIENT_ID"]) and bool(st.secrets["DHAN_ACCESS_TOKEN"])
except Exception:
return False

def _dhan_headers():
return {
"access-token": str(st.secrets["DHAN_ACCESS_TOKEN"]),
"client-id": str(st.secrets["DHAN_CLIENT_ID"]),
"Content-Type": "application/json",
"Accept": "application/json"
}

def _db():
con = sqlite3.connect(DATA_DB, timeout=60, check_same_thread=False)
con.execute("""CREATE TABLE IF NOT EXISTS candles(
symbol TEXT NOT NULL, dt TEXT NOT NULL, open REAL, high REAL, low REAL,
close REAL, volume REAL, PRIMARY KEY(symbol,dt))""")
con.execute("""CREATE TABLE IF NOT EXISTS forward_tests(
id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, symbol TEXT,
strategy TEXT, score REAL, regime TEXT, entry REAL, sl REAL, target REAL,
status TEXT DEFAULT 'ACTIVE', ltp REAL, mfe REAL DEFAULT 0,
mae REAL DEFAULT 0, exit_price REAL, result_r REAL, updated_at TEXT)""")
con.commit()
return con

@st.cache_data(ttl=86400, show_spinner=False)
def dhan_master():
urls = [
"https://images.dhan.co/api-data/api-scrip-master.csv",
"https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
]
last = ""
for u in urls:
try:
r = requests.get(u, timeout=45)
r.raise_for_status()
if len(r.content) > 1000:
return pd.read_csv(io.BytesIO(r.content), low_memory=False)
except Exception as e:
last = str(e)
raise RuntimeError("Dhan instrument master failed: " + last)

@st.cache_data(ttl=86400, show_spinner=False)
def dhan_map():
m = dhan_master()
cols = {str(c).strip().lower(): c for c in m.columns}
sym = next((cols[k] for k in ["sem_trading_symbol", "trading_symbol", "sem_custom_symbol", "custom_symbol"] if k in cols), None)
sid = next((cols[k] for k in ["sem_smst_security_id", "sem_security_id", "security_id"] if k in cols), None)
ex = next((cols[k] for k in ["sem_exm_exch_id", "exchange"] if k in cols), None)
seg = next((cols[k] for k in ["sem_segment", "segment"] if k in cols), None)
if not sym or not sid:
raise RuntimeError("Dhan symbol/Security ID columns not found")
keep = [sym, sid] + ([ex] if ex else []) + ([seg] if seg else [])
m = m[keep].copy()
names = ["symbol", "security_id"] + ((["exchange"] if ex else []) + (["segment"] if seg else []))

Stock market:
m.columns = names
m.symbol = m.symbol.astype(str).str.upper().str.strip()
if ex:
m = m[m.exchange.astype(str).str.upper().isin(["NSE", "NSE_EQ"])]
if seg:
sv = m.segment.astype(str).str.upper().str.strip()
q = sv.isin(["E", "EQUITY", "NSE_EQ"])
if q.any():
m = m[q]
return dict(zip(m.symbol, m.security_id.astype(str)))

def dhan_history(symbol, start_date, end_date):
clean = str(symbol).upper().replace(".NS", "")
sid = dhan_map().get(clean)
if not sid:
raise ValueError("Security ID not found: " + clean)
payload = {
"securityId": sid,
"exchangeSegment": "NSE_EQ",
"instrument": "EQUITY",
"expiryCode": 0,
"oi": False,
"fromDate": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
"toDate": pd.Timestamp(end_date).strftime("%Y-%m-%d")
}
r = requests.post(f"{DHAN_BASE_URL}/charts/historical", headers=_dhan_headers(), json=payload, timeout=45)
if not r.ok:
raise RuntimeError(f"Dhan historical {r.status_code}: {r.text[:250]}")
j = r.json()
if "close" not in j:
raise RuntimeError("Unexpected Dhan historical response")
d = pd.DataFrame({k: j.get(k, []) for k in ["open", "high", "low", "close", "volume"]})
if j.get("timestamp"):
d.index = pd.to_datetime(j["timestamp"], unit="s", errors="coerce")
d = d.apply(pd.to_numeric, errors="coerce").dropna(subset=["close"]).sort_index()
return d

def _bounds(con, s):
return con.execute("SELECT MIN(dt),MAX(dt) FROM candles WHERE symbol=?", (s,)).fetchone()

def _save(con, s, d):
if d.empty:
return 0
rows = [(s, pd.Timestamp(i).strftime("%Y-%m-%d"), float(r.open), float(r.high),
float(r.low), float(r.close), float(r.volume)) for i, r in d.iterrows()]
con.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?)", rows)
con.commit()
return len(rows)

def update_dhan_symbol(symbol, start_date, end_date):
s = str(symbol).upper().replace(".NS", "")
con = _db()
try:
mn, mx = _bounds(con, s)
if not mn:
return _save(con, s, dhan_history(s, start_date, end_date))
n = 0
mn = pd.Timestamp(mn).date()
mx = pd.Timestamp(mx).date()
if pd.Timestamp(start_date).date() < mn:
n += _save(con, s, dhan_history(s, start_date, mn - timedelta(days=1)))
if pd.Timestamp(end_date).date() > mx:
n += _save(con, s, dhan_history(s, mx + timedelta(days=1), end_date))
return n
finally:
con.close()

def _read_cache(con, s, start_date, end_date):
d = pd.read_sql_query(
"""SELECT dt,open,high,low,close,volume FROM candles
WHERE symbol=? AND dt>=? AND dt<=? ORDER BY dt""",
con,
params=(s, pd.Timestamp(start_date).strftime("%Y-%m-%d"), pd.Timestamp(end_date).strftime("%Y-%m-%d"))
)
if d.empty:
return pd.DataFrame()
d["dt"] = pd.to_datetime(d["dt"])
d = d.set_index("dt")
d.index.name = "date"
return d

def download_prices(tickers, start, end, max_workers=6):
if not dhan_configured():
raise RuntimeError("Dhan credentials are not configured")
dhan_map()
tickers = list(dict.fromkeys(tickers))
results = {}
errors = []

def _safe_update(symbol):
try:
update_dhan_symbol(symbol, start, end)
return symbol, True, None
except Exception as e:
return symbol, False, str(e)

with ThreadPoolExecutor(max_workers=max_workers) as executor:
futures = {executor.submit(_safe_update, t): t for t in tickers}
for future in as_completed(futures):
symbol, success, err = future.result()
if not success:
errors.append(f"{symbol}: {err}")

Stock market:
con = _db()
try:
for t in tickers:
clean = str(t).upper().replace(".NS", "")
d = _read_cache(con, clean, start, end)
if not d.empty:
results[t] = d
finally:
con.close()

if errors and len(errors) <= 12:
st.warning(f"Some symbols failed ({len(errors)}): " + " | ".join(errors[:6]))
return results


def dhan_live_ltp(symbols):
mp = dhan_map()
pairs = [(mp[s.replace(".NS", "").upper()], s.replace(".NS", "").upper())
for s in symbols if s.replace(".NS", "").upper() in mp]
if not pairs:
return {}
r = requests.post(
f"{DHAN_BASE_URL}/marketfeed/ltp",
headers=_dhan_headers(),
json={"NSE_EQ": [int(a) for a, b in pairs]},
timeout=20
)
r.raise_for_status()
raw = r.json().get("data", {}).get("NSE_EQ", {})
rev = {a: b for a, b in pairs}
return {rev[str(k)]: float(v["last_price"]) for k, v in raw.items()
if str(k) in rev and isinstance(v, dict) and v.get("last_price") is not None}


# ========================= CRYPTO HELPER =========================
def get_crypto_ohlcv(symbol="BTC/USDT", timeframe="1d", limit=500, exchange_id="binance"):
try:
import ccxt
exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
return df.set_index("timestamp")
except Exception as e:
st.error(f"Crypto data error: {e}")
return pd.DataFrame()


# ========================= INDICATORS =========================
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

def _monthly_asof(d):
m = d.resample("ME").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
cur_key = d.index[-1].to_period("M")
cur = d[d.index.to_period("M") == cur_key]
if not cur.empty:
m.loc[cur.index[-1].to_period("M").end_time.normalize(), ["open", "high", "low", "close", "volume"]] = [
cur.open.iloc[0], cur.high.max(), cur.low.min(), cur.close.iloc[-1], cur.volume.sum()
]
return m

def _weekly_asof(d):
return d.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})

def features(d):
x = d.copy()
for n in [10, 20, 50, 200, 250]:
x[f"ema{n}"] = ema(x.close, n)
x["vol20"] = sma(x.volume, 20)
x["vol30"] = sma(x.volume, 30)
x["rsi14"] = rsi(x.close)
x["relvol"] = x.volume / x.vol20

tr = pd.concat([
x.high - x.low,
(x.high - x.close.shift()).abs(),
(x.low - x.close.shift()).abs()
], axis=1).max(axis=1)
x["atr14"] = tr.rolling(14).mean()

w = _weekly_asof(x)
w["rsi14"] = rsi(w.close, 14)
w["ema20"] = ema(w.close, 20)
w["ema50"] = ema(w.close, 50)
wkvals = []
for dt in x.index:
wk = w[w.index <= dt]
wkvals.append(wk.iloc[-1] if not wk.empty else pd.Series(dtype=float))
x["wrsi14"] = [v.get("rsi14", np.nan) for v in wkvals]
x["wema20"] = [v.get("ema20", np.nan) for v in wkvals]
x["wema50"] = [v.get("ema50", np.nan) for v in wkvals]
x["wclose"] = [v.get("close", np.nan) for v in wkvals]

m = _monthly_asof(x)
m["rsi14"] = rsi(m.close, 14)

Stock market:
m["ema10"] = ema(m.close, 10)
m["ema15"] = ema(m.close, 15)
m["ema20"] = ema(m.close, 20)
m["mom"] = m.close.pct_change() * 100
m["prev_close"] = m.close.shift(1)
m["prev_high"] = m.high.shift(1)
m["prev_low"] = m.low.shift(1)
m["mom20max"] = m.mom.rolling(20, min_periods=1).max()
cross = (m.ema10 > m.ema20) & (m.ema10.shift(1) <= m.ema20.shift(1))
m["cross_10_20"] = cross.astype(int)
m["cross_count20"] = m.cross_10_20.rolling(20, min_periods=1).sum()

vals = []
for dt in x.index:
mm = m[m.index.to_period("M") <= dt.to_period("M")]
vals.append(mm.iloc[-1] if not mm.empty else pd.Series(dtype=float))
x["mclose"] = [v.get("close", np.nan) for v in vals]
x["mopen"] = [v.get("open", np.nan) for v in vals]
x["mhigh"] = [v.get("high", np.nan) for v in vals]
x["mlow"] = [v.get("low", np.nan) for v in vals]
x["mrsi14"] = [v.get("rsi14", np.nan) for v in vals]
x["mema10"] = [v.get("ema10", np.nan) for v in vals]
x["mema15"] = [v.get("ema15", np.nan) for v in vals]
x["mema20"] = [v.get("ema20", np.nan) for v in vals]
x["mmom"] = [v.get("mom", np.nan) for v in vals]
x["mmax20"] = [v.get("mom20max", np.nan) for v in vals]
x["mprevclose"] = [v.get("prev_close", np.nan) for v in vals]
x["mprevhigh"] = [v.get("prev_high", np.nan) for v in vals]
x["mprevlow"] = [v.get("prev_low", np.nan) for v in vals]
x["m_cross_count20"] = [v.get("cross_count20", np.nan) for v in vals]
x["m_cross_10_20"] = [v.get("cross_10_20", np.nan) for v in vals]
return x


# ========================= STRATEGIES =========================
def _pct_change(s):
return s.pct_change() * 100

def strategy_signal(x, s):
if x.empty:
return pd.Series(False, index=x.index)
daily_ret = _pct_change(x.close)

if s == 1:
monthly_open_in_prev = (x.mopen <= x.mprevhigh) & (x.mopen >= x.mprevlow)
monthly_close_in_prev = (x.mclose >= x.mprevlow) & (x.mclose <= x.mprevhigh)
near_ema10 = ((x.mclose - x.mema10) / x.mema10 <= 0.30)
return (
(x.wrsi14 >= 50) & (x.mrsi14 >= 50) & (x.mclose >= x.mema15) &
(x.close >= 15) & (x.vol20 >= 15000) & monthly_open_in_prev &
monthly_close_in_prev & near_ema10 & (x.mmax20 >= 20)
)

if s == 2:
ema20_below_50_cross = (x.ema20 < x.ema50) & (x.ema20.shift(1) >= x.ema50.shift(1))
ema10_below_20_cross = (x.ema10 < x.ema20) & (x.ema10.shift(1) >= x.ema20.shift(1))
ema20_above_50_cross = (x.ema20 > x.ema50) & (x.ema20.shift(1) <= x.ema50.shift(1))
ema50_above_200_cross = (x.ema50 > x.ema200) & (x.ema50.shift(1) <= x.ema200.shift(1))

bearish_20_50_count = ema20_below_50_cross.shift(1).rolling(20, min_periods=20).sum()
bearish_10_20_count = ema10_below_20_cross.shift(1).rolling(10, min_periods=10).sum()
bullish_20_50_count = ema20_above_50_cross.shift(1).rolling(20, min_periods=20).sum()
bullish_50_200_count = ema50_above_200_cross.shift(1).rolling(20, min_periods=20).sum()

inside_previous_day = (
(x.open <= x.high.shift(1)) & (x.open >= x.low.shift(1)) &
(x.close >= x.low.shift(1)) & (x.close <= x.high.shift(1))
)
ret_1d_ago = daily_ret.shift(1)
ret_2d_ago = daily_ret.shift(2)

return (
(daily_ret.rolling(30, min_periods=30).max() >= 5) &
(bearish_20_50_count < 1) & (bearish_10_20_count < 1) &
(x.ema50 >= x.ema250) & (x.vol20 >= 10000) & (x.close >= 15) &
(x.mrsi14 >= 55) & (x.wrsi14 >= 50) & inside_previous_day &
(ret_1d_ago <= 5) & (ret_1d_ago >= -4) &
(ret_2d_ago <= 5) & (ret_2d_ago >= -4) &
(((x.close - x.ema10) / x.ema10) <= 0.04) &
((bullish_20_50_count == 1) | (bullish_50_200_count == 1))
)

Stock market:
if s == 3:
vwap = (x.close * x.volume).rolling(20).sum() / x.volume.rolling(20).sum()
vwap_ema = ema(vwap, 20)
liquidity = vwap_ema * x.vol20 >= 150_000_000
near50 = (x.close <= x.ema50 * 1.04) & (x.close >= x.ema50 * 0.96)
return liquidity & (x.close >= x.ema200) & (x.wrsi14 >= 40) & near50

if s == 4:
monthly_bull_cross = (x.mema10 > x.mema20) & (x.mema10.shift(1) <= x.mema20.shift(1))
monthly_bull_cross_count = monthly_bull_cross.shift(1).rolling(20, min_periods=20).sum()
monthly_reclaim = (x.mclose > x.mema10) & (x.mprevclose <= x.mema10)

return (
(x.mmom >= 20) & (x.mrsi14 >= 50) & (x.mema10 >= x.mema20) &
(x.vol30 >= 50000) & (x.close >= 20) &
((monthly_bull_cross_count >= 1) | monthly_reclaim) &
(x.close <= 1.03 * x.ema20)
)

return pd.Series(False, index=x.index)


# ========================= REGIME + SCORING =========================
def regime_from_index(d):
x = features(d).dropna()
if len(x) < 30:
return "UNKNOWN", 0
z = x.iloc[-1]
score = 0
score += 25 if z.close > z.ema200 else 0
score += 20 if z.ema50 > z.ema200 else 0
score += 15 if z.ema200 > x.ema200.iloc[-20] else 0
score += 15 if z.rsi14 >= 55 else 0
score += 10 if z.close > z.ema20 else 0
score += 15 if z.relvol >= 1 else 0
if score >= 75:
return "STRONG BULL", score
if score >= 60:
return "BULL", score
if score >= 45:
return "RECOVERY / SIDEWAYS", score
if score >= 30:
return "EARLY BEAR", score
return "BEAR", score

def safety(info, d):
score = 100
flags = []
avg_value = float((d.close * d.volume).tail(20).mean()) if d is not None and not d.empty else 0
if avg_value < 2_000_000:
score -= 30
flags.append("Low traded value")
if avg_value < 500_000:
score -= 20
flags.append("Very low liquidity")
if d is not None and len(d) >= 30:
r = d.close.pct_change().tail(30)
if (r.abs() > 0.15).sum() >= 3:
score -= 15
flags.append("Abnormal volatility")
score = max(0, min(100, score))
status = "ELIGIBLE" if score >= 70 else ("CAUTION" if score >= 50 else "REJECT")
return score, status, flags

def htf_confluence(x):
def _zone_score(x, lookback, tolerance=0.035):
if len(x) < lookback + 10:
return 0
recent = x.tail(lookback)
low = float(recent.low.min())
price = float(x.close.iloc[-1])
distance = abs(price / low - 1)
near = distance <= tolerance
reaction = (float(recent.close.max()) / low - 1) if low > 0 else 0
tests = int((recent.low <= low * (1 + tolerance)).sum())
points = 0
if near:
points += 5
if reaction >= 0.20:
points += 4
elif reaction >= 0.10:
points += 2
if tests <= 2:
points += 2
elif tests <= 4:
points += 1
return min(points, 11)
q = _zone_score(x, 252, 0.06)
m = _zone_score(x, 126, 0.045)
w = _zone_score(x, 60, 0.035)
return int(round(min(20, q * 0.75 + m * 0.75 + w * 0.5)))

def footprint_score(x):
if len(x) < 60:
return 0
z = x.iloc[-1]
score = 0
recent_range = ((x.high - x.low) / x.close).tail(10).mean()
prior_range = ((x.high - x.low) / x.close).tail(40).head(30).mean()
if pd.notna(recent_range) and pd.notna(prior_range) and recent_range < prior_range * 0.8:
score += 4
v_recent = x.volume.tail(10).mean()
v_prior = x.volume.tail(40).head(30).mean()
if pd.notna(v_recent) and pd.notna(v_prior) and v_recent < v_prior * 0.9:
score += 3
if pd.notna(z.relvol) and z.relvol >= 1.5:

Stock market:
score += 4
elif pd.notna(z.relvol) and z.relvol >= 1.2:
score += 2
day_range = float(z.high - z.low)
if day_range > 0:
close_location = (float(z.close) - float(z.low)) / day_range
if close_location >= 0.75:
score += 3
elif close_location >= 0.60:
score += 1
extension = float(z.close / z.ema20 - 1) if pd.notna(z.ema20) else np.nan
if np.isfinite(extension) and 0 <= extension <= 0.04:
score += 3
if pd.notna(z.ema50) and z.close > z.ema50:
score += 3
return int(min(20, score))

def strategy_quality_score(x, s):
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
p += 10 if dist <= 0.015 else 7 if dist <= 0.025 else 4 if dist <= 0.04 else 0
p += 10 if z.close > z.ema200 else 0
p += 10 if z.wrsi14 >= 55 else 6 if z.wrsi14 >= 45 else 0
elif s == 4:
p += 10 if z.mmom >= 30 else 7 if z.mmom >= 25 else 4 if z.mmom >= 20 else 0
p += 10 if z.mema10 > z.mema20 else 0
p += 10 if z.close <= z.ema20 * 1.02 else 5 if z.close <= z.ema20 * 1.03 else 0
return int(min(30, p))

def final_setup_score(x, s, regime, safety_score):
z = x.iloc[-1]
strategy = strategy_quality_score(x, s)
htf = htf_confluence(x)
footprint = footprint_score(x)
trend = 0
trend += 4 if z.close > z.ema50 else 0
trend += 3 if z.close > z.ema200 else 0
trend += 3 if z.rsi14 >= 50 else 0
entry = 0
ext = z.close / z.ema20 - 1 if pd.notna(z.ema20) else np.nan
if np.isfinite(ext):
entry = 10 if 0 <= ext <= 0.025 else 7 if ext <= 0.04 else 3 if ext <= 0.07 else 0
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


# ========================= FLEXIBLE BACKTEST =========================
def _flexible_backtest(data, strategies, threshold, start_date, end_date):
rows = []
start = pd.Timestamp(start_date)
end = pd.Timestamp(end_date)

for ticker, df in data.items():
if df is None or len(df) < 260:
continue
df = df.sort_index()
dates = df.index[(df.index >= start) & (df.index <= end)][::5]

for dt in dates:
hist = df.loc[:dt]
if len(hist) < 260:
continue
f = features(hist).replace([np.inf, -np.inf], np.nan)
if f.empty:
continue
regime, _ = regime_from_index(hist)
safe, _, _ = safety({}, hist)

for s in strategies:
if not bool(strategy_signal(f, s).iloc[-1]):
continue
score, parts = final_setup_score(f, s, regime, safe)
if score < threshold:
continue
entry = float(hist.close.iloc[-1])

Stock market:
sl = entry * 0.93
target = entry + 3 * (entry - sl)
future = df[df.index > dt]
if future.empty:
continue
outcome = "OPEN"
exit_price = float(future.close.iloc[-1])
for _, bar in future.iterrows():
if bar.low <= sl:
outcome = "LOSS"
exit_price = sl
break
if bar.high >= target:
outcome = "WIN"
exit_price = target
break
rows.append({
"Date": dt.date(),
"Ticker": ticker.replace(".NS", ""),
"Strategy": f"S{s}",
"Score": score,
"Entry": round(entry, 2),
"SL": round(sl, 2),
"Target": round(target, 2),
"Outcome": outcome,
"R": round((exit_price - entry) / (entry - sl), 2),
"Strategy Score": parts["Strategy"],
"HTF": parts["HTF Demand"],
"Footprint": parts["Footprint"],
"Regime": regime,
"Safety": safe
})
return pd.DataFrame(rows)


def _learning_summary(bt):
if bt.empty:
return pd.DataFrame()
x = bt.copy()
x["Win"] = (x.Outcome == "WIN").astype(int)
y = x.groupby("Strategy").agg(
Signals=("Ticker", "count"),
Wins=("Win", "sum"),
WinRate=("Win", "mean"),
AvgR=("R", "mean"),
BestScore=("Score", "max")
).reset_index()
y["WinRate"] = (y.WinRate * 100).round(1)
y["AvgR"] = y.AvgR.round(2)
return y


# ========================= UI =========================
st.title("🧠 Adaptive Trading Intelligence Lab")
st.caption("Faster scanning • Flexible backtesting • Multi-strategy • ≥85 gate • Learning engine")

tabs = st.tabs([
"🏠 Dashboard", "📡 Daily Scanner", "📊 Backtest", "🔬 Forward Testing",
"🧠 Market Learning", "💎 Long-Term Fundamentals", "🏢 Small/Micro Safety",
"⚡ Live Monitor", "💾 Dhan Data Manager", "🧪 Custom Strategy"
])

with tabs[0]:
a, b, c, d = st.columns(4)
a.metric("Forward-test gate", "≥85")
b.metric("Strategies", "4")
c.metric("MTF", "Monthly / Weekly / Daily")
d.metric("Real orders", "OFF")
st.info("Score ranks setup quality. It is not a guaranteed win probability.")
st.markdown("""
Trading engine: Strategies 1–4 → MTF → market regime → setup score → forward test. 
Fast Mode available in Daily Scanner for much quicker results.
""")

with tabs[1]:
st.subheader("📡 Daily Live Scanner")

c1, c2, c3, c4 = st.columns(4)
fast_mode = c1.checkbox("⚡ Fast Mode (Nifty 500 only)", value=True, key="fast_mode")

universes = c2.multiselect(
"Universes",
["Nifty 500", "Nifty Smallcap 100", "Nifty Smallcap 250", "Nifty Midcap 150"],
default=["Nifty 500"],
key="scan_universes",
disabled=fast_mode
)
min_score = c3.number_input("Min Score", value=85, min_value=0, max_value=100, key="scan_score")
selected_strategies = c4.multiselect("Strategies", [1, 2, 3, 4], default=[1, 2, 3, 4], key="scan_strategies")

if fast_mode:
universes = ["Nifty 500"]
st.caption("Fast Mode ON → scanning only Nifty 500")

if st.button("🔄 Scan Market Now", type="primary", key="scan_button"):
try:
if not dhan_configured():
st.error("Dhan is not configured. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to Streamlit Secrets.")
st.stop()
if not selected_strategies or not universes:
st.warning("Select at least one strategy and universe.")
st.stop()

Stock market:
with st.spinner("Downloading data (this is the slowest part)..."):
idx_tickers = index_universe("Nifty 500")
idx_data = download_prices(tuple(idx_tickers), date.today() - timedelta(days=1000), date.today(), max_workers=6)
if not idx_data:
st.error("No index data returned.")
st.stop()
proxy = max(idx_data.values(), key=len)
regime, _ = regime_from_index(proxy)

universe = set()
for u in universes:
universe.update(index_universe(u))
tickers = sorted(universe)
data = download_prices(tuple(tickers), date.today() - timedelta(days=1000), date.today(), max_workers=6)

if not data:
st.error("No price data returned.")
st.stop()

rows = []
bar = st.progress(0)

for n, (ticker, df) in enumerate(data.items()):
if len(df) < 260:
bar.progress((n + 1) / max(1, len(data)))
continue
f = features(df).replace([np.inf, -np.inf], np.nan)
if len(f) < 260:
bar.progress((n + 1) / max(1, len(data)))
continue
safe, safe_status, flags = safety({}, df)

for s in selected_strategies:
sig = strategy_signal(f, s)
if not bool(sig.iloc[-1]):
continue
score, parts = final_setup_score(f, s, regime, safe)
z = f.iloc[-1]
entry = float(z.close)
stop = entry * 0.93
target = entry + 3 * (entry - stop)
rows.append({
"Score": score,
"Ticker": ticker.replace(".NS", ""),
"Strategy": f"S{s}",
"Regime": regime,
"Safety": safe_status,
"Entry": round(entry, 2),
"SL 7%": round(stop, 2),
"Target 3R": round(target, 2),
"RSI": round(float(z.rsi14), 1),
"RelVol": round(float(z.relvol), 2),
"HTF Score": parts["HTF Demand"],
"Footprint Score": parts["Footprint"],
"Strategy Score": parts["Strategy"],
"Entry Quality": parts["Entry Quality"],
"Safety Score": safe
})
bar.progress((n + 1) / max(1, len(data)))

result = pd.DataFrame(rows)
if result.empty:
st.warning("No setups found today.")
else:
result = result.sort_values(["Score", "Strategy"], ascending=[False, True])
st.subheader(f"🏆 High Quality Setups (Score ≥ {min_score})")
high = result[result["Score"] >= min_score]
if high.empty:
st.info("No setup currently meets the score gate.")
else:
st.dataframe(high, use_container_width=True, hide_index=True)

st.subheader("📋 All Qualifying Setups")
st.dataframe(result, use_container_width=True, hide_index=True)

st.subheader("📊 Strategy Coverage")
cov = []
for s in selected_strategies:
sr = result[result["Strategy"] == f"S{s}"]
cov.append({
"Strategy": f"S{s}",
"Signals": len(sr),
f"≥{min_score}": int((sr["Score"] >= min_score).sum()) if not sr.empty else 0,
"Best Score": int(sr["Score"].max()) if not sr.empty else 0
})
st.dataframe(pd.DataFrame(cov), use_container_width=True, hide_index=True)

Stock market:
except Exception as e:
st.error(f"Scanner error: {e}")

with tabs[2]:
st.subheader("📊 Backtest + Learning")
c1, c2, c3 = st.columns(3)
period = c1.selectbox("Time Span", ["6 Months", "1 Year", "2 Years", "3 Years", "Custom"], index=2)
threshold = c2.number_input("Score threshold", 0, 100, 85, 1)

if period == "Custom":
start_date = c3.date_input("Start", date.today() - timedelta(days=730))
end_date = st.date_input("End", date.today())
else:
days_map = {"6 Months": 182, "1 Year": 365, "2 Years": 730, "3 Years": 1095}
end_date = date.today()
start_date = end_date - timedelta(days=days_map[period])
c3.metric("Period", f"{start_date} → {end_date}")

if st.button("▶ Run Backtest", type="primary"):
if not dhan_configured():
st.error("Dhan credentials missing.")
else:
try:
tickers = sorted(set(sum([index_universe(u) for u in ["Nifty 500", "Nifty Smallcap 100", "Nifty Midcap 150"]], [])))
with st.spinner(f"Running backtest for {period}..."):
bd = download_prices(tickers, start_date, end_date, max_workers=6)
st.session_state["backtest_v19"] = _flexible_backtest(bd, [1, 2, 3, 4], int(threshold), start_date, end_date)
except Exception as e:
st.error(f"Backtest error: {e}")

bt = st.session_state.get("backtest_v19", pd.DataFrame())
if bt.empty:
st.info("Run a backtest to see results.")
else:
st.subheader(f"🏆 Setups ≥ {threshold}")
st.dataframe(bt.sort_values(["Score", "Date"], ascending=[False, False]).head(100), use_container_width=True, hide_index=True)
st.subheader("📈 Strategy Performance")
st.dataframe(_learning_summary(bt), use_container_width=True, hide_index=True)

with tabs[3]:
st.subheader("🔬 Forward Testing")
con = _db()
try:
ft = pd.read_sql_query("SELECT * FROM forward_tests ORDER BY created_at DESC", con)
finally:
con.close()
if ft.empty:
st.info("No forward-test records yet.")
else:
a, b, c, d = st.columns(4)
a.metric("Total", len(ft))
b.metric("Active", int((ft.status == "ACTIVE").sum()))
c.metric("Positive R", int((ft.result_r > 0).sum()))
d.metric("Avg R", round(float(ft.result_r.dropna().mean()), 2) if ft.result_r.notna().any() else 0)
st.dataframe(ft.sort_values("score", ascending=False), use_container_width=True, hide_index=True)

with tabs[4]:
st.subheader("🧠 Market Learning")
bt = st.session_state.get("backtest_v19", pd.DataFrame())
if bt.empty:
st.info("Run a backtest first.")
else:
st.dataframe(_learning_summary(bt), use_container_width=True, hide_index=True)
st.subheader("Component Importance")
rows = []
for c in ["HTF", "Footprint", "Strategy Score", "Safety"]:
if c in bt.columns:
med = bt[c].median()
hi = bt[bt[c] >= med]
lo = bt[bt[c] < med]
rows.append({
"Component": c,
"High Avg R": round(float(hi.R.mean()), 2) if len(hi) else 0,
"Low Avg R": round(float(lo.R.mean()), 2) if len(lo) else 0,
"High Win %": round(float((hi.Outcome == "WIN").mean() * 100), 1) if len(hi) else 0
})
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tabs[5]:
st.subheader("💎 Long-Term Fundamentals")
st.warning("Fundamental API not connected yet.")

with tabs[6]:
st.subheader("🏢 Small/Micro Safety")
st.caption("Independent risk layer.")

with tabs[7]:
st.subheader("⚡ Live Monitor")
st.info("WebSocket live monitoring (uses existing Dhan feed).")
